"""RAG index (phase2 G7; recovery P0-07): derived, rebuildable semantic
retrieval that is now ACTUALLY built.

Pipeline: chunker (heading inheritance + paragraph bounds) → fastembed
bge-small-zh-v1.5 (512-dim, ONNX CPU) → sqlite-vec vec0 KNN ⊕ LIKE
lexical hits → RRF fusion. Hard properties:

- derived/rebuildable: chunks always regenerate from the RSS and library
  projections; deleting the index loses nothing;
- the index is REAL: rebuild writes every chunk into ``rag_chunks`` AND
  its vector into ``rag_vec`` inside ONE transaction (delete-then-insert
  on the same connection), so a failure leaves the previous index
  untouched; search joins ``rag_vec`` via the knn operator — the
  semantic leg hits from the vec table, not a lexical fallback;
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
  sources (other stores call this one-liner) and ``index_refs(refs)``
  re-embeds them from the projections in one transaction;
- plain search never downloads anything and degrades to lexical
  honestly (``semanticUsed=false`` + a reason).
"""

import asyncio
import importlib.util
import logging
import sqlite3
import struct
import time
from dataclasses import dataclass
from datetime import datetime
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
_MAX_STALE_REFS = 200
_MAX_INDEX_REFS = 50

_FASTEMBED_AVAILABLE = importlib.util.find_spec("fastembed") is not None


class RagModelUnavailable(Exception):
    """Embedding runtime missing or model not enabled — lexical fallback."""


class RagRebuildBusy(Exception):
    """A rebuild is already running."""


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

    def __init__(self, db: Database) -> None:
        self._db = db
        self._embedder = EmbeddingService()
        self._rebuild_lock = asyncio.Lock()
        self._vec_ready = False
        self._vec_conn: sqlite3.Connection | None = None

    # -- vec connection (loaded once; extensions are per-connection) --------

    def _vec_connection(self) -> sqlite3.Connection:
        """One persistent connection with sqlite-vec loaded (manual
        transaction control: explicit BEGIN/COMMIT/ROLLBACK)."""
        if self._vec_conn is not None:
            return self._vec_conn
        import sqlite_vec

        connection = sqlite3.connect(
            str(self._db.path), check_same_thread=False, timeout=5.0
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

    async def rebuild(self) -> dict[str, Any]:
        """Full index rebuild (bounded, serial, transactional, honest)."""
        if self._rebuild_lock.locked():
            raise RagRebuildBusy("重建已在进行中。")
        async with self._rebuild_lock:
            started = utc_now()
            try:
                await self._db.migrate()
                documents = await self._collect_documents()
                chunk_jobs: list[tuple[str, str, str, str]] = []
                for doc in documents:
                    for chunk in chunk_text(
                        doc["text"], heading=doc["title"] or None
                    ):
                        chunk_jobs.append(
                            (doc["ref"], doc["kind"], doc["title"], chunk)
                        )
                vectors: list[list[float]] = []
                if chunk_jobs:
                    vectors = await self._embedder.embed(
                        [chunk for _ref, _kind, _title, chunk in chunk_jobs]
                    )
                    if any(len(vector) != MODEL_DIM for vector in vectors):
                        raise RagModelUnavailable(
                            "embedding 模型维度与索引不符。"
                        )
                report = await asyncio.to_thread(
                    _write_index_sync, self, chunk_jobs, vectors
                )
                await self._set_setting("rag_last_rebuild", started)
                await self._clear_setting("rag_last_error")
                return {
                    "chunks": report["chunks"],
                    "elapsedMs": _elapsed_ms(started),
                }
            except Exception as exc:
                await self._set_setting("rag_last_error", str(exc)[:500])
                self._embedder.unload()  # never keep a half-broken model
                raise

    async def _collect_documents(self) -> list[dict[str, str]]:
        await self._db.migrate()
        documents: list[dict[str, str]] = []
        rss_rows = await self._db.fetch_all(
            "SELECT entry_ref, title, content_text FROM search_entries"
        )
        for row in rss_rows:
            documents.append(
                {
                    "ref": str(row["entry_ref"]),
                    "kind": "rss",
                    "title": str(row["title"] or ""),
                    "text": str(row["content_text"] or ""),
                }
            )
        lib_rows = await self._db.fetch_all(
            "SELECT ref, kind, title, body FROM search_library"
        )
        for row in lib_rows:
            documents.append(
                {
                    "ref": str(row["ref"]),
                    "kind": str(row["kind"]),
                    "title": str(row["title"] or ""),
                    "text": str(row["body"] or ""),
                }
            )
        return documents

    # -- incremental propagation (P0-07e) ------------------------------------

    async def mark_stale(self, refs: list[str]) -> int:
        """Delete index rows (chunk + vector) for changed/deleted sources.

        One-line hook for the owning stores (clip/snapshot/obsidian
        delete, entry projection sync); re-indexing happens via
        ``index_refs`` or the next full rebuild."""
        cleaned = list(dict.fromkeys(str(ref) for ref in refs))[:_MAX_STALE_REFS]
        if not cleaned:
            return 0
        await self._db.migrate()
        return await asyncio.to_thread(self._mark_stale_sync, cleaned)

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
        chunk_jobs: list[tuple[str, str, str, str]] = []
        for doc in documents:
            for chunk in chunk_text(doc["text"], heading=doc["title"] or None):
                chunk_jobs.append((doc["ref"], doc["kind"], doc["title"], chunk))
        vectors: list[list[float]] = []
        if chunk_jobs:
            vectors = await self._embedder.embed(
                [chunk for _ref, _kind, _title, chunk in chunk_jobs]
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
    chunk_jobs: list[tuple[str, str, str, str]],
    vectors: list[list[float]],
    only_refs: list[str] | None = None,
) -> dict[str, Any]:
    """Atomically (re)write the index on the vec connection.

    Full rebuild: replace ALL rows for the model. Incremental
    (``only_refs``): replace rows of exactly those refs. Chunks AND
    vectors commit together or not at all — a failure leaves the
    previous index intact. Module-level so tests can wrap it to prove
    the rollback."""
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
            for offset, ((ref, kind, title, chunk), vector) in enumerate(
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
                    )
                )
                vec_rows.append((chunk_id, serialize_vector(vector)))
            connection.executemany(
                "INSERT INTO rag_chunks (chunk_id, ref, ord, model_id, kind, title, text, embedding, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
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


# -- idle lifecycle (P0-07d) --------------------------------------------------


async def rag_idle_loop(app_state: Any) -> None:
    """Periodically release the embedding model when idle past the TTL.
    Failures are logged, never fatal."""
    logger = logging.getLogger("lumirss.rag")
    while True:
        await asyncio.sleep(_RAG_IDLE_TICK_SECONDS)
        service = getattr(app_state, "rag_service", None)
        if service is None:
            continue  # not built yet → nothing can be resident
        try:
            service.unload_if_idle()
        except Exception:  # noqa: BLE001 — lifecycle must never kill the app
            logger.exception("rag idle unload failed")


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
