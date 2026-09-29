"""NEW-271 AI 任务输入预览 — 预览与发送同构 / 删减后发送 / 诚实边界。

- 预览分段与真实发送共用 build_conversation_parts（所见即所发）；
- 预览零 provider 调用；非法 purpose 422；maxChars 截断如实上报；
- note 在预览计段，且随发送真实进入模型输入（不是只改预览）。
"""

from fastapi.testclient import TestClient

from lumirss.ai_conversation import ConversationService
from lumirss.ai_settings import AiSettingsStore
from lumirss.main import app
from lumirss.storage import Database
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
BODY = "这是一段稳定的正文内容，用于预览与发送的一致性验证。" * 40


def _wire(provider: FakeProvider | None = None):
    provider = provider or FakeProvider()
    db = Database(db_path())
    adapter = FakeAdapter({ITEM_ID: make_detail(text=BODY)})
    service = ConversationService(
        db=db,
        adapter=adapter,
        settings_store=AiSettingsStore(db),
        provider_factory=_fake_factory(provider),
    )
    return db, adapter, provider, service


def db_path() -> str:
    import tempfile

    return f"{tempfile.mkdtemp()}/lumi.sqlite"


def _fake_factory(provider: FakeProvider):
    async def factory(base_url: str, model: str):
        return provider

    return factory


def test_new271_preview_matches_actual_send(tmp_path):
    """问答预览的分段与字符数 == 实际发送的组装（含 note 计段）。"""
    db, adapter, provider, service = _wire()
    configure_ai(db)
    with TestClient(app) as test_client:
        app.state.db = db
        app.state.conversation_service = service
        note = "这是我在预览里决定附上的笔记。"
        preview = test_client.post(
            f"/api/v1/entries/{REF}/ai-input-preview",
            json={"purpose": "conversation", "note": note, "question": "这篇文章说什么？"},
        )
        assert preview.status_code == 200, preview.text
        payload = preview.json()
        sections = {item["key"]: item for item in payload["sections"]}
        assert sections["body"]["effectiveChars"] == len(BODY)
        assert sections["userNote"]["included"] is True
        assert sections["userNote"]["effectiveChars"] == len(note)
        assert sections["question"]["effectiveChars"] == len("这篇文章说什么？")
        assert payload["note"] == note
        assert provider.calls == 0  # 预览零费用

        # 预览宣称的正文范围 = 实际发送的正文范围
        sent = test_client.post(
            f"/api/v1/entries/{REF}/conversation/messages",
            json={"question": "这篇文章说什么？", "note": note},
        )
        assert sent.status_code == 200, sent.text
        user_content = provider.last_context_content()
        assert f"【用户笔记】\n{note}" in user_content
        assert f"【文章正文】\n{BODY}" in user_content


def test_new271_summary_preview_is_body_only_and_honest(tmp_path):
    """摘要预览只含正文段（摘要提示只发送正文），截断如实上报。"""
    db, adapter, provider, service = _wire()
    with TestClient(app) as test_client:
        app.state.db = db
        app.state.summary_service = _summary_service(db, adapter)
        preview = test_client.post(
            f"/api/v1/entries/{REF}/ai-input-preview",
            json={"purpose": "summary", "maxChars": 512},
        )
        assert preview.status_code == 200, preview.text
        payload = preview.json()
        assert [s["key"] for s in payload["sections"]] == ["body"]
        assert payload["sections"][0]["totalChars"] == len(BODY)
        assert payload["sections"][0]["effectiveChars"] == 512
        assert payload["truncated"] is True
        assert "只发送正文" in payload["honestyNote"]
        assert provider.calls == 0


def test_new271_preview_validations(tmp_path):
    """非法 purpose 422；非法条目引用 400；均零 provider 调用。"""
    db, adapter, provider, service = _wire()
    with TestClient(app) as test_client:
        app.state.db = db
        app.state.conversation_service = service
        bad = test_client.post(
            f"/api/v1/entries/{REF}/ai-input-preview",
            json={"purpose": "translation"},
        )
        assert bad.status_code == 422
        assert bad.json()["error"]["type"] == "invalid_preview_purpose"
        missing = test_client.post(
            "/api/v1/entries/not-a-ref/ai-input-preview",
            json={"purpose": "summary"},
        )
        assert missing.status_code == 400
        assert provider.calls == 0


def _summary_service(db, adapter):
    from lumirss.ai_settings import AiSettingsStore
    from lumirss.ai_summary import SummaryService

    return SummaryService(
        db=db,
        adapter=adapter,
        settings_store=AiSettingsStore(db),
        provider_factory=_fake_factory(FakeProvider()),
    )
