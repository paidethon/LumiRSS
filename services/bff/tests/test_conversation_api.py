"""Tests for the article conversation API (0016).

GET never spends money; POST asks one bounded question; failures map to
stable errors and persist nothing.
"""

import asyncio

from fastapi.testclient import TestClient

from lumirss.ai_provider import AiRateLimited
from lumirss.ai_settings import AiSettingsStore, AiSettingsUpdate
from lumirss.ai_conversation import ConversationService
from lumirss.adapters.freshrss import EntryNotFound
from lumirss.entryref import encode_entry_ref
from lumirss.main import app
from lumirss.models import EntryDetail
from lumirss.storage import Database


def _async_provider(provider):
    """The BFF provider factory is async (purpose→profile resolution)."""

    async def factory(base_url: str, model: str):
        return provider

    return factory

VALID_REF = encode_entry_ref("tag:google.com,2005:reader/item/0000000000000001")
ARTICLE_TEXT = "This is an English article." + "Body content " * 100


def make_detail() -> EntryDetail:
    return EntryDetail(
        entryRef=VALID_REF,
        title="测试文章",
        feedTitle="测试源",
        contentText=ARTICLE_TEXT,
        contentHtml=f"<p>{ARTICLE_TEXT}</p>",
        read=False,
        starred=False,
    )


class FakeAdapter:
    def __init__(self, detail=None, error=None) -> None:
        self.detail = detail if detail is not None else make_detail()
        self.error = error

    async def get_entry(self, item_id: str) -> EntryDetail:
        if self.error is not None:
            raise self.error
        return self.detail


class FakeProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, *, messages) -> str:
        self.calls += 1
        return "确定性的回答。"


def run(coroutine):
    return asyncio.run(coroutine)


def wire(tmp_path, *, detail=None, adapter_error=None, provider=None):
    db = Database(tmp_path / "lumi.sqlite")
    adapter = FakeAdapter(detail, adapter_error)
    provider = provider if provider is not None else FakeProvider()
    service = ConversationService(
        db=db,
        adapter=adapter,
        settings_store=AiSettingsStore(db),
        provider_factory=_async_provider(provider),
    )
    return db, adapter, provider, service


def configure(db):
    run(
        AiSettingsStore(db).save(
            AiSettingsUpdate(baseUrl="https://api.example.com/v1", model="model-a")
        )
    )


def test_get_conversation_returns_empty_without_provider_call(tmp_path):
    db, _, provider, service = wire(tmp_path)
    with TestClient(app) as client:
        app.state.db = db
        app.state.conversation_service = service
        response = client.get(f"/api/v1/entries/{VALID_REF}/conversation")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "empty"
    assert body["messages"] == []
    assert provider.calls == 0


def test_get_conversation_invalid_ref_rejected(tmp_path):
    db, _, provider, service = wire(tmp_path)
    with TestClient(app) as client:
        app.state.db = db
        app.state.conversation_service = service
        response = client.get("/api/v1/entries/not-a-ref/conversation")

    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_entry_reference"
    assert provider.calls == 0


def test_get_conversation_missing_entry_maps_to_404(tmp_path):
    db, _, _, service = wire(tmp_path, adapter_error=EntryNotFound("nope"))
    with TestClient(app) as client:
        app.state.db = db
        app.state.conversation_service = service
        response = client.get(f"/api/v1/entries/{VALID_REF}/conversation")

    assert response.status_code == 404
    assert response.json()["error"]["type"] == "entry_not_found"


def test_post_message_persists_and_follow_up_works(tmp_path):
    db, _, provider, service = wire(tmp_path)
    configure(db)
    with TestClient(app) as client:
        app.state.db = db
        app.state.conversation_service = service
        first = client.post(
            f"/api/v1/entries/{VALID_REF}/conversation/messages",
            json={"question": "这篇文章主要在说什么？"},
        )
        second = client.post(
            f"/api/v1/entries/{VALID_REF}/conversation/messages",
            json={"question": "作者为什么得出这个结论？"},
        )
        reread = client.get(f"/api/v1/entries/{VALID_REF}/conversation")

    assert first.status_code == 200
    body = first.json()
    assert body["status"] == "active"
    assert [m["role"] for m in body["messages"]] == ["user", "assistant"]
    assert body["messages"][0]["content"] == "这篇文章主要在说什么？"
    assert body["messages"][1]["content"] == "确定性的回答。"
    assert second.json()["messages"][-1]["content"] == "确定性的回答。"
    assert len(second.json()["messages"]) == 4
    assert len(reread.json()["messages"]) == 4
    assert provider.calls == 2


def test_post_message_failure_maps_to_stable_error_and_persists_nothing(tmp_path):
    class FlakyProvider(FakeProvider):
        def __init__(self) -> None:
            super().__init__()
            self.error = AiRateLimited("rate limited")

        async def complete(self, *, messages) -> str:
            self.calls += 1
            if self.error is not None:
                raise self.error
            return "确定性的回答。"

    db, _, provider, service = wire(tmp_path, provider=FlakyProvider())
    configure(db)
    with TestClient(app) as client:
        app.state.db = db
        app.state.conversation_service = service
        failed = client.post(
            f"/api/v1/entries/{VALID_REF}/conversation/messages",
            json={"question": "会失败的问题"},
        )
        state_after_failure = client.get(f"/api/v1/entries/{VALID_REF}/conversation")
        provider.error = None
        recovered = client.post(
            f"/api/v1/entries/{VALID_REF}/conversation/messages",
            json={"question": "会失败的问题"},
        )

    assert failed.status_code == 429
    assert failed.json()["error"]["type"] == "ai_rate_limited"
    assert state_after_failure.json()["status"] == "empty"
    assert recovered.status_code == 200
    assert len(recovered.json()["messages"]) == 2


def test_post_message_blank_question_rejected(tmp_path):
    db, _, provider, service = wire(tmp_path)
    configure(db)
    with TestClient(app) as client:
        app.state.db = db
        app.state.conversation_service = service
        response = client.post(
            f"/api/v1/entries/{VALID_REF}/conversation/messages",
            json={"question": "   "},
        )

    assert response.status_code == 422
    assert provider.calls == 0


def test_post_message_too_long_rejected(tmp_path):
    db, _, provider, service = wire(tmp_path)
    configure(db)
    with TestClient(app) as client:
        app.state.db = db
        app.state.conversation_service = service
        response = client.post(
            f"/api/v1/entries/{VALID_REF}/conversation/messages",
            json={"question": "长" * 5000},
        )

    assert response.status_code == 422
    assert provider.calls == 0


def test_post_message_without_configuration_returns_503(tmp_path):
    db, _, _, service = wire(tmp_path)
    with TestClient(app) as client:
        app.state.db = db
        app.state.conversation_service = service
        response = client.post(
            f"/api/v1/entries/{VALID_REF}/conversation/messages",
            json={"question": "问题"},
        )

    assert response.status_code == 503
    assert response.json()["error"]["type"] == "ai_not_configured"


def test_conversation_response_never_contains_secrets(tmp_path):
    db, _, _, service = wire(tmp_path)
    configure(db)
    with TestClient(app) as client:
        app.state.db = db
        app.state.conversation_service = service
        response = client.post(
            f"/api/v1/entries/{VALID_REF}/conversation/messages",
            json={"question": "问题"},
        )

    text = response.text
    assert "sk-" not in text
    assert "apiKey" not in text
    assert "Authorization" not in text
    assert "Bearer" not in text
