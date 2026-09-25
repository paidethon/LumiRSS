"""RAG streaming-rebuild staging helpers (Q-P0-01 / F093 pause / N157).

Extracted from rag.py so the index-build module stays focused on
retrieval; this module owns ONLY the physical staging table lifecycle
and the atomic promotion of staged rows into the live index.

All SQL is a single literal at each execute site — table names are
module constants, dimensions dispatch through explicit literal
branches, and every value is bound via ``?`` placeholders. Nothing
here concatenates or interpolates values into a statement.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from lumirss.util import utc_now

if TYPE_CHECKING:
    from lumirss.rag import RagService

STAGE_TABLE = "rag_rebuild_stage"


def _stage_reset(service: RagService) -> None:
    """Drop + recreate the staging table (start of a rebuild)."""
    connection = service._vec_connection()
    connection.execute("DROP TABLE IF EXISTS rag_rebuild_stage")
    _stage_ensure(service)


def _stage_ensure(service: RagService) -> None:
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


def _stage_discard(service: RagService) -> None:
    """Failure cleanup: drop the staging table, best effort."""
    with contextlib.suppress(Exception):
        service._vec_connection().execute("DROP TABLE IF EXISTS rag_rebuild_stage")


def _stage_rows(
    service: RagService,
    batch: list[tuple[str, str, str, str, str]],
    vectors: list[list[float]],
    ord_state: dict[str, int],
    model_id: str = "",
) -> None:
    """Persist one embedded batch as compact blobs (auto-commit staging).

    ``ord_state`` carries each ref's next chunk ordinal ACROSS batches —
    a per-batch reset produced duplicate (ref, ord) pairs that blew up
    the unique index at promotion time for any corpus bigger than one
    batch. N157：行带目标 model_id，promotion 时原样带入 rag_chunks。"""
    # 惰性导入：rag.py 反向依赖本模块，避免循环。
    from lumirss.rag import serialize_vector  # noqa: PLC0415

    connection = service._vec_connection()
    rows = []
    for (ref, kind, title, chunk, doc_hash), vector in zip(batch, vectors, strict=True):
        ord_ = ord_state.get(ref, 0)
        ord_state[ref] = ord_ + 1
        rows.append((ref, ord_, kind, title, chunk, serialize_vector(vector), doc_hash, model_id))
    for row in rows:
        connection.execute(
            "INSERT INTO rag_rebuild_stage (ref, ord, kind, title, text, embedding, content_hash, model_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            row,
        )


def _promote_staged_index(
    service: RagService,
    model_id: str = "",
    model_dim: int = 0,
) -> None:
    """Promote the staged index into place in ONE short transaction.

    chunk_id is reassigned by AUTOINCREMENT; rag_vec rows follow. A
    failure rolls back to the previous index (same guarantee the old
    single-transaction rebuild gave, without its memory residency).
    P20 residual hardening: staged rows whose source row is ALREADY
    gone (deleted after their page was staged, before this promotion)
    are excluded — the promotion must never resurrect deleted content
    as ghost hits; the F093 pre-stage recheck alone could not cover
    this window.

    N157：换模型——staged 行以目标 model_id 落入 rag_chunks；目标维度
    与现有 rag_vec 不同时，vec 表在同一事务内重建（rag_meta.vec_dim
    同步更新）。旧索引在 promotion 前始终完整可查；promotion 后查询
    按 live 模型解析自然切到新维度。

    维度分支为单条完整字面量语句（384/512 = 模型目录允许的全部维度）；
    执行处不拼接任何动态值。"""
    from lumirss.rag import RagModelUnavailable  # noqa: PLC0415 — 惰性防循环

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
            if model_dim == 384:
                connection.execute("CREATE VIRTUAL TABLE rag_vec USING vec0(chunk_id INTEGER PRIMARY KEY, embedding float[384])")
            elif model_dim == 512:
                connection.execute("CREATE VIRTUAL TABLE rag_vec USING vec0(chunk_id INTEGER PRIMARY KEY, embedding float[512])")
            else:  # 目录外维度在解析处已被拒绝
                raise RagModelUnavailable("unsupported embedding dimension")
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
        connection.execute(
            "INSERT INTO rag_vec (chunk_id, embedding) SELECT chunk_id, embedding FROM rag_chunks WHERE model_id = ?",
            (model_id,),
        )
        connection.execute("DROP TABLE rag_rebuild_stage")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
