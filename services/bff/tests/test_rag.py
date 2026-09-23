"""RAG unit tests (phase2 G7; recovery P0-07).

The fake embedder is deterministic (length-indexed one-hot, 512-dim) so
the FULL pipeline is provable without any model download: rebuild writes
REAL vectors into rag_vec, a semantic-only query hits via the knn leg
(zero lexical overlap), deletion propagates, rebuilds are transactional
and enable ordering is honest. The real fastembed model smoke is
opt-in via LUMI_TEST_REAL_EMBED=1 (model is cached in dev).
"""

import asyncio
import os
import struct

import pytest

from lumirss.rag import (
    MODEL_DIM,
    RagModelUnavailable,
    RagRebuildBusy,
    RagService,
    chunk_text,
    rag_index_pass,
    rrf_fuse,
    serialize_vector,
)
from lumirss.search_library import LibrarySearchWriter
from lumirss.storage import Database


def _run(coroutine):
    return asyncio.run(coroutine)


def length_vector(text: str) -> list[float]:
    """Deterministic 512-dim one-hot: index = len(text) mod 512."""
    vector = [0.0] * MODEL_DIM
    vector[len(text) % MODEL_DIM] = 1.0
    return vector


def install_fake_embedder(service: RagService) -> None:
    """Deterministic embedder bound to THIS service (no downloads)."""

    async def fake_embed(texts):
        return [length_vector(t) for t in texts]

    service._embedder.embed = fake_embed  # noqa: SLF001 — test seam


_DOC_A_TITLE = "向量检索笔记"
_DOC_A_BODY = "v" * 500  # chunk = len(title) + 3 + 500
_DOC_B_TITLE = "另一篇"
_DOC_B_BODY = "w" * 100
_DOC_A_REF = "library:0b8df3e0-1f2a-4c3d-9e4f-5a6b7c8d9e0f"
_DOC_B_REF = "library:0c9df3e0-1f2a-4c3d-9e4f-5a6b7c8d9e0f"


def _seed_projections(db: Database) -> None:
    writer = LibrarySearchWriter(db)
    _run(
        writer.upsert(
            ref=_DOC_A_REF,
            kind="clip",
            title=_DOC_A_TITLE,
            body=_DOC_A_BODY,
            url="https://example.com/a",
        )
    )
    _run(
        writer.upsert(
            ref=_DOC_B_REF,
            kind="clip",
            title=_DOC_B_TITLE,
            body=_DOC_B_BODY,
            url=None,
        )
    )


@pytest.fixture(autouse=True)
def _hermetic_fastembed_available(monkeypatch):
    """Treat the embedding runtime as AVAILABLE for every test here.

    This module proves the full pipeline with the deterministic fake
    embedder (no downloads), but ``RagService.enable()`` consults the
    module-level ``_FASTEMBED_AVAILABLE`` flag BEFORE warmup — on
    machines without the optional fastembed package every enable-gated
    test died on the honest 404-class guard before the fake ever ran.
    Same hermetic pattern as tests/test_rag_api.py::test_disable_route_
    resets_enabled and tests/test_rag_multi_user.py::fake_embedding.
    The not-installed contract stays covered: test_enable_requires_
    explicit_action re-patches the flag to False explicitly."""
    import lumirss.rag as rag_module

    monkeypatch.setattr(rag_module, "_FASTEMBED_AVAILABLE", True)


@pytest.fixture()
def rag_db(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    _run(db.migrate())
    return db


def test_chunker_paragraph_bounds_and_heading_inheritance():
    body = "\n\n".join([f"段落{index} " + "x" * 80 for index in range(20)])
    chunks = chunk_text(body, heading="transformer")
    assert all(len(c) <= 800 + 20 for c in chunks)
    assert all(c.startswith("transformer — ") for c in chunks)
    # Long single paragraph is hard-split.
    long_single = "y" * 2000
    split = chunk_text(long_single)
    assert len(split) >= 3
    assert all(len(c) <= 800 + 20 for c in split)


def test_rrf_fusion_semantic_and_lexical():
    semantic = [{"ref": "rss:a", "text": "t", "kind": "rss", "title": "a", "chunk_id": 1}]
    lexical = [
        {"ref": "rss:b", "text": "t", "kind": "rss", "title": "b", "chunk_id": 2},
        {"ref": "rss:a", "text": "t", "kind": "rss", "title": "a", "chunk_id": 1},
    ]
    fused = rrf_fuse(semantic, lexical, k=5)
    # 'a' appears in both legs → top ranked.
    assert fused[0]["ref"] == "rss:a"
    assert fused[0]["hits"] == 2
    assert any(item["ref"] == "rss:b" for item in fused)


def test_serialize_vector_roundtrip():
    values = [0.5, -1.25, 2.0, 0.0]
    blob = serialize_vector(values)
    assert len(blob) == 16
    assert list(struct.unpack("<4f", blob)) == values


def test_vec_table_created_when_extension_present(rag_db):
    service = RagService(rag_db)
    available = service._ensure_vec_table()
    if available:
        rows = rag_db._fetch_all(
            "SELECT name FROM sqlite_master WHERE name = 'rag_vec'"
        )
        assert rows
    else:
        with rag_db._connect() as conn:  # noqa: SLF001
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE name = 'rag_vec'"
            ).fetchall()
        assert rows == []


# -- P0-07 (b) THE core proof: rebuild really builds the vec index ----------


def _target_chunk_len_a() -> int:
    return len(chunk_text(_DOC_A_BODY, heading=_DOC_A_TITLE)[0])


def test_rebuild_writes_vec_rows_and_semantic_query_hits(rag_db):
    """MANDATORY proof: after enable+rebuild (1) rag_vec really contains
    one vector per chunk, (2) a DIRECT knn SELECT with a bound ``k``
    returns the chunk, (3) service.search with a query that has ZERO
    lexical overlap still finds the target via the semantic leg
    (semanticUsed=true), and (4) chunk titles are persisted (the title
    LIKE leg can match)."""
    _seed_projections(rag_db)
    service = RagService(rag_db)
    install_fake_embedder(service)

    assert _run(service.enable()) is True  # warmup-first enable path
    report = _run(service.rebuild())
    assert report["chunks"] == 2

    # (1) rag_vec rows exist — the audit's core bug (zero INSERTs) is gone.
    vec_count = _run(asyncio.to_thread(service._vec_count_sync))
    assert vec_count == 2

    # (2) direct knn proof with bound k: target chunk returns distance 0.
    target_vector = length_vector(chunk_text(_DOC_A_BODY, heading=_DOC_A_TITLE)[0])
    connection = service._vec_connection()

    def _knn():
        return connection.execute(
            "SELECT c.ref, v.distance FROM rag_vec v JOIN rag_chunks c ON c.chunk_id = v.chunk_id WHERE v.embedding MATCH ? AND k = ? ORDER BY v.distance",
            (serialize_vector(target_vector), 30),
        ).fetchall()

    knn_rows = _run(asyncio.to_thread(_knn))
    assert knn_rows[0][0] == _DOC_A_REF
    assert float(knn_rows[0][1]) == 0.0

    # (3) semantic-only search: garbage query with EXACTLY the target
    # chunk's length (→ identical deterministic vector) and ZERO
    # substring overlap with any chunk text.
    query = "ź" * _target_chunk_len_a()
    for word in ("向量", "v", "w", "笔记"):
        assert word not in query
    result = _run(service.search(query))
    assert result["semanticUsed"] is True, result["semanticError"]
    assert result["items"], "semantic leg must produce hits"
    assert result["items"][0]["ref"] == _DOC_A_REF
    assert result["items"][0]["hits"] == 1  # semantic leg only

    # (4) titles persisted → the title LIKE leg can match.
    titled = _run(service.search(_DOC_A_TITLE))
    assert any(item["ref"] == _DOC_A_REF for item in titled["items"])

    status = _run(service.status())
    assert status["enabled"] is True
    assert status["chunks"] == 2
    assert status["vecRows"] == 2
    assert status["vecTable"] is True


def test_search_degrades_honestly_without_enable(rag_db):
    service = RagService(rag_db)
    _seed_projections(rag_db)
    install_fake_embedder(service)
    _run(service.rebuild())
    result = _run(service.search("v"))
    assert result["semanticUsed"] is False
    assert "未启用" in (result["semanticError"] or "")
    assert result["items"]  # lexical leg still serves


def test_deletion_propagates_to_vec_and_chunks(rag_db):
    _seed_projections(rag_db)
    service = RagService(rag_db)
    install_fake_embedder(service)
    _run(service.enable())
    _run(service.rebuild())
    removed = _run(service.mark_stale([_DOC_A_REF]))
    assert removed >= 1
    vec_count = _run(asyncio.to_thread(service._vec_count_sync))
    assert vec_count == 1  # only doc B remains
    query = "ź" * _target_chunk_len_a()
    result = _run(service.search(query))
    assert all(item["ref"] != _DOC_A_REF for item in result["items"])


def test_rebuild_is_transactional_previous_index_survives(rag_db, monkeypatch):
    _seed_projections(rag_db)
    service = RagService(rag_db)
    install_fake_embedder(service)
    _run(service.enable())
    _run(service.rebuild())
    # Sentinel "resident model": a failure must unload it (P0-07d).
    service._embedder._model = object()  # noqa: SLF001 — test seam
    service._embedder._dim = MODEL_DIM  # noqa: SLF001

    import lumirss.rag as rag_module

    def _exploding_swap(*args, **kwargs):
        raise RuntimeError("disk exploded mid-transaction")

    monkeypatch.setattr(rag_module, "_swap_staged_index", _exploding_swap)
    with pytest.raises(RuntimeError):
        _run(service.rebuild())

    # Previous index fully intact (the swap is the atomicity boundary).
    vec_count = _run(asyncio.to_thread(service._vec_count_sync))
    assert vec_count == 2
    status = _run(service.status())
    assert "disk exploded" in (status["lastError"] or "")
    assert service._embedder.loaded is False  # model unloaded on failure


def test_rebuild_failure_mid_staging_keeps_previous_index(rag_db, monkeypatch):
    """Q-P0-01: a failure while STAGING (before the swap) must leave the
    previous index intact AND discard the staging table."""
    _seed_projections(rag_db)
    service = RagService(rag_db)
    install_fake_embedder(service)
    _run(service.enable())
    _run(service.rebuild())

    import lumirss.rag as rag_module

    monkeypatch.setattr(rag_module, "_EMBED_BATCH", 1)  # one chunk per batch
    original_stage = rag_module._stage_rows
    calls = {"n": 0}

    def _exploding_stage(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise RuntimeError("disk exploded mid-staging")
        return original_stage(*args, **kwargs)

    monkeypatch.setattr(rag_module, "_stage_rows", _exploding_stage)
    with pytest.raises(RuntimeError):
        _run(service.rebuild())

    vec_count = _run(asyncio.to_thread(service._vec_count_sync))
    assert vec_count == 2  # previous index untouched
    assert calls["n"] >= 2  # the failure happened mid-staging, not up front
    with rag_db._connect() as conn:  # noqa: SLF001
        leftover = conn.execute(
            "SELECT name FROM sqlite_master WHERE name = 'rag_rebuild_stage'"
        ).fetchall()
    assert leftover == []  # staging table cleaned up


def test_mark_stale_processes_all_refs_beyond_single_slice(rag_db):
    """Q-P1-02: deleting a whole connector (>200 refs) must not silently
    leave the tail of the list searchable."""
    service = RagService(rag_db)
    refs = [f"library:mark-{i:04d}" for i in range(250)]
    with rag_db._connect() as conn:  # noqa: SLF001
        for index, ref in enumerate(refs, start=1):
            conn.execute(
                "INSERT INTO rag_chunks (chunk_id, ref, ord, model_id, kind, title, text, embedding, created_at) VALUES (?, ?, 0, ?, 'clip', '', 'x', NULL, '2026-01-01T00:00:00+00:00')",
                (index, ref, "test-model"),
            )
    removed = _run(service.mark_stale(refs))
    assert removed == 250
    rows = rag_db._fetch_all("SELECT COUNT(*) AS n FROM rag_chunks")
    assert int(rows[0]["n"]) == 0


def test_index_refs_serializes_behind_rebuild_lock(rag_db):
    """Q-P1-01: index writers share one sqlite connection — index_refs
    must wait for a held rebuild lock instead of racing it."""
    _seed_projections(rag_db)
    service = RagService(rag_db)
    install_fake_embedder(service)
    _run(service.enable())

    async def racing():
        async with service._rebuild_lock:  # noqa: SLF001 — simulate rebuild
            task = asyncio.create_task(service.index_refs([_DOC_A_REF]))
            await asyncio.sleep(0.05)
            assert not task.done()  # blocked, not racing
        return await task

    report = _run(racing())
    assert report["updated"] == 1


def test_rebuild_spans_embed_batches_without_dup_ords(rag_db, monkeypatch):
    """Fresh-eyes P0 regression: a document whose chunk sequence crosses
    the embed-batch boundary must keep contiguous (ref, ord) — the
    per-batch reset made every real-sized corpus rebuild die on the
    rag_chunks unique index at swap time."""
    import lumirss.rag as rag_module

    monkeypatch.setattr(rag_module, "_EMBED_BATCH", 2)
    # 无段落边界的 3200 字符单段 → chunker 硬切 4×800 → 两个 embed 批，
    # 文档的 chunk 序列必然跨批（旧实现第二批 ord 从 0 重置即撞唯一索引）。
    long_body = "x" * 3200
    writer = LibrarySearchWriter(rag_db)
    _run(
        writer.upsert(
            ref="library:long-doc-1",
            kind="clip",
            title="长文一篇",
            body=long_body,
            url=None,
        )
    )
    service = RagService(rag_db)
    install_fake_embedder(service)
    _run(service.enable())
    report = _run(service.rebuild())
    assert report["chunks"] >= 4

    rows = rag_db._fetch_all(
        "SELECT ord FROM rag_chunks WHERE ref = 'library:long-doc-1' ORDER BY ord"
    )
    assert [int(r["ord"]) for r in rows] == list(range(len(rows)))
    vec_count = _run(asyncio.to_thread(service._vec_count_sync))
    assert vec_count == report["chunks"]


def test_incremental_pass_converges_new_and_deleted_rows(rag_db):
    """Q-P2-02: the incremental task must index NEW projection rows and
    sweep chunks whose source row disappeared — without a full rebuild."""
    _seed_projections(rag_db)
    service = RagService(rag_db)
    install_fake_embedder(service)
    _run(service.enable())
    _run(service.rebuild())

    doc_c_ref = "library:0daf3e0-1f2a-4c3d-9e4f-5a6b7c8d9e0f"
    writer = LibrarySearchWriter(rag_db)
    _run(
        writer.upsert(
            ref=doc_c_ref,
            kind="clip",
            title="增量新增",
            body="z" * 300,
            url=None,
        )
    )
    _run(rag_db.execute("DELETE FROM search_library WHERE ref = ?", (_DOC_B_REF,)))

    report = _run(rag_index_pass(service))
    assert report["indexed"] == 1
    assert report["swept"] == 1

    rows = rag_db._fetch_all("SELECT DISTINCT ref FROM rag_chunks ORDER BY ref")
    indexed_refs = {str(row["ref"]) for row in rows}
    assert indexed_refs == {_DOC_A_REF, doc_c_ref}
    result = _run(service.search("增量新增"))
    assert any(item["ref"] == doc_c_ref for item in result["items"])


def test_enable_warmup_failure_rolls_back(rag_db, monkeypatch):
    service = RagService(rag_db)

    async def failing_embed(texts):
        raise RagModelUnavailable("模型下载失败。")

    service._embedder.embed = failing_embed  # noqa: SLF001
    with pytest.raises(RagModelUnavailable):
        _run(service.enable())
    status = _run(service.status())
    assert status["enabled"] is False  # rolled back, never half-enabled
    assert "模型下载失败" in (status["lastError"] or "")


def test_incremental_index_refs_updates_only_target(rag_db):
    _seed_projections(rag_db)
    service = RagService(rag_db)
    install_fake_embedder(service)
    _run(service.enable())
    _run(service.rebuild())

    writer = LibrarySearchWriter(rag_db)
    _run(
        writer.upsert(
            ref=_DOC_B_REF,
            kind="clip",
            title=_DOC_B_TITLE,
            body="全新的第二篇内容" + "n" * 200,
            url=None,
        )
    )
    report = _run(service.index_refs([_DOC_B_REF, "library:does-not-exist"]))
    assert report["updated"] == 1
    assert report["missing"] == ["library:does-not-exist"]
    assert report["chunks"] >= 1

    def _texts():
        rows = rag_db._fetch_all(
            "SELECT ref, title, text FROM rag_chunks ORDER BY ref, ord"
        )
        return {str(row["ref"]): (str(row["title"]), str(row["text"])) for row in rows}

    texts = _texts()
    assert texts[_DOC_A_REF][0] == _DOC_A_TITLE  # untouched doc keeps rows
    assert texts[_DOC_B_REF][0] == _DOC_B_TITLE  # real titles (P0-07f)
    assert texts[_DOC_B_REF][1].startswith(_DOC_B_TITLE + " — ")
    vec_count = _run(asyncio.to_thread(service._vec_count_sync))
    assert vec_count == _run(service.rebuild())["chunks"]
    result = _run(service.search("全新的第二篇内容"))
    assert any(item["ref"] == _DOC_B_REF for item in result["items"])


def test_idle_unload_and_lifecycle_factory(rag_db):
    import time as _time

    service = RagService(rag_db)
    assert service.unload_if_idle() is False  # nothing loaded
    service._embedder._model = object()  # noqa: SLF001 — test seam
    # Ancient relative to the runner's monotonic clock (a fresh CI VM has
    # a small monotonic value, so an absolute 0.0 is NOT ancient there).
    service._embedder._last_used = _time.monotonic() - 10 * 3600  # noqa: SLF001
    assert service._embedder.idle_expired() is True
    assert service.unload_if_idle() is True
    assert service._embedder.loaded is False

    async def _smoke():
        from lumirss.rag import build_rag_idle_task

        class _State:
            rag_service = None  # not built → no-op tick

        task = build_rag_idle_task(_State())
        assert task is not None
        task.cancel()

    _run(_smoke())


def test_rebuild_busy_lock(rag_db):
    service = RagService(rag_db)
    _seed_projections(rag_db)

    async def slow_embed(texts):
        await asyncio.sleep(10)
        return [length_vector(t) for t in texts]

    service._embedder.embed = slow_embed  # noqa: SLF001

    import contextlib

    async def racing():
        task = asyncio.create_task(service.rebuild())
        await asyncio.sleep(0.05)
        with pytest.raises(RagRebuildBusy):
            await service.rebuild()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    _run(racing())


def test_enable_requires_explicit_action(rag_db, monkeypatch):
    service = RagService(rag_db)
    # No enable → search must NOT download or load anything (lexical only).
    result = _run(service.search("anything"))
    assert result["semanticUsed"] is False
    assert "未启用" in (result["semanticError"] or "")
    # Explicit enable without fastembed raises honestly AND records the
    # error (status.lastError) for the UI.
    import lumirss.rag as rag_module

    monkeypatch.setattr(rag_module, "_FASTEMBED_AVAILABLE", False)
    with pytest.raises(RagModelUnavailable):
        _run(service.enable())
    status = _run(service.status())
    assert status["enabled"] is False
    assert status["lastError"]


@pytest.mark.skipif(
    os.environ.get("LUMI_TEST_REAL_EMBED") != "1",
    reason="real fastembed model download/load — opt-in smoke",
)
def test_real_fastembed_smoke(rag_db):
    """Opt-in: the REAL fastembed bge-small-zh-v1.5 loads (with the
    corrected ``model_name`` kwarg), embeds at 512-dim and the full
    enable→rebuild→semantic-search pipeline works against it."""
    # Probe the REAL runtime (the module flag is patched True by the
    # hermetic autouse fixture above, so it cannot decide this skip).
    import importlib.util

    if importlib.util.find_spec("fastembed") is None:
        pytest.skip("fastembed not installed")
    _seed_projections(rag_db)
    service = RagService(rag_db)  # REAL embedder, no monkeypatching
    assert _run(service.enable()) is True
    report = _run(service.rebuild())
    assert report["chunks"] >= 1
    result = _run(service.search("另一篇"))
    assert result["semanticUsed"] is True
