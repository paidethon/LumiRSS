"""NEW-278 AI 输入隐私过滤 — 显式字段勾选 / 过滤差异 / 发送真实生效。"""

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
BODY = "隐私过滤测试的正文，保持稳定。" * 10
NOTE = "我的私人笔记，可能含有敏感信息。"


def _setup():
    provider = FakeProvider(outputs=["回答。"])
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


def test_new278_exclusions_apply_to_preview_and_send():
    """勾选 feedTitle/userNote → 预览如实剔除，发送时这些段真的不进输入。"""
    db, adapter, provider, conversation = _setup()
    with _client(db, adapter, conversation) as client:
        set_filters = client.put(
            "/api/v1/ai/privacy-filters",
            json={"exclude": ["feedTitle", "userNote"]},
        )
        assert set_filters.status_code == 200, set_filters.text
        assert set_filters.json()["exclude"] == ["feedTitle", "userNote"]
        assert "不会自动识别" in set_filters.json()["honestyNote"]

        preview = client.post(
            f"/api/v1/entries/{REF}/ai-input-preview",
            json={"purpose": "conversation", "note": NOTE, "question": "问题"},
        ).json()
        sections = {s["key"]: s for s in preview["sections"]}
        assert sections["feedTitle"]["included"] is False
        assert sections["feedTitle"]["effectiveChars"] == 0
        assert sections["userNote"]["included"] is False
        assert sections["body"]["included"] is True

        sent = client.post(
            f"/api/v1/entries/{REF}/conversation/messages",
            json={"question": "问题", "note": NOTE},
        )
        assert sent.status_code == 200, sent.text
        context = provider.last_context_content()
        assert "【文章来源】" not in context  # 勾选后真实剔除
        assert "【用户笔记】" not in context
        assert "【文章正文】" in context  # 正文不在可排除词表内
        assert "【文章标题】" in context  # 未勾选的保留


def test_new278_diff_endpoint_shows_removed_chars():
    """过滤差异面：未过滤 vs 过滤的分段对比 + 被剔除字符数。"""
    db, adapter, provider, conversation = _setup()
    with _client(db, adapter, conversation) as client:
        client.put(
            "/api/v1/ai/privacy-filters", json={"exclude": ["feedTitle"]}
        )
        diff = client.post(
            "/api/v1/ai/privacy-filters/diff",
            json={"entryRef": REF, "purpose": "conversation", "note": NOTE},
        )
        assert diff.status_code == 200, diff.text
        body = diff.json()
        assert body["exclude"] == ["feedTitle"]
        assert body["removedChars"] > 0
        unfiltered = {s["key"]: s for s in body["unfilteredSections"]}
        assert unfiltered["feedTitle"]["included"] is True
        filtered = {s["key"]: s for s in body["sections"]}
        assert filtered["feedTitle"]["included"] is False
        assert filtered["feedTitle"].get("excludedByFilter") is True
        assert "不会自动识别" in body["honestyNote"]


def test_new278_validation_and_clear():
    """未知字段 422；空清单 = 全部恢复。"""
    db, adapter, provider, conversation = _setup()
    with _client(db, adapter, conversation) as client:
        bad = client.put(
            "/api/v1/ai/privacy-filters",
            json={"exclude": ["body"]},  # 正文不可排除（词表外）
        )
        assert bad.status_code == 422
        assert bad.json()["error"]["type"] == "invalid_privacy_filter"

        client.put("/api/v1/ai/privacy-filters", json={"exclude": ["feedTitle"]})
        cleared = client.put("/api/v1/ai/privacy-filters", json={"exclude": []})
        assert cleared.status_code == 200
        assert cleared.json()["exclude"] == []
        preview = client.post(
            f"/api/v1/entries/{REF}/ai-input-preview",
            json={"purpose": "conversation"},
        ).json()
        sections = {s["key"]: s for s in preview["sections"]}
        assert sections["feedTitle"]["included"] is True


def test_new278_cross_user_filters_isolated(ab_env):  # noqa: F811
    """A 的勾选不影响 B 的预览（过滤状态在 per-user 库）。"""
    env = ab_env
    client = env["client"]
    app.state.freshrss_adapter = FakeAdapter({ITEM_ID: make_detail(text=BODY)})
    put = client.put(
        "/api/v1/ai/privacy-filters",
        json={"exclude": ["feedTitle", "cachedSummary", "userNote"]},
        headers=env["a"],
    )
    assert put.status_code == 200
    assert client.get("/api/v1/ai/privacy-filters", headers=env["b"]).json()["exclude"] == []
    preview_b = client.post(
        f"/api/v1/entries/{REF}/ai-input-preview",
        json={"purpose": "conversation"},
        headers=env["b"],
    )
    assert preview_b.status_code == 200
    sections_b = {s["key"]: s for s in preview_b.json()["sections"]}
    assert sections_b["feedTitle"]["included"] is True
