"""RAG index (phase2 G7): derived, rebuildable semantic retrieval.

Pipeline: chunker (heading inheritance + paragraph bounds) → fastembed
bge-small-zh-v1.5 (512-dim, ONNX CPU) → sqlite-vec vec0 KNN ⊕ LIKE
lexical hits → RRF fusion. Hard properties:

- derived/rebuildable: chunks always regenerate from the RSS and library
  projections; deleting the index loses nothing;
- lazy + bounded: the embedding model loads ONLY on explicit enable or
  rebuild/search with an enabled index, and unloads after idle so it
  never stays resident; rebuild runs bounded and serial;
- explicit enable: the model downloads on POST /rag/enable only — plain
  search never downloads anything and degrades to lexical honestly;
- locked model identity: model id recorded per chunk; re-index replaces
  all rows for the model (no mixed-model results).
"""

import asyncio
import importlib.util
import logging
import struct
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

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
    """Lazy fastembed singleton with idle unload and a load lock."""

    def __init__(self) -> None:
        self._model = None
        self._lock = asyncio.Lock()
        self._last_used = 0.0

    @property
    def loaded(self) -> bool:
        return self._model is not None

    def idle_expired(self) -> bool:
        return (
            self._model is not None
            and time.monotonic() - self._last_used > _IDLE_UNLOAD_SECONDS
        )

    def unload(self) -> None:
        self._model = None
        import gc

        gc.collect()

    async def embed(self, texts: list[str]) -> list[list[float]]:
        async with self._lock:
            if self._model is None:
                if not _FASTEMBED_AVAILABLE:
                    raise RagModelUnavailable("fastembed 未安装。")
                from fastembed import TextEmbedding

                def _load():
                    return TextEmbedding(
                        model=MODEL_ID, providers=["CPUExecutionProvider"]
                    )

                self._model = await asyncio.to_thread(_load)
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

    # -- schema ------------------------------------------------------------

    def _ensure_vec_table(self) -> bool:
        if self._vec_ready:
            return True
        if not vec_extension_available():
            return False
        try:
            import sqlite_vec

            with self._db._connect() as connection:  # noqa: SLF001 — owned schema
                connection.enable_load_extension(True)
                connection.load_extension(sqlite_vec.loadable_path())
                connection.enable_load_extension(False)
                connection.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS rag_vec USING vec0(chunk_id INTEGER PRIMARY KEY, embedding float[512])"
                )
                connection.commit()
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

    # -- status -------------------------------------------------------------

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
            "vecTable": self._ensure_vec_table(),
            "lastRebuildAt": await self._setting("rag_last_rebuild"),
            "lastError": await self._setting("rag_last_error"),
            "fastembedAvailable": _FASTEMBED_AVAILABLE,
        }

    async def enable(self) -> bool:
        """Explicit user authorization to download/load the model."""
        if not _FASTEMBED_AVAILABLE:
            raise RagModelUnavailable("fastembed 未安装，无法启用语义索引。")
        await self._set_setting("rag_enabled", "1")
        await self._embedder.embed(["warmup"])  # failures surface now
        return True

    async def unload_model(self) -> bool:
        was = self._embedder.loaded
        self._embedder.unload()
        return was

    # -- indexing -----------------------------------------------------------

    async def rebuild(self) -> dict[str, Any]:
        """Full index rebuild (bounded, serial, honest report)."""
        if self._rebuild_lock.locked():
            raise RagRebuildBusy("重建已在进行中。")
        async with self._rebuild_lock:
            started = utc_now()
            documents = await self._collect_documents()
            chunk_jobs: list[tuple[str, str, str]] = []
            for doc in documents:
                for chunk in chunk_text(doc["text"], heading=doc["title"] or None):
                    chunk_jobs.append((doc["ref"], doc["kind"], chunk))
            if not chunk_jobs:
                await self._db.migrate()
                await self._db.execute(
                    "DELETE FROM rag_chunks WHERE model_id = ?",
                    (MODEL_ID,),
                )
                await self._set_setting("rag_last_rebuild", started)
                return {"chunks": 0, "elapsedMs": 0}
            vectors = await self._embedder.embed(
                [chunk for _ref, _kind, chunk in chunk_jobs]
            )
            await self._db.migrate()
            await self._db.execute(
                "DELETE FROM rag_chunks WHERE model_id = ?",
                (MODEL_ID,),
            )
            now = utc_now()
            for index, ((ref, kind, chunk), vector) in enumerate(
                zip(chunk_jobs, vectors, strict=True)
            ):
                await self._db.execute(
                    "INSERT INTO rag_chunks (ref, ord, model_id, kind, title, text, embedding, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        ref,
                        index,
                        MODEL_ID,
                        kind,
                        "",
                        chunk,
                        serialize_vector(vector),
                        now,
                    ),
                )
            await self._set_setting("rag_last_rebuild", started)
            await self._db.execute(
                "DELETE FROM lumi_settings WHERE key = 'rag_last_error'"
            )
            self._vec_ready = False  # force vec re-attach on next search
            return {
                "chunks": len(chunk_jobs),
                "elapsedMs": _elapsed_ms(started),
            }

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
        import sqlite_vec

        with self._db._connect() as connection:  # noqa: SLF001 — owned schema
            connection.enable_load_extension(True)
            connection.load_extension(sqlite_vec.loadable_path())
            connection.enable_load_extension(False)
            rows = connection.execute("SELECT c.chunk_id, c.ref, c.kind, c.title, c.text, v.distance FROM rag_vec v JOIN rag_chunks c ON c.chunk_id = v.chunk_id WHERE v.embedding MATCH ? AND k = ? ORDER BY v.distance", (serialize_vector(query_vec), _LEXICAL_CANDIDATES)).fetchall()
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
