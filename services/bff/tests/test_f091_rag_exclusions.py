"""F091 RAG 索引排除 — 排除后搜索不命中、预览计数一致、恢复纳入、
F066 优先级负向、重启持久、原始条目不受影响（负向）。"""

import asyncio

import pytest

from lumirss.main import app
from lumirss.rag import MODEL_DIM, RagService
from lumirss.storage import Database

FEED = "https://excluded.example/feed.xml"
OTHER = "https://kept.example/feed.xml"


def run(coro):
    return asyncio.run(coro)


def _fake_embedder(service: RagService, counter: list[int] | None = None):
    async def fake_embed(texts):
        if counter is not None:
            counter[0] += len(texts)
        vectors = []
        for text in texts:
            vector = [0.0] * MODEL_DIM
            vector[len(text) % MODEL_DIM] = 1.0
            vectors.append(vector)
        return vectors

    service._embedder.embed = fake_embed  # noqa: SLF001 — test seam


@pytest.fixture()
def rag_env(client, monkeypatch):
    import tempfile

    tmp = tempfile.TemporaryDirectory()
    db = Database(f"{tmp.name}/lumi.sqlite")
    monkeypatch.setattr(app.state, "db", db, raising=False)
    service = RagService(db)
    _fake_embedder(service)
    app.state.rag_service = service

    async def seed():
        await db.migrate()
        from lumirss.source_ai_gate import set_ai_disabled

        await set_ai_disabled(db, FEED, False)
        await db.execute(
            "INSERT INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, content_text, published_at, read, starred, fetched_at) VALUES ('i1', 'rss:ZjAx', ?, 'F', '排除源条目', 'excluded quantum 独特内容', '2026-01-01T00:00:00Z', 0, 0, 1)",
            (FEED,),
        )
        await db.execute(
            "INSERT INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, content_text, published_at, read, starred, fetched_at) VALUES ('i2', 'rss:ZjAy', ?, 'F', '保留源条目', 'kept content 普通文本', '2026-01-01T00:00:00Z', 0, 0, 1)",
            (OTHER,),
        )
        await service.index_refs(["rss:ZjAx", "rss:ZjAy"])

    run(seed())
    try:
        yield service
    finally:
        app.state.rag_service = None
        tmp.cleanup()


def _seed_into_main_db(client):
    """route 级排除走 app.state.db —— 用 client 的临时库直接列表端点。"""


def test_f091_exclude_removes_from_search_and_restore_rebuilds(rag_env, client):
    service = rag_env
    # 初始两源都在索引中
    hits = run(service.search("quantum"))
    assert any(i["ref"] == "rss:ZjAx" for i in hits["items"])
    # 预览计数（排除前：该源现有分块数）
    pre = {i["feedUrl"]: i for i in client.get("/api/v1/rag/exclusions").json()["items"]}
    assert pre[FEED]["affectedChunks"] >= 1
    # PUT 排除
    put = client.put(
        "/api/v1/rag/exclusions", json={"feedRef": FEED, "excluded": True}
    )
    assert put.status_code == 200, put.text
    items = {i["feedUrl"]: i for i in put.json()["items"]}
    assert items[FEED]["ragExcluded"] is True
    # 排除后计数归零（与实际移除一致）
    assert items[FEED]["affectedChunks"] == 0
    # 排除后直接搜索不命中
    hits2 = run(service.search("quantum"))
    assert all(i["ref"] != "rss:ZjAx" for i in hits2["items"])
    # 重建后排除源仍不进入语料
    run(service.rebuild())
    assert run(service.search("quantum"))["items"] == [] or all(
        i["ref"] != "rss:ZjAx" for i in run(service.search("quantum"))["items"]
    )
    # 恢复纳入 → rebuild 恢复
    client.put("/api/v1/rag/exclusions", json={"feedRef": FEED, "excluded": False})
    run(service.rebuild())
    hits3 = run(service.search("quantum"))
    assert any(i["ref"] == "rss:ZjAx" for i in hits3["items"])
    # 原始条目数据不受影响（负向）
    row = run(
        rag_env._db.fetch_one(  # noqa: SLF001
            "SELECT content_text FROM search_entries WHERE entry_ref = 'rss:ZjAx'"
        )
    )
    assert row["content_text"] == "excluded quantum 独特内容"


def test_f091_ai_disabled_strict_priority(rag_env, client):
    from lumirss.source_ai_gate import set_ai_disabled

    service = rag_env
    # ai_disabled=1 且 rag_excluded=0 → 仍被排除（F066 严格优先，负向）
    run(set_ai_disabled(service._db, OTHER, True))  # noqa: SLF001
    client.put("/api/v1/rag/exclusions", json={"feedRef": OTHER, "excluded": False})
    run(service.rebuild())
    hits = run(service.search("普通文本"))
    assert all(i["ref"] != "rss:ZjAy" for i in hits["items"])
    # exclusions 列表如实展示两个开关的独立状态
    listed = client.get("/api/v1/rag/exclusions").json()["items"]
    by_feed = {i["feedUrl"]: i for i in listed}
    assert by_feed[OTHER]["aiDisabled"] is True
    assert by_feed[OTHER]["ragExcluded"] is False


def test_f091_exclusion_persists_restart(rag_env, client):
    client.put("/api/v1/rag/exclusions", json={"feedRef": FEED, "excluded": True})
    # 新 RagService 实例（模拟重启）读取同一 DB 仍生效
    fresh = RagService(rag_env._db)  # noqa: SLF001
    _fake_embedder(fresh)
    run(fresh.rebuild())
    hits = run(fresh.search("quantum"))
    assert all(i["ref"] != "rss:ZjAx" for i in hits["items"])
