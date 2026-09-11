"""RAG unit tests (phase2 G7): chunker rules, RRF fusion, honest
degradation, vec pipeline with a FAKE embedder (no model download in
unit tests — the real-model benchmark runs separately in Gate 9)."""

import asyncio

import pytest

from lumirss.rag import (
    MODEL_ID,
    RagModelUnavailable,
    RagRebuildBusy,
    RagService,
    chunk_text,
    rrf_fuse,
    serialize_vector,
)
from lumirss.search_library import LibrarySearchWriter
from lumirss.storage import Database


def _run(coroutine):
    return asyncio_run(coroutine)


def asyncio_run(coroutine):
    import asyncio

    return asyncio.run(coroutine)


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
    import struct

    assert list(struct.unpack("<4f", blob)) == values


def test_rebuild_and_lexical_search_with_fake_embedder(rag_db, monkeypatch):
    """Fake embedder (deterministic vector) proves the full index/search
    pipeline without any model download."""
    service = RagService(rag_db)

    async def fake_embed(texts):
        return [[float(len(t) % 7), 1.0, 0.0] for t in texts]

    monkeypatch.setattr(
        service._embedder, "embed", fake_embed
    )
    # Seed the projections the index draws from.
    writer = LibrarySearchWriter(rag_db)
    _run(
        writer.upsert(
            ref="library:0b8df3e0-1f2a-4c3d-9e4f-5a6b7c8d9e0f",
            kind="clip",
            title="vLLM 发布说明",
            body="vLLM quantized inference 的发布记录。",
            url="https://example.com/vllm",
        )
    )
    report = _run(service.rebuild())
    assert report["chunks"] >= 1
    status = _run(service.status())
    assert status["enabled"] is False  # never enabled — semantic leg degraded
    result = _run(service.search("quantized"))
    assert result["semanticUsed"] is False
    assert result["semanticError"]  # honest message present
    assert any("vLLM" in item["text"] for item in result["items"])


def test_enable_requires_explicit_action(rag_db, monkeypatch):
    service = RagService(rag_db)
    # No enable → search must NOT download or load anything (lexical only).
    result = _run(service.search("anything"))
    assert result["semanticUsed"] is False
    assert "未启用" in (result["semanticError"] or "")
    # Explicit enable without fastembed would raise honestly (fastembed IS
    # installed in dev; simulate absence).
    import lumirss.rag as rag_module

    monkeypatch.setattr(rag_module, "_FASTEMBED_AVAILABLE", False)
    with pytest.raises(RagModelUnavailable):
        _run(service.enable())


def test_rebuild_busy_lock(rag_db, monkeypatch):
    service = RagService(rag_db)

    async def slow_embed(texts):
        import asyncio

        await asyncio.sleep(10)
        return [[0.0] for _ in texts]

    monkeypatch.setattr(service._embedder, "embed", slow_embed)
    from lumirss.search_library import LibrarySearchWriter

    writer = LibrarySearchWriter(rag_db)
    _run(
        writer.upsert(
            ref="library:0b8df3e0-1f2a-4c3d-9e4f-5a6b7c8d9e0f",
            kind="clip",
            title="t",
            body="b",
            url=None,
        )
    )

    import contextlib

    async def racing():
        task = asyncio.create_task(service.rebuild())
        await asyncio.sleep(0.05)
        with pytest.raises(RagRebuildBusy):
            await service.rebuild()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    awaitable = racing()
    asyncio_run(awaitable)


def test_vec_table_created_when_extension_present(rag_db):
    service = RagService(rag_db)
    available = service._ensure_vec_table()
    if available:
        # The virtual table really exists in the database file.
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


_ = serialize_vector, MODEL_ID
