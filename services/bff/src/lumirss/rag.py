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
import os
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

# N157：模型可配置化。历史常量保留为默认值/兼容别名；实际生效的模型
# 按「settings > 环境变量 > 默认」解析（RagService 构造时读环境变量，
# settings 在首个异步点惰性读取）。目录表允许的模型维度是硬编码的
# allow-list——任意 HuggingFace 模型被拒绝，而不是静默下载一个维度
# 不匹配的嵌入空间。
DEFAULT_MODEL_ID = "BAAI/bge-small-zh-v1.5"
DEFAULT_MODEL_DIM = 512
MODEL_ID = DEFAULT_MODEL_ID  # 兼容别名（旧导入点）
MODEL_DIM = DEFAULT_MODEL_DIM  # 兼容别名（旧导入点）

MODEL_CATALOG: dict[str, int] = {
    "BAAI/bge-small-zh-v1.5": 512,
    "BAAI/bge-small-en-v1.5": 384,
    "intfloat/multilingual-e5-small": 384,
}
ENV_MODEL_ID = "LUMI_RAG_MODEL_ID"
ENV_MODEL_DIM = "LUMI_RAG_MODEL_DIM"
# settings 键（每用户库；N157 切换端点写入，rebuild/swap 消费）。
SETTING_MODEL_ID = "rag_model_id"
SETTING_VEC_DIM = "rag_vec_dim"


def model_dim_for(model_id: str) -> int | None:
    """目录内的模型 → 声明维度；目录外 → None（诚实拒绝）。"""
    return MODEL_CATALOG.get(model_id)


def configured_env_model() -> tuple[str, int]:
    """N157：构造时读取的环境变量覆盖（env > 默认）。

    维度优先取目录表；目录外的 env 模型要求 LUMI_RAG_MODEL_DIM 显式
    给出（部署级自行负责维度正确性），否则回落默认——绝不猜。"""
    model_id = os.environ.get(ENV_MODEL_ID, "").strip() or DEFAULT_MODEL_ID
    dim = MODEL_CATALOG.get(model_id)
    if dim is None:
        raw = os.environ.get(ENV_MODEL_DIM, "").strip()
        try:
            dim = int(raw)
        except ValueError:
            dim = 0
        if dim <= 0:
            model_id, dim = DEFAULT_MODEL_ID, DEFAULT_MODEL_DIM
    return model_id, dim

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
# N158：局部重建作业（同一 rag_jobs 表，kind 区分；取消 = 现有暂停）。
_SUBSET_JOB_KIND = "rebuild_subset"
# N158：子集逐页推进（每页 5 个 ref 写一次进度——轮询粒度与批开销的
# 折中；≤50 的子集最多 10 页）。
_SUBSET_PAGE = 5


def chunk_scheme() -> dict[str, int]:
    """N153：当前分块方案的只读元数据（当前 chunker 无重叠，诚实为 0）。"""
    return {"maxLen": _CHUNK_MAX, "overlap": 0}

_FASTEMBED_AVAILABLE = importlib.util.find_spec("fastembed") is not None


class RagModelUnavailable(Exception):
    """Embedding runtime missing or model not enabled — lexical fallback."""


class RagRebuildBusy(Exception):
    """A rebuild is already running."""


class RagJobPaused(Exception):
    """F093：批间安全点观察到暂停请求（游标已持久化）。"""


class RagJobNotFound(Exception):
    """N158：作业不存在（映射 404，不跨用户库泄露）。"""


class RagModelUnknown(Exception):
    """N157：请求切换的模型不在目录表内（映射 400）。"""

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id
        super().__init__(f"未知模型：{model_id}")


def doc_content_hash(text: str) -> str:
    """F100：语料文档正文 hash（分块行的 content_hash 列存同一值）。"""
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


async def live_model_id(db: Database, fallback: str = DEFAULT_MODEL_ID) -> str:
    """N157：某用户库当前索引的 LIVE 模型 id（helper 模块共用）。

    rag_chunks 里只会有一个模型的行（swap 全量替换）；空索引 → fallback。"""
    row = await db.fetch_one(
        "SELECT model_id FROM rag_chunks ORDER BY chunk_id LIMIT 1"
    )
    return str(row["model_id"]) if row is not None else fallback


def vec_extension_available() -> bool:
    return importlib.util.find_spec("sqlite_vec") is not None


def serialize_vector(values: list[float]) -> bytes:
    return struct.pack(f"<{len(values)}f", *values)


def chunk_text(text: str, *, heading: str | None = None) -> list[str]:
    """Heading-inheriting paragraph grouping (300-800 chars)."""
    return [span.text for span in chunk_text_with_spans(text, heading=heading)]


@dataclass(frozen=True)
class ChunkSpan:
    """One chunk plus its source-document character span (N153).

    ``char_start``/``char_end`` index the ORIGINAL stored text such that
    the whitespace-normalized source span equals the chunk text without
    the heading prefix (the prefix is decoration, never part of the
    span). ``ord`` is the per-ref chunk ordinal (matches rag_chunks.ord).
    """

    ord: int
    text: str
    char_start: int
    char_end: int


def chunk_text_with_spans(
    text: str, *, heading: str | None = None
) -> list[ChunkSpan]:
    """N153：chunk_text 的带源文本坐标版本（单一实现，chunk_text 委托）。

    Produces byte-identical chunk strings to the historical chunk_text
    while carrying each chunk's source span, so the preview endpoint can
    show exactly what indexing WOULD store with verifiable offsets. The
    ``\\r\\n`` → ``\\n`` normalization happens first and offsets are
    mapped back to the ORIGINAL text."""
    normalized = (text or "").replace("\r\n", "\n")
    # orig index of each normalized char (+1 sentinel); \r\n pairs shrink.
    orig_of_norm: list[int] = []
    orig_i = 0
    for ch in normalized:
        orig_of_norm.append(orig_i)
        orig_i += 2 if (ch == "\n" and orig_i < len(text) and text[orig_i] == "\r") else 1
    orig_of_norm.append(min(orig_i, len(text)))

    # Paragraphs as (clean, per-clean-char normalized offsets, block offset).
    paragraphs: list[tuple[str, list[int], int]] = []
    block_start = 0
    for block in normalized.split("\n\n"):
        nonws = [pos for pos, ch in enumerate(block) if not ch.isspace()]
        if nonws:
            clean = " ".join(block.split())
            clean_pos = [block_start + pos for pos in nonws]
            paragraphs.append((clean, clean_pos, block_start))
        block_start += len(block) + 2  # split consumed the "\n\n" separator

    prefix = f"{heading} — " if heading else ""
    spans: list[ChunkSpan] = []
    buffer: list[tuple[str, list[int]]] = []
    # Accumulated buffer length = the historical string-buffer length
    # (pieces joined with "\n") — the flush condition must stay identical.
    buffer_len = 0

    def emit(pieces: list[tuple[str, list[int]]]) -> None:
        text_out = (prefix + "\n".join(p[0] for p in pieces)).strip()
        char_start = orig_of_norm[pieces[0][1][0]]
        char_end = orig_of_norm[pieces[-1][1][-1]] + 1
        spans.append(
            ChunkSpan(
                ord=len(spans), text=text_out, char_start=char_start,
                char_end=char_end,
            )
        )

    for clean, clean_pos, _block_start in paragraphs:
        if len(clean) > _CHUNK_MAX:
            if buffer:
                emit(buffer)
                buffer = []
                buffer_len = 0
            for start in range(0, len(clean), _CHUNK_MAX):
                window = clean[start : start + _CHUNK_MAX]
                window_pos = clean_pos[start : start + _CHUNK_MAX]
                spans.append(
                    ChunkSpan(
                        ord=len(spans),
                        text=(prefix + window).strip(),
                        char_start=orig_of_norm[window_pos[0]],
                        char_end=orig_of_norm[window_pos[-1]] + 1,
                    )
                )
            continue
        candidate_len = buffer_len + 1 + len(clean) if buffer else len(clean)
        if candidate_len > _CHUNK_MAX and buffer_len >= _CHUNK_MIN:
            emit(buffer)
            buffer = [(clean, clean_pos)]
            buffer_len = len(clean)
        else:
            buffer.append((clean, clean_pos))
            buffer_len = candidate_len
    if buffer:
        emit(buffer)
    return spans[:_MAX_CHUNKS_PER_REF]


class EmbeddingService:
    """Lazy fastembed holder with idle unload and a load lock.

    The constructor kwarg is ``model_name`` — fastembed 0.8 silently
    loads its DEFAULT model when the older ``model=`` alias is used, so
    the resolved identity is verified at load and the dimension is
    measured from the loaded model. N157：模型身份按实例配置（每个
    RagService 解析出自己的 active 模型）；身份变化时上层负责换实例。
    """

    def __init__(self, model_id: str = DEFAULT_MODEL_ID, model_dim: int = DEFAULT_MODEL_DIM) -> None:
        self.model_id = model_id
        self._expected_dim = model_dim
        self._model = None
        self._dim: int | None = None
        self._lock = asyncio.Lock()
        self._last_used = 0.0

    @property
    def loaded(self) -> bool:
        return self._model is not None

    @property
    def dim(self) -> int:
        """Dimension of the loaded model (declared dim before load)."""
        return self._dim if self._dim is not None else self._expected_dim

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
                        model_name=self.model_id, providers=["CPUExecutionProvider"]
                    )
                    resolved = str(getattr(model, "model_name", self.model_id))
                    if resolved != self.model_id:
                        raise RagModelUnavailable(
                            "embedding 模型身份不符：请求 "
                            f"{self.model_id}，实际加载 {resolved}。"
                        )
                    probe = [
                        [float(x) for x in vec]
                        for vec in model.embed(["维度探测"])
                    ]
                    if not probe or len(probe[0]) != self._expected_dim:
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
        # N157：环境覆盖在构造时读取（settings 在首个异步点惰性解析）。
        self._env_model_id, self._env_model_dim = configured_env_model()
        self._embedders: dict[str, EmbeddingService] = {}
        self._rebuild_lock = asyncio.Lock()
        self._vec_ready = False
        self._vec_conn: sqlite3.Connection | None = None
        # F093：测试可注入的批间暂停点（None = 生产无额外钩子）。
        self._pause_hook: Any = None

    # -- N157 模型身份解析 -----------------------------------------------------

    def _embedder_for(self, model_id: str, model_dim: int) -> EmbeddingService:
        """当前模型的 embedder（按 model_id 缓存，≤2 个驻留）。

        rebuild 换模型期间查询仍走旧模型——两个槽位让 query/build 各用
        各的实例，互不卸载；第三个身份出现时淘汰最久未用的。"""
        existing = self._embedders.get(model_id)
        if existing is None:
            existing = EmbeddingService(model_id, model_dim)
            self._embedders[model_id] = existing
            while len(self._embedders) > 2:
                oldest = next(k for k in self._embedders if k != model_id)
                self._embedders.pop(oldest).unload()
        return existing

    @property
    def _embedder(self) -> EmbeddingService:
        """兼容旧引用点：env 解析模型的 embedder（idle 卸载循环用）。"""
        return self._embedder_for(self._env_model_id, self._env_model_dim)

    async def configured_model(self) -> tuple[str, int]:
        """下一次 rebuild 将写入的模型（settings > env > 默认）。

        settings 值必须能解析出维度（目录表内，或与 env 模型一致）；
        无法解析的值诚实回落 env/默认——绝不带着未知模型重建。"""
        stored = await self._setting(SETTING_MODEL_ID)
        if stored:
            dim = MODEL_CATALOG.get(stored)
            if dim is not None:
                return stored, dim
            if stored == self._env_model_id:
                return stored, self._env_model_dim
        return self._env_model_id, self._env_model_dim

    async def live_model(self) -> tuple[str, int]:
        """当前可查询索引的模型（查询/增量都以它为准）。

        rag_chunks 里只会有一个模型的行（swap 全量替换）——取现有行的
        model_id；索引为空时回落 configured。这样 rebuild 期间旧索引
        依然完全可查（staging 是独立表），swap 后查询自然切换到新模型，
        且任何时刻都不可能混出两种维度的结果。"""
        row = await self._db.fetch_one(
            "SELECT model_id FROM rag_chunks ORDER BY chunk_id LIMIT 1"
        )
        if row is not None:
            stored = str(row["model_id"])
            dim = MODEL_CATALOG.get(stored)
            if dim is not None:
                return stored, dim
            if stored == self._env_model_id:
                return stored, self._env_model_dim
        return await self.configured_model()

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
                "CREATE TABLE IF NOT EXISTS rag_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            # N157：vec 表维度取「已建表时的记录值」；从未建过表时用
            # 环境解析出的模型维度（异步 settings 不进同步路径——swap
            # 时若目标维度不同会重建表）。
            row = connection.execute(
                "SELECT value FROM rag_meta WHERE key = 'vec_dim'"
            ).fetchone()
            dim = int(row["value"]) if row is not None else self._env_model_dim
            connection.execute(
                f"CREATE VIRTUAL TABLE IF NOT EXISTS rag_vec USING vec0(chunk_id INTEGER PRIMARY KEY, embedding float[{dim}])"
            )
            if row is None:
                connection.execute(
                    "INSERT INTO rag_meta (key, value) VALUES ('vec_dim', ?)",
                    (str(dim),),
                )
            self._vec_ready = True
        except Exception:  # noqa: BLE001 — degrade to lexical-only mode
            _logger.info("sqlite-vec unavailable; semantic leg disabled")
            self._vec_ready = False
        return self._vec_ready

    def _stored_vec_dim(self) -> int | None:
        """rag_vec 建表时的维度（rag_meta 记录；未建表 → None）。"""
        if not vec_extension_available():
            return None
        try:
            connection = self._vec_connection()
            connection.execute(
                "CREATE TABLE IF NOT EXISTS rag_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            row = connection.execute(
                "SELECT value FROM rag_meta WHERE key = 'vec_dim'"
            ).fetchone()
            return int(row["value"]) if row is not None else None
        except Exception:  # noqa: BLE001 — 元数据读不到按未建表处理
            return None

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
        model_id, dim = await self.live_model()
        row = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM rag_chunks WHERE model_id = ?",
            (model_id,),
        )
        chunks = int(row["n"]) if row is not None else 0
        configured_id, _configured_dim = await self.configured_model()
        job_section = await self._job_summary()
        return {
            "enabled": (await self._setting("rag_enabled")) == "1",
            "chunks": chunks,
            "model": model_id,
            "dim": dim,
            "rowCounts": await self.row_counts(),
            "configuredModel": configured_id,
            "vecTable": self._ensure_vec_table(),
            "vecRows": await asyncio.to_thread(self._vec_count_sync),
            "modelLoaded": any(e.loaded for e in self._embedders.values()),
            "lastRebuildAt": await self._setting("rag_last_rebuild"),
            "lastError": await self._setting("rag_last_error"),
            "fastembedAvailable": _FASTEMBED_AVAILABLE,
            # F093：最近一次重建作业（stage/done/remaining）。
            "job": job_section,
        }

    async def row_counts(self) -> dict[str, int]:
        """N157：按 model_id 的分块行数（index-version/status 回显）。"""
        rows = await self._db.fetch_all(
            "SELECT model_id, COUNT(*) AS n FROM rag_chunks GROUP BY model_id"
        )
        return {str(r["model_id"]): int(r["n"]) for r in rows}

    async def index_version(self) -> dict[str, Any]:
        """N157：GET index-version 载荷——当前可查询模型 + 各模型行数。

        modelId/dim 是 LIVE 口径（rebuild 期间仍指旧模型，swap 后自然
        切到新模型）；configuredModel 单独回显下一次重建将写入的模型。"""
        model_id, dim = await self.live_model()
        configured_id, _ = await self.configured_model()
        return {
            "modelId": model_id,
            "dim": dim,
            "rowCounts": await self.row_counts(),
            "configuredModel": configured_id,
        }

    async def set_model(self, model_id: str) -> dict[str, Any]:
        """N157：切换目标模型（下一次 rebuild 生效）。

        settings 必须落在目录表内（或与 env 模型一致）——未知模型诚实
        400，绝不静默接受一个下载不下来/维度未知的模型。切换本身不改
        现有索引（live 模型不变，旧索引继续可查可搜）。"""
        stored = str(model_id or "").strip()
        dim = MODEL_CATALOG.get(stored)
        if dim is None and stored != self._env_model_id:
            raise RagModelUnknown(stored)
        await self._set_setting(SETTING_MODEL_ID, stored)
        return {"modelId": stored, "dim": dim if dim is not None else self._env_model_dim}

    async def _job_summary(self) -> dict[str, Any] | None:
        """F093 status job 段：最近作业的进度（stage/done/remaining）。

        N158：kind=rebuild_subset 的作业按子集口径回显（done/total/
        pending），绝不套用全量语料的 remaining 估算。"""
        job = await self._job_latest()
        if job is None:
            return None
        if job["kind"] == _SUBSET_JOB_KIND:
            stats = job.get("stats") or {}
            cursor = job.get("cursor") or {}
            return {
                "jobId": job["jobId"],
                "kind": job["kind"],
                "status": job["status"],
                "stage": "refs",
                "done": int(stats.get("done", 0)),
                "remaining": len(cursor.get("pending", []) or []),
                "updatedAt": job["updatedAt"],
            }
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
        ``rag_enabled=1`` is only persisted after success. N157：预热用
        configured 模型（与下一次 rebuild 一致）。"""
        if not _FASTEMBED_AVAILABLE:
            await self._set_setting(
                "rag_last_error", "fastembed 未安装，无法启用语义索引。"
            )
            raise RagModelUnavailable("fastembed 未安装，无法启用语义索引。")
        model_id, dim = await self.configured_model()
        embedder = self._embedder_for(model_id, dim)
        try:
            await embedder.embed(["warmup"])  # downloads/loads now
        except Exception as exc:
            embedder.unload()
            await self._set_setting("rag_last_error", str(exc)[:500])
            raise
        await self._set_setting("rag_enabled", "1")
        await self._clear_setting("rag_last_error")
        return True

    async def disable(self) -> bool:
        """Turn the semantic leg off and free the model."""
        await self._set_setting("rag_enabled", "0")
        was = False
        for embedder in self._embedders.values():
            was = embedder.unload() or was
        return was

    async def unload_model(self) -> bool:
        was = False
        for embedder in self._embedders.values():
            was = embedder.unload() or was
        return was

    def unload_if_idle(self) -> bool:
        """Idle lifecycle (P0-07d): called periodically by the lifespan
        task; true when an idle model was actually released."""
        was = False
        for embedder in list(self._embedders.values()):
            if embedder.idle_expired():
                was = embedder.unload() or was
        return was

    # -- indexing -----------------------------------------------------------

    # -- F093 作业行（rag_jobs）---------------------------------------------

    async def _job_create(
        self,
        *,
        kind: str = _JOB_KIND,
        stats: dict[str, Any] | None = None,
    ) -> str:
        job_id = str(_uuid.uuid4())
        await self._db.execute(
            "INSERT INTO rag_jobs (id, kind, status, cursor_json, stats_json, updated_at) VALUES (?, ?, 'running', NULL, ?, ?)",
            (job_id, kind, json.dumps(stats if stats is not None else {"chunks": 0, "docs": 0, "skipped": []}), utc_now()),
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
        # N157：优先非终态作业（running/paused）——秒级 updated_at 并列
        # 时 uuid 决胜负会指到旧的 done 作业上，resume 就成了空操作。
        row = await self._db.fetch_one(
            "SELECT id FROM rag_jobs ORDER BY (status IN ('running', 'paused')) DESC, updated_at DESC, id DESC LIMIT 1"
        )
        if row is None:
            return None
        job = await self._job_get(str(row["id"]))
        assert job is not None
        return job

    async def job_get(self, job_id: str) -> dict[str, Any] | None:
        """N158：按 id 取作业行（公开只读视图；None = 不存在 → 404）。"""
        return await self._job_get(job_id)

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
                # N157：目标模型在 rebuild 开始时解析并写入游标——rebuild
                # 期间 live 模型（旧索引）继续可查可搜，swap 完成后查询
                # 自然切到新模型。
                target_model, target_dim = await self.configured_model()
                chunks = await self._rebuild_streaming(
                    job_id,
                    target_model=target_model,
                    target_dim=target_dim,
                )
                await self._set_setting("rag_last_rebuild", started)
                await self._clear_setting("rag_last_error")
                return {
                    "chunks": chunks,
                    "elapsedMs": _elapsed_ms(started),
                    "jobId": job_id,
                    "status": "done",
                    "modelId": target_model,
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
                for embedder in self._embedders.values():
                    embedder.unload()  # never keep a half-broken model
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
        if job["kind"] == _SUBSET_JOB_KIND:
            # N158：最近作业是子集重建——全量续建绝不吞并子集游标。
            subset = await self.resume_subset(job["jobId"])
            return {
                "chunks": 0,
                "jobId": job["jobId"],
                "status": str(subset.get("status", "done")),
                "resumed": bool(subset.get("resumed")),
            }
        if self._rebuild_lock.locked():
            raise RagRebuildBusy("重建已在进行中。")
        async with self._rebuild_lock:
            started = utc_now()
            if await self._job_get(job["jobId"]) is None:
                return {"chunks": 0, "jobId": None, "status": "idle", "resumed": False}
            await self._job_write(job["jobId"], status="running")
            try:
                cursor = job.get("cursor") or {}
                target_model = str(cursor.get("model") or "") or (await self.configured_model())[0]
                target_dim = MODEL_CATALOG.get(target_model)
                if target_dim is None:
                    target_dim = self._env_model_dim if target_model == self._env_model_id else DEFAULT_MODEL_DIM
                chunks = await self._rebuild_streaming(
                    job["jobId"],
                    target_model=target_model,
                    target_dim=target_dim,
                )
                await self._set_setting("rag_last_rebuild", started)
                await self._clear_setting("rag_last_error")
                return {
                    "chunks": chunks,
                    "elapsedMs": _elapsed_ms(started),
                    "jobId": job["jobId"],
                    "status": "done",
                    "resumed": True,
                    "modelId": target_model,
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
        """F093：请求暂停（当前文档页完成后生效）。返回作业 id。

        N158：取消 = 同一暂停机制——局部重建作业是同一 rag_jobs 表的
        running 行，最新 running 作业无论 kind 都会被此入口命中。"""
        return await self._job_pause_latest_running()

    # -- N158 局部索引重建 ----------------------------------------------------

    async def rebuild_subset(self, refs: list[str]) -> dict[str, Any]:
        """N158：局部重建——只重嵌给定 refs（≤50），绝不触碰其他分块。

        - 复用增量管线（分块 → 嵌入 → 事务内只替换这些 ref 的行，
          ``_write_index_sync(only_refs=…)``）——不走全量的 staging/
          swap 路径（那会清空整个索引，正是本特性要避免的）；
        - 进度持久化在 rag_jobs（kind=rebuild_subset）：每页写一次
          {done, total}，轮询端点据此显示工作量；
        - 取消 = 现有暂停（批间安全点观察 paused → 游标 pending
          持久化）；resume 从游标继续，已完成的 ref 绝不重复嵌入；
        - 投影中不存在的 ref 诚实汇报 ``missing``，绝不冒充成功。"""
        cleaned = list(dict.fromkeys(str(ref) for ref in refs))[:_MAX_INDEX_REFS]
        if not cleaned:
            return {"jobId": "", "status": "done", "total": 0, "updated": 0, "chunks": 0, "missing": []}
        if self._rebuild_lock.locked():
            raise RagRebuildBusy("重建已在进行中。")
        async with self._rebuild_lock:
            job_id = await self._job_create(
                kind=_SUBSET_JOB_KIND,
                stats={"done": 0, "total": len(cleaned), "chunks": 0, "missing": []},
            )
            try:
                result = await self._rebuild_subset_locked(job_id, cleaned)
                return {
                    "jobId": job_id,
                    "status": str(result.get("status", "done")),
                    "total": len(cleaned),
                    "updated": int(result.get("updated", 0)),
                    "chunks": int(result.get("chunks", 0)),
                    "missing": list(result.get("missing", [])),
                }
            except RagJobPaused:
                return {
                    "jobId": job_id,
                    "status": "paused",
                    "total": len(cleaned),
                    "updated": 0,
                    "chunks": 0,
                    "missing": [],
                }
            except Exception as exc:
                await self._job_write(job_id, status="failed", stats={"error": str(exc)[:300]})
                await self._set_setting("rag_last_error", str(exc)[:500])
                raise

    async def _rebuild_subset_locked(
        self, job_id: str, refs: list[str]
    ) -> dict[str, Any]:
        """子集推进循环：每页 _SUBSET_PAGE 个 ref，页间安全点检查暂停。"""
        pending = list(refs)
        done = 0
        chunks = 0
        missing: list[str] = []
        cursor: dict[str, Any] = {"pending": pending}
        stats: dict[str, Any] = {
            "done": 0, "total": len(refs), "chunks": 0, "missing": [],
        }
        await self._job_write(job_id, cursor=cursor, stats=stats)
        while pending:
            await self._check_pause(job_id, cursor, stats)
            page, pending = pending[:_SUBSET_PAGE], pending[_SUBSET_PAGE:]
            result = await self._index_refs_locked(page)
            done += int(result["updated"])
            chunks += int(result["chunks"])
            missing.extend(result["missing"])
            cursor = {"pending": pending}
            stats = {
                "done": done,
                "total": len(refs),
                "chunks": chunks,
                "missing": missing,
            }
            await self._job_write(job_id, cursor=cursor, stats=stats)
        await self._job_write(job_id, status="done", cursor=None, stats=stats)
        return {"status": "done", "updated": done, "chunks": chunks, "missing": missing}

    async def resume_subset(self, job_id: str | None = None) -> dict[str, Any]:
        """N158：从游标继续 paused 的子集作业（幂等；缺省 = 最近一个）。"""
        job = (
            await self._job_get(job_id)
            if job_id is not None
            else await self._job_latest()
        )
        if job is None or job["kind"] != _SUBSET_JOB_KIND or job["status"] == "done":
            return {"status": "done" if job is not None and job["status"] == "done" else "idle", "resumed": False}
        if self._rebuild_lock.locked():
            raise RagRebuildBusy("重建已在进行中。")
        async with self._rebuild_lock:
            current = await self._job_get(job["jobId"])
            if current is None or current["status"] == "done":
                return {"status": "done", "resumed": False}
            pending = list((current.get("cursor") or {}).get("pending", []) or [])
            stats = current.get("stats") or {}
            await self._job_write(job["jobId"], status="running")
            result = await self._rebuild_subset_locked_from(
                job["jobId"], pending, int(stats.get("done", 0)),
                int(stats.get("chunks", 0)), list(stats.get("missing", [])),
                int(stats.get("total", 0)) or len(pending),
            )
            return {"status": "done", "resumed": True, **result}

    async def _rebuild_subset_locked_from(
        self,
        job_id: str,
        pending: list[str],
        done: int,
        chunks: int,
        missing: list[str],
        total: int,
    ) -> dict[str, Any]:
        """resume 变体：携带续建前的累计状态（done/chunks/missing）。"""
        cursor: dict[str, Any] = {"pending": list(pending)}
        stats: dict[str, Any] = {
            "done": done, "total": total, "chunks": chunks, "missing": missing,
        }
        while pending:
            await self._check_pause(job_id, cursor, stats)
            page, pending = pending[:_SUBSET_PAGE], pending[_SUBSET_PAGE:]
            result = await self._index_refs_locked(page)
            done += int(result["updated"])
            chunks += int(result["chunks"])
            missing = list(missing) + list(result["missing"])
            cursor = {"pending": pending}
            stats = {
                "done": done, "total": total, "chunks": chunks, "missing": missing,
            }
            await self._job_write(job_id, cursor=cursor, stats=stats)
        await self._job_write(job_id, status="done", cursor=None, stats=stats)
        return {"updated": done, "chunks": chunks, "missing": missing}

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

    async def _rebuild_streaming(
        self,
        job_id: str | None = None,
        *,
        target_model: str = DEFAULT_MODEL_ID,
        target_dim: int = DEFAULT_MODEL_DIM,
    ) -> int:
        """Stream the corpus in document pages: chunk → embed → stage.

        Embeddings never accumulate (one ``_EMBED_BATCH`` of float
        vectors at a time) and the staged rows swap into the live index
        in ONE short transaction, so a failure leaves the previous index
        intact (Q-P0-01). F093：带 rag_jobs 游标——批间安全点检查暂停，
        暂停/失败后续建从游标继续，已完成的批绝不重复 embed。
        N157：staged 行带目标 model_id（可与 live 不同）；维度校验按
        目标模型声明维度。"""
        cursor: dict[str, Any] = {
            "stage": "rss",
            "after": 0,
            "chunks": 0,
            "docs": 0,
            "ord": {},
            "model": target_model,
        }
        embedder = self._embedder_for(target_model, target_dim)
        stats: dict[str, Any] = {"chunks": 0, "docs": 0, "skipped": []}
        if job_id is not None:
            job = await self._job_get(job_id)
            if job is not None and job["cursor"] is not None:
                cursor = job["cursor"]
                cursor.setdefault("model", target_model)
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
                    vectors = await embedder.embed(
                        [chunk for _ref, _kind, _title, chunk, _h in batch]
                    )
                    if any(len(vector) != target_dim for vector in vectors):
                        raise RagModelUnavailable(
                            "embedding 模型维度与索引不符。"
                        )
                    await asyncio.to_thread(
                        _stage_rows, self, batch, vectors, ord_state, target_model
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
            await asyncio.to_thread(
                _swap_staged_index, self, target_model, target_dim
            )
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
        # N157：增量写入按 LIVE 模型（换模型后由全量 rebuild 统一切换；
        # 增量路径绝不写入与现有索引不同的模型，杜绝混维度）。
        live_model_id, live_dim = await self.live_model()
        vectors: list[list[float]] = []
        if chunk_jobs:
            embedder = self._embedder_for(live_model_id, live_dim)
            vectors = await embedder.embed(
                [chunk for _ref, _kind, _title, chunk, _h in chunk_jobs]
            )
            if any(len(vector) != live_dim for vector in vectors):
                raise RagModelUnavailable("embedding 模型维度与索引不符。")
        written = await asyncio.to_thread(
            _write_index_sync,
            self,
            chunk_jobs,
            vectors,
            list(found),
            live_model_id,
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
        """Hybrid semantic ⊕ lexical with RRF; honest lexical fallback.

        N157：两条腿都只取 LIVE 模型的行，查询向量按 LIVE 模型的声明
        维度校验——维度不匹配（配置漂移/切换中途）时语义腿诚实降级，
        绝不混出两种模型的混合结果。"""
        await self._db.migrate()
        live_model_id, live_dim = await self.live_model()
        lexical_rows = await self._db.fetch_all(
            "SELECT chunk_id, ref, kind, title, text FROM rag_chunks WHERE model_id = ? AND (? IS NULL OR kind = ?) AND (text LIKE ? ESCAPE '\\' OR title LIKE ? ESCAPE '\\') LIMIT ?",
            (
                live_model_id,
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
                "model_id": live_model_id,
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
            embedder = self._embedder_for(live_model_id, live_dim)
            vectors = await embedder.embed([query])
            if len(vectors[0]) != live_dim:
                raise RagModelUnavailable(
                    "查询向量维度与活动索引不符（模型切换进行中）。"
                )
            semantic = await asyncio.to_thread(
                self._vec_search_sync, vectors[0], kind, live_model_id
            )
            for item in semantic:
                item["model_id"] = live_model_id
        except RagModelUnavailable as exc:
            semantic_error = str(exc)
        except Exception as exc:  # noqa: BLE001 — degrade, never fail search
            semantic_error = f"语义检索不可用：{exc}"
        return {
            "items": rrf_fuse(semantic, lexical, k=k),
            "semanticUsed": semantic_error is None,
            "semanticError": semantic_error,
            "modelId": live_model_id,
        }

    def _vec_search_sync(
        self, query_vec: list[float], kind: str | None, model_id: str
    ) -> list[dict[str, Any]]:
        """KNN over rag_vec (extension already loaded on the cached
        connection); joined back to chunks for text + model filter."""
        connection = self._vec_connection()
        rows = connection.execute(
            "SELECT c.chunk_id, c.ref, c.kind, c.title, c.text, v.distance FROM rag_vec v JOIN rag_chunks c ON c.chunk_id = v.chunk_id WHERE c.model_id = ? AND v.embedding MATCH ? AND k = ? ORDER BY v.distance",
            (model_id, serialize_vector(query_vec), _LEXICAL_CANDIDATES),
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
    model_id: str = DEFAULT_MODEL_ID,
) -> dict[str, Any]:
    """Atomically (re)write the index on the vec connection.

    Full rebuild: replace ALL rows for the model. Incremental
    (``only_refs``): replace rows of exactly those refs. Chunks AND
    vectors commit together or not at all — a failure leaves the
    previous index intact. Module-level so tests can wrap it to prove
    the rollback. F100：每行记录其源文档正文 hash（content_hash）。
    N157：写入的 model_id 由调用方按 LIVE 模型显式传入。"""
    if not service._ensure_vec_table():
        raise RagModelUnavailable("sqlite-vec 扩展不可用。")
    connection = service._vec_connection()
    now = utc_now()
    try:
        connection.execute("BEGIN")
        if only_refs is None:
            connection.execute("DELETE FROM rag_vec")
            connection.execute(
                "DELETE FROM rag_chunks WHERE model_id = ?", (model_id,)
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
                        model_id,
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
    already discarded it — F093 keeps staged rows across pauses).

    N157：staging 行携带 model_id（可与 live 不同）；旧 schema（无
    model_id 列）的遗留 staging 原样丢弃重建——升级点上的 paused 重建
    由 resume 从游标重新 stage，诚实而非半兼容。"""
    connection = service._vec_connection()
    connection.execute(
        "CREATE TABLE IF NOT EXISTS rag_rebuild_stage (ref TEXT NOT NULL, ord INTEGER NOT NULL, kind TEXT NOT NULL, title TEXT NOT NULL, text TEXT NOT NULL, embedding BLOB NOT NULL, content_hash TEXT)"
    )
    columns = {
        str(row["name"])
        for row in connection.execute("PRAGMA table_info(rag_rebuild_stage)").fetchall()
    }
    if "model_id" not in columns:
        connection.execute("DROP TABLE rag_rebuild_stage")
        connection.execute(
            "CREATE TABLE rag_rebuild_stage (ref TEXT NOT NULL, ord INTEGER NOT NULL, kind TEXT NOT NULL, title TEXT NOT NULL, text TEXT NOT NULL, embedding BLOB NOT NULL, content_hash TEXT, model_id TEXT NOT NULL DEFAULT '')"
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
    model_id: str = DEFAULT_MODEL_ID,
) -> None:
    """Persist one embedded batch as compact blobs (auto-commit staging).

    ``ord_state`` carries each ref's next chunk ordinal ACROSS batches —
    a per-batch reset produced duplicate (ref, ord) pairs that blew up
    the unique index at swap time for any corpus bigger than one batch
    (found by the Round-1 fresh-eyes re-audit). N157：行带目标
    model_id，swap 时原样带入 rag_chunks。"""
    connection = service._vec_connection()
    rows = []
    for (ref, kind, title, chunk, doc_hash), vector in zip(batch, vectors, strict=True):
        ord_ = ord_state.get(ref, 0)
        ord_state[ref] = ord_ + 1
        rows.append((ref, ord_, kind, title, chunk, serialize_vector(vector), doc_hash, model_id))
    connection.executemany(
        "INSERT INTO rag_rebuild_stage (ref, ord, kind, title, text, embedding, content_hash, model_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )


def _swap_staged_index(
    service: "RagService",
    model_id: str = DEFAULT_MODEL_ID,
    model_dim: int = DEFAULT_MODEL_DIM,
) -> None:
    """Swap the staged index into place in ONE short transaction.

    chunk_id is reassigned by AUTOINCREMENT; rag_vec rows follow. A
    failure rolls back to the previous index (same guarantee the old
    single-transaction rebuild gave, without its memory residency).
    P20 residual hardening: staged rows whose source row is ALREADY
    gone (deleted after their page was staged, before this swap) are
    excluded — the swap must never resurrect deleted content as ghost
    hits; the F093 pre-stage recheck alone could not cover this window.

    N157：swap 换模型——staged 行以目标 model_id 落入 rag_chunks；
    目标维度与现有 rag_vec 不同时，vec 表在同一事务内重建为
    float[target_dim]（rag_meta.vec_dim 同步更新）。旧索引在 swap
    前始终完整可查；swap 后查询按 live 模型解析自然切到新维度。"""
    if not service._ensure_vec_table():
        raise RagModelUnavailable("sqlite-vec 扩展不可用。")
    connection = service._vec_connection()
    now = utc_now()
    try:
        connection.execute("BEGIN")
        stored_dim_row = connection.execute(
            "SELECT value FROM rag_meta WHERE key = 'vec_dim'"
        ).fetchone()
        stored_dim = int(stored_dim_row["value"]) if stored_dim_row is not None else model_dim
        if stored_dim != model_dim:
            connection.execute("DROP TABLE rag_vec")
            connection.execute(
                f"CREATE VIRTUAL TABLE rag_vec USING vec0(chunk_id INTEGER PRIMARY KEY, embedding float[{model_dim}])"
            )
            connection.execute(
                "UPDATE rag_meta SET value = ? WHERE key = 'vec_dim'",
                (str(model_dim),),
            )
        connection.execute("DELETE FROM rag_vec")
        connection.execute("DELETE FROM rag_chunks")
        connection.execute(
            "INSERT INTO rag_chunks (ref, ord, model_id, kind, title, text, embedding, created_at, content_hash) SELECT s.ref, s.ord, s.model_id, s.kind, s.title, s.text, s.embedding, ?, s.content_hash FROM rag_rebuild_stage s WHERE s.model_id = ? AND (EXISTS (SELECT 1 FROM search_entries e WHERE e.entry_ref = s.ref) OR EXISTS (SELECT 1 FROM search_library l WHERE l.ref = s.ref))",
            (now, model_id),
        )
        connection.execute("INSERT INTO rag_vec (chunk_id, embedding) SELECT chunk_id, embedding FROM rag_chunks WHERE model_id = ?", (model_id,))
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
    live_model_id, _live_dim = await service.live_model()
    orphan_rows = await service._db.fetch_all("SELECT DISTINCT c.ref FROM rag_chunks c WHERE c.ref NOT IN (SELECT entry_ref FROM search_entries) AND c.ref NOT IN (SELECT ref FROM search_library) LIMIT ?", (_MAX_INDEX_REFS,))
    orphans = [str(row["ref"]) for row in orphan_rows]
    swept = await service.mark_stale(orphans) if orphans else 0

    missing_rows = await service._db.fetch_all("SELECT entry_ref AS ref FROM search_entries WHERE entry_ref NOT IN (SELECT ref FROM rag_chunks WHERE model_id = ?) AND TRIM(content_text) <> '' UNION ALL SELECT ref FROM search_library WHERE ref NOT IN (SELECT ref FROM rag_chunks WHERE model_id = ?) AND TRIM(body) <> '' ORDER BY ref LIMIT ?", (live_model_id, live_model_id, _MAX_INDEX_REFS))
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
