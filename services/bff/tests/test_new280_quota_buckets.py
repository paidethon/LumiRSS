"""NEW-280 AI 配额分桶 — 分桶 CRUD / 用途超额 429（不静默）/ 快照近限提示。"""

from contextlib import contextmanager

from fastapi.testclient import TestClient

from lumirss.ai_conversation import ConversationService
from lumirss.ai_settings import AiSettingsStore
from lumirss.main import app
from lumirss.storage import Database
from new2xx_ab import ab_env  # noqa: F401,F811 — pytest 夹具注册
from new271_helpers import (
    FakeAdapter,
    FakeProvider,
    configure_ai,
    entry_ref,
    item_id_of,
    make_detail,
)

REF = entry_ref()
ITEM_ID = item_id_of(REF)
BODY = "配额分桶测试的正文。" * 10


def _setup():
    provider = FakeProvider(outputs=["回答一。", "回答二。", "回答三。"])
    db = Database(f"{_tmp()}/lumi.sqlite")
    adapter = FakeAdapter({ITEM_ID: make_detail(text=BODY)})
    configure_ai(db)
    conversation = ConversationService(
        db=db, adapter=adapter, settings_store=AiSettingsStore(db),
        provider_factory=_factory(provider),
    )
    return db, adapter, provider, conversation


def _factory(provider):
    async def factory(base_url: str, model: str):
        return provider

    return factory


@contextmanager
def _client(db, adapter, conversation):
    with TestClient(app) as client:
        app.state.db = db
        app.state.freshrss_adapter = adapter
        app.state.conversation_service = conversation
        yield client


def _tmp() -> str:
    import tempfile

    return tempfile.mkdtemp()


def _send(client):
    return client.post(
        f"/api/v1/entries/{REF}/conversation/messages",
        json={"question": "问题"},
    )


def test_new280_bucket_limits_purpose_without_silent_overrun():
    """chat 分桶 = 2：第三次发送 429 scope=bucket（带调整入口），不静默超额。"""
    db, adapter, provider, conversation = _setup()
    with _client(db, adapter, conversation) as client:
        put = client.put("/api/v1/ai/quota/buckets/chat", json={"maxCalls": 2})
        assert put.status_code == 200, put.text
        assert put.json()["maxCalls"] == 2

        assert _send(client).status_code == 200
        assert _send(client).status_code == 200
        assert provider.calls == 2

        third = _send(client)
        assert third.status_code == 429, third.text
        error = third.json()["error"]
        assert error["type"] == "quota_exceeded"
        assert error["scope"] == "bucket"
        assert error["purpose"] == "chat"
        assert provider.calls == 2  # 上游零请求

        snapshot = client.get("/api/v1/ai/quota/buckets").json()
        bucket = next(b for b in snapshot["buckets"] if b["purpose"] == "chat")
        assert bucket["used"] == 2
        assert bucket["remaining"] == 0
        assert bucket["nearLimit"] is True  # 接近/达到限额 → 提示调整
        assert "不会静默超额" in snapshot["honestyNote"]

        # 用户选择调整（提高上限）而不是被静默截断
        adjusted = client.put("/api/v1/ai/quota/buckets/chat", json={"maxCalls": 3})
        assert adjusted.status_code == 200
        assert _send(client).status_code == 200
        assert provider.calls == 3

        # 删除分桶 = 沿用全局（未配置 → 不拦截）
        assert (
            client.delete("/api/v1/ai/quota/buckets/chat").status_code == 204
        )
        assert _send(client).status_code == 200
        assert (
            client.delete("/api/v1/ai/quota/buckets/chat").status_code == 404
        )


def test_new280_summary_bucket_independent_of_chat():
    """分桶按用途隔离：chat 打满不影响 summary 的桶。"""
    db, adapter, provider, conversation = _setup()
    with _client(db, adapter, conversation) as client:
        assert (
            client.put("/api/v1/ai/quota/buckets/chat", json={"maxCalls": 1}).status_code
            == 200
        )
        assert _send(client).status_code == 200
        assert _send(client).status_code == 429
        snapshot = client.get("/api/v1/ai/quota/buckets").json()
        chat_bucket = next(
            b for b in snapshot["buckets"] if b["purpose"] == "chat"
        )
        assert chat_bucket["used"] == 1
        # summary 无分桶行 → 快照中没有该桶（未分桶 = 沿用全局配额）
        assert all(b["purpose"] != "summary" for b in snapshot["buckets"])


def test_new280_validation():
    """未知用途 422；maxCalls 边界 422（schema 拦截）；未知桶 404。"""
    db, adapter, provider, conversation = _setup()
    with _client(db, adapter, conversation) as client:
        assert (
            client.put(
                "/api/v1/ai/quota/buckets/nope", json={"maxCalls": 5}
            ).status_code
            == 422
        )
        assert (
            client.put(
                "/api/v1/ai/quota/buckets/chat", json={"maxCalls": 0}
            ).status_code
            == 422
        )
        assert (
            client.delete("/api/v1/ai/quota/buckets/summary").status_code == 404
        )


def test_new280_cross_user_buckets_isolated(ab_env):  # noqa: F811
    """A 的分桶与用量对 B 不可见（计数在 per-user ai_usage）。"""
    env = ab_env
    client = env["client"]
    app.state.freshrss_adapter = FakeAdapter({ITEM_ID: make_detail(text=BODY)})
    put = client.put(
        "/api/v1/ai/quota/buckets/chat", json={"maxCalls": 9}, headers=env["a"]
    )
    assert put.status_code == 200
    buckets_b = client.get("/api/v1/ai/quota/buckets", headers=env["b"]).json()
    assert all(b["purpose"] != "chat" for b in buckets_b["buckets"])
