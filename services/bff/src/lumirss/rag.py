"""RAG index (phase2 G7; recovery P0-07): derived, rebuildable semantic
retrieval that is now ACTUALLY built.

Pipeline: chunker (heading inheritance + paragraph bounds) → fastembed
bge-small-zh-v1.5 (512-dim, ONNX CPU) → sqlite-vec vec0 KNN ⊕ LIKE
lexical hits → RRF fusion. Hard properties:

- derived/rebuildable: chunks always regenerate from the RSS and library
  projections; deleting the index loses nothing;
- the index is REAL and MEMORY-BOUNDED: rebuild streams the corpus in
  document pages (chunk → embed → serialize into a staging table), then
  swaps staging into ``rag_chunks``/``rag_vec`` inside ONE short
  transaction — a failure leaves the previous index untouched and peak
  RAM is one page, never the whole corpus (a full-corpus float-vector
  residency OOMs a 1.6GB production box); search joins ``rag_vec`` via
  the knn operator — the semantic leg hits from the vec table, not a
  lexical fallback;
- locked model identity: the fastembed kwarg is ``model_name`` (passing
  ``model=`` silently loads a DEFAULT model — fixed and now verified at
  load), the dimension is validated against the vec table, and
  re-indexing replaces all rows for the model;
- lazy + bounded: the embedding model loads ONLY on explicit enable or
  rebuild/search with an enabled index; an idle-unload task (lifespan
  factory below) unloads it after the idle TTL, and a failed rebuild or
  enable unloads immediately;
- explicit enable: warmup happens FIRST and ``rag_enabled=1`` is only
  persisted after it succeeds (no more enabled-without-model state);
- incremental propagation: ``mark_stale(refs)`` deletes rows for changed
  sources (other stores call this one-liner; the ref list is processed
  in bounded slices — never silently truncated), ``index_refs(refs)``
  re-embeds them from the projections in one transaction, and the
  incremental index task (lifespan factory below) converges NEW
  projection rows into the index and sweeps chunks whose source row is
  gone, so newly saved content becomes semantically searchable without
  a manual rebuild;
- plain search never downloads anything and degrades to lexical
  honestly (``semanticUsed=false`` + a reason).
"""

import asyncio
import contextlib
import hashlib
import importlib.util
import json
import logging
import sqlite3
import struct
import time
import uuid as _uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from lumirss.db_tx import transaction
from lumirss.storage import Database
from lumirss.util import utc_now

_logger = logging.getLogger("lumirss.rag")

MODEL_ID = "BAAI/bge-small-zh-v1.5"
MODEL_DIM = 512
_CHUNK_MIN = 200
_CHUNK_MAX = 800
_MAX_CHUNKS_PER_REF = 40
_LEXICAL_CANDIDATES = 30
_RRF_K = 60
_IDLE_UNLOAD_SECONDS = 300.0
_RAG_IDLE_TICK_SECONDS = 60.0
# Q-P1-02: stale refs are processed in bounded transaction slices — the
# full list is always consumed (a silent cap left deleted content in the
# index when a whole connector was removed).
_STALE_SLICE = 200
_MAX_INDEX_REFS = 50
# Streaming rebuild (Q-P0-01): peak memory is one document page of text
# plus one embed batch of float vectors — never the whole corpus.
_DOC_PAGE = 16
_EMBED_BATCH = 32
# F093：作业游标持久化上限与默认 kind。
_JOB_KIND = "rebuild"

_FASTEMBED_AVAILABLE = importlib.util.find_spec("fastembed") is not None


class RagModelUnavailable(Exception):
    """Embedding runtime missing or model not enabled — lexical fallback."""


class RagRebuildBusy(Exception):
    """A rebuild is already running."""


class RagJobPaused(Exception):
    """F093：批间安全点观察到暂停请求（游标已持久化）。"""


def doc_content_hash(text: str) -> str:
    """F100：语料文档正文 hash（分块行的 content_hash 列存同一值）。"""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def vec_extension_available() -> bool:
    return importlib.util.find_spec("sqlite_vec") is not None


def serialize_vector(values: list[float]) -> bytes:
    return struct.pack(f"<{len(values)}f", *values)


def chunk_text(text: str, *, heading: str | None = None) -> list[str]:
    """Heading-inheriting paragraph grouping (300-800 chars)."""
    paragraphs = []
    for block in text.replace("\r\n", "\n").split("\n\n"):
        clean = " ".join(block.split())
        if clean:
            paragraphs.append(clean)
    chunks: list[str] = []
    buffer = ""
    prefix = f"{heading} — " if heading else ""
    for paragraph in paragraphs:
        if len(paragraph) > _CHUNK_MAX:
            if buffer:
                chunks.append((prefix + buffer).strip())
                buffer = ""
            for start in range(0, len(paragraph), _CHUNK_MAX):
                chunks.append((prefix + paragraph[start : start + _CHUNK_MAX]).strip())
            continue
        candidate = f"{buffer}\n{paragraph}".strip() if buffer else paragraph
        if len(candidate) > _CHUNK_MAX and len(buffer) >= _CHUNK_MIN:
            chunks.append((prefix + buffer).strip())
            buffer = paragraph
        else:
            buffer = candidate
    if buffer:
        chunks.append((prefix + buffer).strip())
    return chunks[:_MAX_CHUNKS_PER_REF]


class EmbeddingService:
    """Lazy fastembed singleton with idle unload and a load lock.

    The constructor kwarg is ``model_name`` — fastembed 0.8 silently
    loads its DEFAULT model when the older ``model=`` alias is used, so
    the resolved identity is verified at load and the dimension is
    measured from the loaded model.
    """

    def __init__(self) -> None:
        self._model = None
        self._dim: int | None = None
        self._lock = asyncio.Lock()
        self._last_used = 0.0

    @property
    def loaded(self) -> bool:
        return self._model is not None

    @property
    def dim(self) -> int:
        """Dimension of the loaded model (declared MODEL_DIM before load)."""
        return self._dim if self._dim is not None else MODEL_DIM

    def idle_expired(self) -> bool:
        return (
            self._model is not None
            and time.monotonic() - self._last_used > _IDLE_UNLOAD_SECONDS
        )

    def unload(self) -> bool:
        was = self._model is not None
        self._model = None
        self._dim = None
        import gc

        gc.collect()
        return was

    async def embed(self, texts: list[str]) -> list[list[float]]:
        async with self._lock:
            if self._model is None:
                if not _FASTEMBED_AVAILABLE:
                    raise RagModelUnavailable("fastembed 未安装。")
                from fastembed import TextEmbedding

                def _load():
                    model = TextEmbedding(
                        model_name=MODEL_ID, providers=["CPUExecutionProvider"]
                    )
                    resolved = str(getattr(model, "model_name", MODEL_ID))
                    if resolved != MODEL_ID:
                        raise RagModelUnavailable(
                            "embedding 模型身份不符：请求 "
                            f"{MODEL_ID}，实际加载 {resolved}。"
                        )
                    probe = [
                        [float(x) for x in vec]
                        for vec in model.embed(["维度探测"])
                    ]
                    if not probe or len(probe[0]) != MODEL_DIM:
                        raise RagModelUnavailable(
                            "embedding 模型维度与索引不符。"
                        )
                    return model, len(probe[0])

                self._model, self._dim = await asyncio.to_thread(_load)
            self._last_used = time.monotonic()

            def _embed():
                return [[float(x) for x in vec] for vec in self._model.embed(texts)]

            vectors = await asyncio.to_thread(_embed)
            self._last_used = time.monotonic()
            return vectors


@dataclass
class RagStatus:
    enabled: bool
    chunks: int
    model: str
    vecTable: bool
    lastRebuildAt: str | None
    lastError: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "chunks": self.chunks,
            "model": self.model,
            "vecTable": self.vecTable,
            "lastRebuildAt": self.lastRebuildAt,
            "lastError": self.lastError,
            "fastembedAvailable": _FASTEMBED_AVAILABLE,
        }


class RagService:
    """Index build + hybrid retrieval over the derived projections."""

    def __init__(self, db: Database, db_path: str | Path | None = None) -> None:
        self._db = db
        # 0067 isolation: pin the vec-connection file AT CONSTRUCTION.
        # A RoutingDatabase resolves ``.path`` through the CURRENT user
        # context; resolving it lazily at first vec use let whichever
        # account touched a shared instance first pin THEIR file for
        # everyone after (cross-account index leak). Callers build the
        # service inside the owning user's context, so the pinned path
        # is that owner's file for the instance's whole life.
        self._db_path: Path | None = Path(db_path) if db_path is not None else None
        self._embedder = EmbeddingService()
        self._rebuild_lock = asyncio.Lock()
        self._vec_ready = False
        self._vec_conn: sqlite3.Connection | None = None
        # F093：测试可注入的批间暂停点（None = 生产无额外钩子）。
        self._pause_hook: Any = None

    # -- vec connection (loaded once; extensions are per-connection) --------

    @property
    def _resolved_db_path(self) -> Path:
        """The concrete file the vec connection binds to (pinned when the
        builder supplied one; legacy ``db.path`` fallback otherwise)."""
        return self._db_path if self._db_path is not None else self._db.path

    def _vec_connection(self) -> sqlite3.Connection:
        """One persistent connection with sqlite-vec loaded (manual
        transaction control: explicit BEGIN/COMMIT/ROLLBACK)."""
        if self._vec_conn is not None:
            return self._vec_conn
        import sqlite_vec

        connection = sqlite3.connect(
            str(self._resolved_db_path), check_same_thread=False, timeout=5.0
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=5000")
        connection.enable_load_extension(True)
        connection.load_extension(sqlite_vec.loadable_path())
        connection.enable_load_extension(False)
        connection.isolation_level = None  # manual transactions
        self._vec_conn = connection
        return connection

    def close(self) -> None:
        if self._vec_conn is not None:
            self._vec_conn.close()
            self._vec_conn = None
        self._vec_ready = False

    def _ensure_vec_table(self) -> bool:
        if self._vec_ready:
            return True
        if not vec_extension_available():
            return False
        try:
            connection = self._vec_connection()
            connection.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS rag_vec USING vec0(chunk_id INTEGER PRIMARY KEY, embedding float[512])"
            )
            self._vec_ready = True
        except Exception:  # noqa: BLE001 — degrade to lexical-only mode
            _logger.info("sqlite-vec unavailable; semantic leg disabled")
            self._vec_ready = False
        return self._vec_ready

    # -- settings helpers ---------------------------------------------------

    async def _setting(self, key: str) -> str | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT value FROM lumi_settings WHERE key = ?", (key,)
        )
        return str(row["value"]) if row is not None else None

    async def _set_setting(self, key: str, value: str) -> None:
        await self._db.migrate()
        existing = await self._db.fetch_one(
            "SELECT key FROM lumi_settings WHERE key = ?", (key,)
        )
        if existing is None:
            await self._db.execute(
                "INSERT INTO lumi_settings (key, value, updated_at) VALUES (?, ?, ?)",
                (key, value, utc_now()),
            )
        else:
            await self._db.execute(
                "UPDATE lumi_settings SET value = ?, updated_at = ? WHERE key = ?",
                (value, utc_now(), key),
            )

    async def _clear_setting(self, key: str) -> None:
        await self._db.migrate()
        await self._db.execute(
            "DELETE FROM lumi_settings WHERE key = ?", (key,)
        )

    # -- status -------------------------------------------------------------

    def _vec_count_sync(self) -> int:
        if not self._ensure_vec_table():
            return 0
        row = self._vec_connection().execute(
            "SELECT COUNT(*) AS n FROM rag_vec"
        ).fetchone()
        return int(row["n"]) if row is not None else 0

    async def status(self) -> dict[str, Any]:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM rag_chunks WHERE model_id = ?",
            (MODEL_ID,),
        )
        chunks = int(row["n"]) if row is not None else 0
        job_section = await self._job_summary()
        return {
            "enabled": (await self._setting("rag_enabled")) == "1",
            "chunks": chunks,
            "model": MODEL_ID,
            "dim": MODEL_DIM,
            "vecTable": self._ensure_vec_table(),
            "vecRows": await asyncio.to_thread(self._vec_count_sync),
            "modelLoaded": self._embedder.loaded,
            "lastRebuildAt": await self._setting("rag_last_rebuild"),
            "lastError": await self._setting("rag_last_error"),
            "fastembedAvailable": _FASTEMBED_AVAILABLE,
            # F093：最近一次重建作业（stage/done/remaining）。
            "job": job_section,
        }

    async def _job_summary(self) -> dict[str, Any] | None:
        """F093 status job 段：最近作业的进度（stage/done/remaining）。"""
        job = await self._job_latest()
        if job is None:
            return None
        stage = (job.get("cursor") or {}).get("stage")
        done = int((job.get("stats") or {}).get("chunks", 0))
        docs_done = int((job.get("stats") or {}).get("docs", 0))
        remaining: int | None = None
        if job["status"] == "running" or job["status"] == "paused":
            row_rss = await self._db.fetch_one("SELECT COUNT(*) AS n FROM search_entries")
            row_lib = await self._db.fetch_one("SELECT COUNT(*) AS n FROM search_library")
            total = int(row_rss["n"] if row_rss else 0) + int(row_lib["n"] if row_lib else 0)
            remaining = max(total - docs_done, 0)
        return {
            "jobId": job["jobId"],
            "kind": job["kind"],
            "status": job["status"],
            "stage": stage,
            "done": done,
            "remaining": remaining,
            "updatedAt": job["updatedAt"],
        }

    async def enable(self) -> bool:
        """Explicit user authorization to download/load the model.

        Warmup FIRST (failures surface before any state changes);
        ``rag_enabled=1`` is only persisted after success."""
        if not _FASTEMBED_AVAILABLE:
            await self._set_setting(
                "rag_last_error", "fastembed 未安装，无法启用语义索引。"
            )
            raise RagModelUnavailable("fastembed 未安装，无法启用语义索引。")
        try:
            await self._embedder.embed(["warmup"])  # downloads/loads now
        except Exception as exc:
            self._embedder.unload()
            await self._set_setting("rag_last_error", str(exc)[:500])
            raise
        await self._set_setting("rag_enabled", "1")
        await self._clear_setting("rag_last_error")
        return True

    async def disable(self) -> bool:
        """Turn the semantic leg off and free the model."""
        await self._set_setting("rag_enabled", "0")
        return self._embedder.unload()

    async def unload_model(self) -> bool:
        return self._embedder.unload()

    def unload_if_idle(self) -> bool:
        """Idle lifecycle (P0-07d): called periodically by the lifespan
        task; true when an idle model was actually released."""
        if self._embedder.idle_expired():
            return self._embedder.unload()
        return False

    # -- indexing -----------------------------------------------------------

    # -- F093 作业行（rag_jobs）---------------------------------------------

    async def _job_create(self) -> str:
        job_id = str(_uuid.uuid4())
        await self._db.execute(
            "INSERT INTO rag_jobs (id, kind, status, cursor_json, stats_json, updated_at) VALUES (?, ?, 'running', NULL, ?, ?)",
            (job_id, _JOB_KIND, json.dumps({"chunks": 0, "docs": 0, "skipped": []}), utc_now()),
        )
        return job_id

    async def _job_get(self, job_id: str) -> dict[str, Any] | None:
        row = await self._db.fetch_one(
            "SELECT id, kind, status, cursor_json, stats_json, updated_at FROM rag_jobs WHERE id = ?",
            (job_id,),
        )
        if row is None:
            return None
        return {
            "jobId": str(row["id"]),
            "kind": str(row["kind"]),
            "status": str(row["status"]),
            "cursor": json.loads(str(row["cursor_json"])) if row["cursor_json"] else None,
            "stats": json.loads(str(row["stats_json"])) if row["stats_json"] else {},
            "updatedAt": str(row["updated_at"]),
        }

    async def _job_latest(self) -> dict[str, Any] | None:
        row = await self._db.fetch_one(
            "SELECT id FROM rag_jobs ORDER BY updated_at DESC, id DESC LIMIT 1"
        )
        if row is None:
            return None
        job = await self._job_get(str(row["id"]))
        assert job is not None
        return job

    async def _job_pause_request(self, job_id: str) -> bool:
        """设置暂停请求（当前批完成后生效）；False = 作业不在运行。"""
        row = await self._db.fetch_one(
            "SELECT id FROM rag_jobs WHERE id = ? AND status = 'running'",
            (job_id,),
        )
        if row is None:
            return False
        await self._db.execute(
            "UPDATE rag_jobs SET status = 'paused', updated_at = ? WHERE id = ?",
            (utc_now(), job_id),
        )
        return True

    async def _job_pause_latest_running(self) -> str | None:
        row = await self._db.fetch_one(
            "SELECT id FROM rag_jobs WHERE status = 'running' ORDER BY updated_at DESC LIMIT 1"
        )
        if row is None:
            return None
        job_id = str(row["id"])
        await self._job_pause_request(job_id)
        return job_id

    async def _job_write(self, job_id: str, *, status: str | None = None, cursor: dict | None = None, stats: dict | None = None) -> None:
        row = await self._job_get(job_id)
        if row is None:
            return
        await self._db.execute(
            "UPDATE rag_jobs SET status = ?, cursor_json = ?, stats_json = ?, updated_at = ? WHERE id = ?",
            (
                status or row["status"],
                json.dumps(cursor, ensure_ascii=False) if cursor is not None else (json.dumps(row["cursor"], ensure_ascii=False) if row["cursor"] else None),
                json.dumps(stats if stats is not None else row["stats"], ensure_ascii=False),
                utc_now(),
                job_id,
            ),
        )

    async def rebuild(self) -> dict[str, Any]:
        """Full index rebuild as a PAUSABLE batched job (F093).

        Same synchronous contract as before (await → done report), but
        the loop checkpoints a rag_jobs row between document pages: a
        concurrent pause request flips the job row and the loop stops at
        the next safe point, persisting its cursor for ``resume_rebuild``.
        """
        if self._rebuild_lock.locked():
            raise RagRebuildBusy("重建已在进行中。")
        async with self._rebuild_lock:
            started = utc_now()
            job_id = await self._job_create()
            try:
                await self._db.migrate()
                chunks = await self._rebuild_streaming(job_id)
                await self._set_setting("rag_last_rebuild", started)
                await self._clear_setting("rag_last_error")
                return {
                    "chunks": chunks,
                    "elapsedMs": _elapsed_ms(started),
                    "jobId": job_id,
                    "status": "done",
                }
            except RagJobPaused:
                job = await self._job_get(job_id)
                return {
                    "chunks": int((job or {}).get("stats", {}).get("chunks", 0)),
                    "elapsedMs": _elapsed_ms(started),
                    "jobId": job_id,
                    "status": "paused",
                }
            except Exception as exc:
                await self._job_write(job_id, status="failed", stats={"error": str(exc)[:300]})
                await self._set_setting("rag_last_error", str(exc)[:500])
                self._embedder.unload()  # never keep a half-broken model
                raise

    async def resume_rebuild(self) -> dict[str, Any]:
        """F093：从持久化游标继续 paused/failed 的重建（幂等）。

        已 done 的作业直接返回完成态，不重复 embed；进程重启后新建
        实例同样可续（游标与 staging 都在同一个 SQLite 文件里）。"""
        job = await self._job_latest()
        if job is None or job["status"] == "done":
            return {
                "chunks": job["stats"].get("chunks", 0) if job else 0,
                "jobId": job["jobId"] if job else None,
                "status": "done" if job else "idle",
                "resumed": False,
            }
        if self._rebuild_lock.locked():
            raise RagRebuildBusy("重建已在进行中。")
        async with self._rebuild_lock:
            started = utc_now()
            if await self._job_get(job["jobId"]) is None:
                return {"chunks": 0, "jobId": None, "status": "idle", "resumed": False}
            await self._job_write(job["jobId"], status="running")
            try:
                chunks = await self._rebuild_streaming(job["jobId"])
                await self._set_setting("rag_last_rebuild", started)
                await self._clear_setting("rag_last_error")
                return {
                    "chunks": chunks,
                    "elapsedMs": _elapsed_ms(started),
                    "jobId": job["jobId"],
                    "status": "done",
                    "resumed": True,
                }
            except RagJobPaused:
                return {
                    "chunks": job["stats"].get("chunks", 0),
                    "jobId": job["jobId"],
                    "status": "paused",
                    "resumed": True,
                }
            except Exception as exc:
                await self._job_write(job["jobId"], status="failed", stats={"error": str(exc)[:300]})
                raise

    async def pause_rebuild(self) -> str | None:
        """F093：请求暂停（当前文档页完成后生效）。返回作业 id。"""
        return await self._job_pause_latest_running()

    async def _check_pause(self, job_id: str, cursor: dict[str, Any], stats: dict[str, Any]) -> None:
        """批间安全点：暂停请求 → 游标持久化 → 抛 RagJobPaused。"""
        if self._pause_hook is not None:  # 测试注入的同步暂停点
            await self._pause_hook(job_id)
        job = await self._job_get(job_id)
        if job is not None and job["status"] == "paused":
            await self._job_write(job_id, status="paused", cursor=cursor, stats=stats)
            raise RagJobPaused()

    async def _corpus_page(
        self, stage: str, after: Any
    ) -> tuple[list[dict[str, str]], Any, bool]:
        """一页语料（F093 游标化分页）。返回 (docs, next_after, exhausted)。"""
        await self._db.migrate()
        if stage == "rss":
            # F066 + F091：AI 禁用与索引排除来源都不进入语料
            #（ai_disabled 严格优先；此处取并集）。
            from lumirss.rag_exclusions import rag_excluded_feed_set
            from lumirss.source_ai_gate import ai_disabled_feed_set

            disabled_feeds = await ai_disabled_feed_set(self._db)
            disabled_feeds = disabled_feeds | await rag_excluded_feed_set(self._db)
            rows = await self._db.fetch_all(
                "SELECT id, entry_ref, feed_url, title, content_text FROM search_entries WHERE id > ? ORDER BY id LIMIT ?",
                (after, _DOC_PAGE),
            )
            if not rows:
                return [], after, True
            next_after = int(rows[-1]["id"])
            docs = [
                {
                    "ref": str(row["entry_ref"]),
                    "kind": "rss",
                    "title": str(row["title"] or ""),
                    "text": str(row["content_text"] or ""),
                }
                for row in rows
                if str(row["feed_url"] or "") not in disabled_feeds
            ]
            return docs, next_after, False
        rows = await self._db.fetch_all(
            "SELECT ref, kind, title, body FROM search_library WHERE ref > ? ORDER BY ref LIMIT ?",
            (after, _DOC_PAGE),
        )
        if not rows:
            return [], after, True
        next_after = str(rows[-1]["ref"])
        docs = [
            {
                "ref": str(row["ref"]),
                "kind": str(row["kind"]),
                "title": str(row["title"] or ""),
                "text": str(row["body"] or ""),
            }
            for row in rows
        ]
        return docs, next_after, False

    async def _refs_still_present(
        self, docs: list[dict[str, str]]
    ) -> tuple[list[dict[str, str]], list[str]]:
        """F093：staging 前复核来源仍存在；中途删除的源跳过并记录。"""
        present: list[dict[str, str]] = []
        skipped: list[str] = []
        for doc in docs:
            if doc["kind"] == "rss":
                row = await self._db.fetch_one(
                    "SELECT entry_ref FROM search_entries WHERE entry_ref = ?",
                    (doc["ref"],),
                )
            else:
                row = await self._db.fetch_one(
                    "SELECT ref FROM search_library WHERE ref = ?", (doc["ref"],)
                )
            if row is not None:
                present.append(doc)
            else:
                skipped.append(doc["ref"])
        return present, skipped

    async def _rebuild_streaming(self, job_id: str | None = None) -> int:
        """Stream the corpus in document pages: chunk → embed → stage.

        Embeddings never accumulate (one ``_EMBED_BATCH`` of float
        vectors at a time) and the staged rows swap into the live index
        in ONE short transaction, so a failure leaves the previous index
        intact (Q-P0-01). F093：带 rag_jobs 游标——批间安全点检查暂停，
        暂停/失败后续建从游标继续，已完成的批绝不重复 embed。"""
        cursor: dict[str, Any] = {
            "stage": "rss",
            "after": 0,
            "chunks": 0,
            "docs": 0,
            "ord": {},
        }
        stats: dict[str, Any] = {"chunks": 0, "docs": 0, "skipped": []}
        if job_id is not None:
            job = await self._job_get(job_id)
            if job is not None and job["cursor"] is not None:
                cursor = job["cursor"]
                stats = {
                    "chunks": cursor.get("chunks", 0),
                    "docs": cursor.get("docs", 0),
                    "skipped": list(job["stats"].get("skipped", [])),
                }
                # 断点续建：staging 可能在上次失败清理中丢失——确保存在
                #（已 staged 的行原样保留，游标对齐）。
                await asyncio.to_thread(_stage_ensure, self)
            else:
                await asyncio.to_thread(_stage_reset, self)
        else:
            await asyncio.to_thread(_stage_reset, self)
        try:
            # Per-ref chunk ordinals must survive batch boundaries (the
            # UNIQUE(ref, ord, model_id) index) — the counter state is
            # part of the persisted cursor, so resume never restarts it.
            ord_state: dict[str, int] = dict(cursor.get("ord", {}))
            stage = cursor.get("stage", "rss")
            after: Any = cursor.get("after", 0)
            while True:
                docs, next_after, exhausted = await self._corpus_page(stage, after)
                if exhausted:
                    if stage == "rss":
                        stage, after = "library", ""
                        continue
                    break
                if docs:
                    docs, skipped_refs = await self._refs_still_present(docs)
                    if skipped_refs:
                        stats["skipped"] = list(stats.get("skipped", [])) + skipped_refs
                jobs: list[tuple[str, str, str, str, str]] = []
                for doc in docs:
                    doc_hash = doc_content_hash(doc["text"])
                    for chunk in chunk_text(doc["text"], heading=doc["title"] or None):
                        jobs.append(
                            (doc["ref"], doc["kind"], doc["title"], chunk, doc_hash)
                        )
                for start in range(0, len(jobs), _EMBED_BATCH):
                    batch = jobs[start : start + _EMBED_BATCH]
                    vectors = await self._embedder.embed(
                        [chunk for _ref, _kind, _title, chunk, _h in batch]
                    )
                    if any(len(vector) != MODEL_DIM for vector in vectors):
                        raise RagModelUnavailable(
                            "embedding 模型维度与索引不符。"
                        )
                    await asyncio.to_thread(
                        _stage_rows, self, batch, vectors, ord_state
                    )
                    stats["chunks"] = int(stats.get("chunks", 0)) + len(batch)
                    cursor["chunks"] = stats["chunks"]
                stats["docs"] = int(stats.get("docs", 0)) + len(docs)
                cursor["docs"] = stats["docs"]
                cursor["stage"] = stage
                cursor["after"] = next_after
                cursor["ord"] = ord_state
                after = next_after
                if job_id is not None:
                    await self._job_write(job_id, cursor=cursor, stats=stats)
                    await self._check_pause(job_id, cursor, stats)
            await asyncio.to_thread(_swap_staged_index, self)
            if job_id is not None:
                await self._job_write(
                    job_id, status="done", cursor=None, stats=stats
                )
            return int(stats.get("chunks", 0))
        except RagJobPaused:
            # 暂停不是失败：staging 与游标原样保留，等待 resume。
            raise
        except BaseException:
            await asyncio.to_thread(_stage_discard, self)
            raise

    async def _document_pages(self) -> AsyncIterator[list[dict[str, str]]]:
        """Keyset-paged corpus reader (search_entries by id, then
        search_library by ref) — never a whole-table fetch_all.

        F091：AI 禁用与 rag_excluded 来源不进入语料（与 rebuild 的
        _corpus_page 同一排除口径）。"""
        stage, after = "rss", 0
        while True:
            docs, next_after, exhausted = await self._corpus_page(stage, after)
            if exhausted:
                if stage == "rss":
                    stage, after = "library", ""
                    continue
                break
            after = next_after
            if docs:
                yield docs

    # -- incremental propagation (P0-07e) ------------------------------------

    async def mark_stale(self, refs: list[str], *, wait: bool = True) -> int:
        """Delete index rows (chunk + vector) for changed/deleted sources.

        One-line hook for the owning stores (clip/snapshot/obsidian
        delete, entry projection sync); re-indexing happens via
        ``index_refs`` or the incremental task. The FULL list is
        consumed in bounded transaction slices — truncating here used to
        leave deleted content searchable (Q-P1-02).

        ``wait=False`` (request-path callers): skip with a log when a
        rebuild/indexing holds the lock instead of blocking the HTTP
        request for its remaining duration — correctness converges via
        the incremental task's orphan sweep."""
        cleaned = list(dict.fromkeys(str(ref) for ref in refs))
        if not cleaned:
            return 0
        await self._db.migrate()
        if not wait and self._rebuild_lock.locked():
            _logger.warning(
                "rag index busy; deferring invalidation of %d refs to the orphan sweep",
                len(cleaned),
            )
            return 0
        async with self._rebuild_lock:
            removed = 0
            for start in range(0, len(cleaned), _STALE_SLICE):
                removed += await asyncio.to_thread(
                    self._mark_stale_sync, cleaned[start : start + _STALE_SLICE]
                )
        return removed

    def _mark_stale_sync(self, refs: list[str]) -> int:
        removed = 0
        if self._ensure_vec_table():
            connection = self._vec_connection()
            try:
                connection.execute("BEGIN")
                for ref in refs:
                    connection.execute(
                        "DELETE FROM rag_vec WHERE chunk_id IN (SELECT chunk_id FROM rag_chunks WHERE ref = ?)",
                        (ref,),
                    )
                    cursor = connection.execute(
                        "DELETE FROM rag_chunks WHERE ref = ?", (ref,)
                    )
                    removed += max(cursor.rowcount or 0, 0)
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            return removed

        def _fallback(connection):
            total = 0
            for ref in refs:
                cursor = connection.execute(
                    "DELETE FROM rag_chunks WHERE ref = ?", (ref,)
                )
                total += max(cursor.rowcount or 0, 0)
            return total

        removed = transaction(self._db, _fallback)
        return int(removed or 0)

    async def index_refs(self, refs: list[str]) -> dict[str, Any]:
        """Incremental re-index: re-chunk+re-embed ONLY the given refs
        from the projections and atomically replace their rows."""
        cleaned = list(dict.fromkeys(str(ref) for ref in refs))[:_MAX_INDEX_REFS]
        if not cleaned:
            return {"updated": 0, "chunks": 0, "missing": []}
        await self._db.migrate()
        async with self._rebuild_lock:
            return await self._index_refs_locked(cleaned)

    async def _index_refs_locked(
        self, cleaned: list[str]
    ) -> dict[str, Any]:
        documents: list[dict[str, str]] = []
        found: set[str] = set()
        for ref in cleaned:
            row = await self._db.fetch_one(
                "SELECT entry_ref, title, content_text FROM search_entries WHERE entry_ref = ?",
                (ref,),
            )
            if row is not None:
                documents.append(
                    {
                        "ref": str(row["entry_ref"]),
                        "kind": "rss",
                        "title": str(row["title"] or ""),
                        "text": str(row["content_text"] or ""),
                    }
                )
                found.add(ref)
                continue
            row = await self._db.fetch_one(
                "SELECT ref, kind, title, body FROM search_library WHERE ref = ?",
                (ref,),
            )
            if row is not None:
                documents.append(
                    {
                        "ref": str(row["ref"]),
                        "kind": str(row["kind"]),
                        "title": str(row["title"] or ""),
                        "text": str(row["body"] or ""),
                    }
                )
                found.add(ref)
        chunk_jobs: list[tuple[str, str, str, str, str]] = []
        for doc in documents:
            doc_hash = doc_content_hash(doc["text"])
            for chunk in chunk_text(doc["text"], heading=doc["title"] or None):
                chunk_jobs.append((doc["ref"], doc["kind"], doc["title"], chunk, doc_hash))
        vectors: list[list[float]] = []
        if chunk_jobs:
            vectors = await self._embedder.embed(
                [chunk for _ref, _kind, _title, chunk, _h in chunk_jobs]
            )
            if any(len(vector) != MODEL_DIM for vector in vectors):
                raise RagModelUnavailable("embedding 模型维度与索引不符。")
        written = await asyncio.to_thread(
            _write_index_sync, self, chunk_jobs, vectors, list(found)
        )
        return {
            "updated": len(found),
            "chunks": written["chunks"],
            "missing": [ref for ref in cleaned if ref not in found],
        }

    # -- retrieval ----------------------------------------------------------

    async def search(
        self, query: str, *, k: int = 8, kind: str | None = None
    ) -> dict[str, Any]:
        """Hybrid semantic ⊕ lexical with RRF; honest lexical fallback."""
        await self._db.migrate()
        lexical_rows = await self._db.fetch_all(
            "SELECT chunk_id, ref, kind, title, text FROM rag_chunks WHERE model_id = ? AND (? IS NULL OR kind = ?) AND (text LIKE ? ESCAPE '\\' OR title LIKE ? ESCAPE '\\') LIMIT ?",
            (
                MODEL_ID,
                kind,
                kind,
                f"%{_escape_like(query)}%",
                f"%{_escape_like(query)}%",
                _LEXICAL_CANDIDATES,
            ),
        )
        lexical = [
            {
                "chunk_id": int(row["chunk_id"]),
                "ref": str(row["ref"]),
                "kind": str(row["kind"]),
                "title": str(row["title"]),
                "text": str(row["text"]),
            }
            for row in lexical_rows
        ]
        semantic: list[dict[str, Any]] = []
        semantic_error: str | None = None
        try:
            if (await self._setting("rag_enabled")) != "1":
                raise RagModelUnavailable("语义索引未启用。")
            if not self._ensure_vec_table():
                raise RagModelUnavailable("sqlite-vec 扩展不可用。")
            vectors = await self._embedder.embed([query])
            semantic = await asyncio.to_thread(
                self._vec_search_sync, vectors[0], kind
            )
        except RagModelUnavailable as exc:
            semantic_error = str(exc)
        except Exception as exc:  # noqa: BLE001 — degrade, never fail search
            semantic_error = f"语义检索不可用：{exc}"
        return {
            "items": rrf_fuse(semantic, lexical, k=k),
            "semanticUsed": semantic_error is None,
            "semanticError": semantic_error,
        }

    def _vec_search_sync(
        self, query_vec: list[float], kind: str | None
    ) -> list[dict[str, Any]]:
        """KNN over rag_vec (extension already loaded on the cached
        connection); joined back to chunks for text + model filter."""
        connection = self._vec_connection()
        rows = connection.execute(
            "SELECT c.chunk_id, c.ref, c.kind, c.title, c.text, v.distance FROM rag_vec v JOIN rag_chunks c ON c.chunk_id = v.chunk_id WHERE c.model_id = ? AND v.embedding MATCH ? AND k = ? ORDER BY v.distance",
            (MODEL_ID, serialize_vector(query_vec), _LEXICAL_CANDIDATES),
        ).fetchall()
        results = [
            {
                "chunk_id": int(row[0]),
                "ref": str(row[1]),
                "kind": str(row[2]),
                "title": str(row[3]),
                "text": str(row[4]),
            }
            for row in rows
        ]
        if kind is not None:
            results = [r for r in results if r["kind"] == kind]
        return results


def _write_index_sync(
    service: "RagService",
    chunk_jobs: list[tuple[str, str, str, str, str]],
    vectors: list[list[float]],
    only_refs: list[str] | None = None,
) -> dict[str, Any]:
    """Atomically (re)write the index on the vec connection.

    Full rebuild: replace ALL rows for the model. Incremental
    (``only_refs``): replace rows of exactly those refs. Chunks AND
    vectors commit together or not at all — a failure leaves the
    previous index intact. Module-level so tests can wrap it to prove
    the rollback. F100：每行记录其源文档正文 hash（content_hash）。"""
    if not service._ensure_vec_table():
        raise RagModelUnavailable("sqlite-vec 扩展不可用。")
    connection = service._vec_connection()
    now = utc_now()
    try:
        connection.execute("BEGIN")
        if only_refs is None:
            connection.execute("DELETE FROM rag_vec")
            connection.execute(
                "DELETE FROM rag_chunks WHERE model_id = ?", (MODEL_ID,)
            )
        else:
            for ref in only_refs:
                connection.execute(
                    "DELETE FROM rag_vec WHERE chunk_id IN (SELECT chunk_id FROM rag_chunks WHERE ref = ?)",
                    (ref,),
                )
                connection.execute(
                    "DELETE FROM rag_chunks WHERE ref = ?", (ref,)
                )
        if chunk_jobs:
            row = connection.execute(
                "SELECT COALESCE(MAX(chunk_id), 0) AS m FROM rag_chunks"
            ).fetchone()
            base = int(row["m"]) if row is not None else 0
            chunk_rows = []
            vec_rows = []
            for offset, ((ref, kind, title, chunk, doc_hash), vector) in enumerate(
                zip(chunk_jobs, vectors, strict=True), start=1
            ):
                chunk_id = base + offset
                chunk_rows.append(
                    (
                        chunk_id,
                        ref,
                        offset - 1,
                        MODEL_ID,
                        kind,
                        title,
                        chunk,
                        serialize_vector(vector),
                        now,
                        doc_hash,
                    )
                )
                vec_rows.append((chunk_id, serialize_vector(vector)))
            connection.executemany(
                "INSERT INTO rag_chunks (chunk_id, ref, ord, model_id, kind, title, text, embedding, created_at, content_hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                chunk_rows,
            )
            connection.executemany(
                "INSERT INTO rag_vec (chunk_id, embedding) VALUES (?, ?)",
                vec_rows,
            )
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    return {"chunks": len(chunk_jobs)}


# -- streaming rebuild staging (Q-P0-01 / F093 pause) -------------------------


def _stage_reset(service: "RagService") -> None:
    """Drop + recreate the staging table (start of a rebuild)."""
    connection = service._vec_connection()
    connection.execute("DROP TABLE IF EXISTS rag_rebuild_stage")
    _stage_ensure(service)


def _stage_ensure(service: "RagService") -> None:
    """Create the staging table when absent (resume after a failure that
    already discarded it — F093 keeps staged rows across pauses)."""
    connection = service._vec_connection()
    connection.execute(
        "CREATE TABLE IF NOT EXISTS rag_rebuild_stage (ref TEXT NOT NULL, ord INTEGER NOT NULL, kind TEXT NOT NULL, title TEXT NOT NULL, text TEXT NOT NULL, embedding BLOB NOT NULL, content_hash TEXT)"
    )


def _stage_discard(service: "RagService") -> None:
    """Failure cleanup: drop the staging table, best effort."""
    with contextlib.suppress(Exception):
        service._vec_connection().execute("DROP TABLE IF EXISTS rag_rebuild_stage")


def _stage_rows(
    service: "RagService",
    batch: list[tuple[str, str, str, str, str]],
    vectors: list[list[float]],
    ord_state: dict[str, int],
) -> None:
    """Persist one embedded batch as compact blobs (auto-commit staging).

    ``ord_state`` carries each ref's next chunk ordinal ACROSS batches —
    a per-batch reset produced duplicate (ref, ord) pairs that blew up
    the unique index at swap time for any corpus bigger than one batch
    (found by the Round-1 fresh-eyes re-audit)."""
    connection = service._vec_connection()
    rows = []
    for (ref, kind, title, chunk, doc_hash), vector in zip(batch, vectors, strict=True):
        ord_ = ord_state.get(ref, 0)
        ord_state[ref] = ord_ + 1
        rows.append((ref, ord_, kind, title, chunk, serialize_vector(vector), doc_hash))
    connection.executemany(
        "INSERT INTO rag_rebuild_stage (ref, ord, kind, title, text, embedding, content_hash) VALUES (?, ?, ?, ?, ?, ?, ?)",
        rows,
    )


def _swap_staged_index(service: "RagService") -> None:
    """Swap the staged index into place in ONE short transaction.

    chunk_id is reassigned by AUTOINCREMENT; rag_vec rows follow. A
    failure rolls back to the previous index (same guarantee the old
    single-transaction rebuild gave, without its memory residency)."""
    if not service._ensure_vec_table():
        raise RagModelUnavailable("sqlite-vec 扩展不可用。")
    connection = service._vec_connection()
    now = utc_now()
    try:
        connection.execute("BEGIN")
        connection.execute("DELETE FROM rag_vec")
        connection.execute("DELETE FROM rag_chunks WHERE model_id = ?", (MODEL_ID,))
        connection.execute("INSERT INTO rag_chunks (ref, ord, model_id, kind, title, text, embedding, created_at, content_hash) SELECT ref, ord, ?, kind, title, text, embedding, ?, content_hash FROM rag_rebuild_stage", (MODEL_ID, now))
        connection.execute("INSERT INTO rag_vec (chunk_id, embedding) SELECT chunk_id, embedding FROM rag_chunks WHERE model_id = ?", (MODEL_ID,))
        connection.execute("DROP TABLE rag_rebuild_stage")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise


# -- incremental convergence (Q-P2-02) ----------------------------------------


async def rag_index_pass(service: "RagService") -> dict[str, Any]:
    """One incremental convergence pass over the projections.

    NEW projection rows become searchable (anti-join) and chunks whose
    source row is gone are swept — the two legs ``mark_stale`` hooks
    could not cover. Content that mutates in place under the same ref
    still needs the next full rebuild (documented limitation). Bounded:
    at most ``_MAX_INDEX_REFS`` refs per leg per pass; empty-text rows
    are excluded from the missing leg (they can never produce chunks
    and would otherwise permanently occupy the pass budget)."""
    await service._db.migrate()
    if (await service._setting("rag_enabled")) != "1":
        return {"indexed": 0, "swept": 0, "skipped": "disabled"}
    orphan_rows = await service._db.fetch_all("SELECT DISTINCT c.ref FROM rag_chunks c WHERE c.ref NOT IN (SELECT entry_ref FROM search_entries) AND c.ref NOT IN (SELECT ref FROM search_library) LIMIT ?", (_MAX_INDEX_REFS,))
    orphans = [str(row["ref"]) for row in orphan_rows]
    swept = await service.mark_stale(orphans) if orphans else 0

    missing_rows = await service._db.fetch_all("SELECT entry_ref AS ref FROM search_entries WHERE entry_ref NOT IN (SELECT ref FROM rag_chunks WHERE model_id = ?) AND TRIM(content_text) <> '' UNION ALL SELECT ref FROM search_library WHERE ref NOT IN (SELECT ref FROM rag_chunks WHERE model_id = ?) AND TRIM(body) <> '' ORDER BY ref LIMIT ?", (MODEL_ID, MODEL_ID, _MAX_INDEX_REFS))
    missing = [str(row["ref"]) for row in missing_rows]
    result = (
        await service.index_refs(missing)
        if missing
        else {"updated": 0, "chunks": 0, "missing": []}
    )
    return {"indexed": result["updated"], "swept": swept}


async def rag_incremental_loop(app_state: Any, interval: float) -> None:
    """Periodically converge each user's semantic index (0067/O163).
    Failures are isolated per user and logged, never fatal.

    Per-user RagService instances live in ``user_services`` (the embed
    model is heavy — the idle loop unloads them after the TTL). When no
    instance exists yet the loop probes RAG-enabled under that user's
    context, so an enabled deployment converges without a prior request.
    """
    from lumirss.user_scope import for_each_active_user

    async def index_user(uid: str) -> None:
        cache = app_state.user_services
        service: RagService | None = cache.get((uid, "rag_service"))
        if service is None:
            # Built inside user_context(uid): db.path resolves to THIS
            # user's file, and pinning it keeps the vec connection bound
            # to the owner even if a call later escapes the context.
            probe = RagService(app_state.db, db_path=app_state.db.path)
            if (await probe._setting("rag_enabled")) != "1":  # noqa: SLF001
                return  # RAG never enabled for this user → no service
            service = probe
            cache[(uid, "rag_service")] = service
        await rag_index_pass(service)

    while True:
        await asyncio.sleep(interval)
        await for_each_active_user(app_state, index_user)


def build_rag_incremental_task(app_state: Any, interval: float) -> asyncio.Task:
    """Lifespan wiring factory. Callers must pass a positive interval —
    main.py owns the ``> 0`` (disabled) gate; this factory fails fast on
    a zero/negative value instead of starting a sleep(0) hot loop."""
    if interval <= 0:
        raise ValueError("rag incremental interval must be a positive number of seconds")
    return asyncio.create_task(rag_incremental_loop(app_state, interval))


# -- idle lifecycle (P0-07d) --------------------------------------------------


async def rag_idle_loop(app_state: Any) -> None:
    """Periodically release idle embedding models (per-user instances).
    Failures are logged, never fatal."""
    logger = logging.getLogger("lumirss.rag")
    while True:
        await asyncio.sleep(_RAG_IDLE_TICK_SECONDS)
        cache = getattr(app_state, "user_services", None)
        if not cache:
            continue  # no per-user service built yet → nothing resident
        for key, service in list(cache.items()):
            if key[1] != "rag_service":
                continue
            try:
                service.unload_if_idle()
            except Exception:  # noqa: BLE001 — lifecycle must never kill the app
                logger.exception("rag idle unload failed for %s", key[0])


def build_rag_idle_task(app_state: Any) -> asyncio.Task:
    """Lifespan wiring factory — main.py creates the task in ONE line
    (exact diff in the recovery report). Disabling is implicit: with the
    RAG service never built, every tick is a no-op."""
    return asyncio.create_task(rag_idle_loop(app_state))


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _elapsed_ms(started_iso: str) -> int:
    delta = datetime.fromisoformat(utc_now()) - datetime.fromisoformat(started_iso)
    return int(delta.total_seconds() * 1000)


def rrf_fuse(
    semantic: list[dict[str, Any]],
    lexical: list[dict[str, Any]],
    *,
    k: int,
) -> list[dict[str, Any]]:
    """Reciprocal-rank fusion; both legs optional (classic formulation)."""
    scores: dict[str, dict[str, Any]] = {}

    def add(items: list[dict[str, Any]], weight: float) -> None:
        for rank, item in enumerate(items):
            entry = scores.setdefault(
                item["ref"], {**item, "score": 0.0, "hits": 0}
            )
            entry["score"] += weight / (_RRF_K + rank + 1)
            entry["hits"] += 1

    add(semantic, 1.0)
    add(lexical, 1.0)
    ranked = sorted(scores.values(), key=lambda e: (-e["score"], e["ref"]))
    return ranked[:k]
