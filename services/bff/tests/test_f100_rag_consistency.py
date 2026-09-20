"""F100 RAG 版本失配修复 — 正文变更列入、仅标题不列（负向）、修复后新分块
生效旧分块消失、模型切换全列、无失配空态。"""

import asyncio

import pytest

from lumirss.main import app
from lumirss.rag import MODEL_DIM, MODEL_ID, RagService
from lumirss.search_library import LibrarySearchWriter
from lumirss.storage import Database

REF = "library:consistency-doc"


def run(coro):
    return asyncio.run(coro)


def _fake_embedder(service: RagService):
    async def fake_embed(texts):
        vectors = []
        for text in texts:
            vector = [0.0] * MODEL_DIM
            vector[len(text) % MODEL_DIM] = 1.0
            vectors.append(vector)
        return vectors

    service._embedder.embed = fake_embed  # noqa: SLF001


@pytest.fixture()
def cons_env(client, monkeypatch):
    import tempfile

    tmp = tempfile.TemporaryDirectory()
    db = Database(f"{tmp.name}/lumi.sqlite")
    monkeypatch.setattr(app.state, "db", db, raising=False)
    service = RagService(db)
    _fake_embedder(service)
    app.state.rag_service = service

    async def seed():
        await db.migrate()
        writer = LibrarySearchWriter(db)
        await writer.upsert(
            ref=REF, kind="clip", title="一致性文档", body="原始正文内容 alpha。",
            url=None,
        )
        await service.index_refs([REF])

    run(seed())
    try:
        yield service
    finally:
        app.state.rag_service = None
        tmp.cleanup()


def test_f100_content_change_listed_title_change_not(cons_env, client):
    service = cons_env
    # 无失配 → 空态
    empty = client.get("/api/v1/rag/inconsistencies")
    assert empty.status_code == 200
    assert empty.json()["items"] == []
    # 仅标题/元数据变化 → 不列（负向）
    async def _retitle():
        db = service._db  # noqa: SLF001
        await db.migrate()
        await db.execute(
            "UPDATE search_library SET title = '新标题而已' WHERE ref = ?", (REF,)
        )

    run(_retitle())
    listed = client.get("/api/v1/rag/inconsistencies").json()["items"]
    assert all(i["ref"] != REF for i in listed)
    # 正文变更 → 列入（basis content_hash）
    async def _rebody():
        db = service._db  # noqa: SLF001
        await db.migrate()
        await db.execute(
            "UPDATE search_library SET body = '更新后的正文内容 beta。' WHERE ref = ?",
            (REF,),
        )

    run(_rebody())
    listed2 = client.get("/api/v1/rag/inconsistencies").json()["items"]
    hit = next((i for i in listed2 if i["ref"] == REF), None)
    assert hit is not None
    assert hit["basis"] == "content_hash"


def test_f100_repair_swaps_chunks_and_search_uses_new(cons_env, client):
    service = cons_env
    async def _rebody():
        db = service._db  # noqa: SLF001
        await db.migrate()
        await db.execute(
            "UPDATE search_library SET body = '修复后的全新文本 gamma。' WHERE ref = ?",
            (REF,),
        )

    run(_rebody())
    # 修复前列表命中新文本不可能（旧分块还在）
    before = run(service.search("gamma"))["items"]
    assert all(i["ref"] != REF for i in before)
    repair = client.post("/api/v1/rag/repair", json={"refs": [REF]})
    assert repair.status_code == 200, repair.text
    assert repair.json()["repaired"] == [REF]
    # 修复后检索用新分块且旧分块消失（搜索断言）
    after = run(service.search("gamma"))["items"]
    assert any(i["ref"] == REF for i in after)
    chunks = run(
        service._db.fetch_all(  # noqa: SLF001
            "SELECT text FROM rag_chunks WHERE ref = ?", (REF,)
        )
    )
    assert all("原始正文" not in c["text"] for c in chunks)
    # 清单回到空态
    listed = client.get("/api/v1/rag/inconsistencies").json()["items"]
    assert all(i["ref"] != REF for i in listed)


def test_f100_model_switch_lists_all_with_basis(cons_env, client):
    service = cons_env
    run(
        service._db.execute(  # noqa: SLF001
            "UPDATE rag_chunks SET model_id = 'old/model-v0' WHERE ref = ?",
            (REF,),
        )
    )
    listed = client.get("/api/v1/rag/inconsistencies").json()
    assert listed["items"] and listed["items"][0]["basis"] == "embedding_model"
    assert listed["modelId"] == MODEL_ID
