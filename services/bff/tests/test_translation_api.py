"""Tests for the translation API (0016).

Fake FreshRSS adapter + deterministic fake provider + temp database.
GET never spends money; POST generates exactly once per identity.
"""

import asyncio

from fastapi.testclient import TestClient

from lumirss.ai_provider import AiRateLimited
from lumirss.ai_settings import AiSettingsStore, AiSettingsUpdate
from lumirss.ai_translation import TranslationService
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

TITLE_MARKER = "<<<TRANSLATED_TITLE>>>"
BODY_MARKER = "<<<TRANSLATED_BODY>>>"


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
        return (
            f"{TITLE_MARKER}\n翻译后的标题\n{BODY_MARKER}\n翻译后的正文。"
        )


def run(coroutine):
    return asyncio.run(coroutine)


def wire(tmp_path, *, detail=None, adapter_error=None, provider=None):
    db = Database(tmp_path / "lumi.sqlite")
    adapter = FakeAdapter(detail, adapter_error)
    provider = provider if provider is not None else FakeProvider()
    service = TranslationService(
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


def test_get_translation_returns_not_generated_without_provider_call(tmp_path):
    db, _, provider, service = wire(tmp_path)
    with TestClient(app) as client:
        app.state.db = db
        app.state.translation_service = service
        response = client.get(f"/api/v1/entries/{VALID_REF}/translation")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "not_generated"
    assert body["translatedText"] is None
    assert provider.calls == 0


def test_get_translation_invalid_ref_rejected(tmp_path):
    db, _, provider, service = wire(tmp_path)
    with TestClient(app) as client:
        app.state.db = db
        app.state.translation_service = service
        response = client.get("/api/v1/entries/not-a-ref/translation")

    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_entry_reference"
    assert provider.calls == 0


def test_get_translation_missing_entry_maps_to_404(tmp_path):
    db, _, _, service = wire(tmp_path, adapter_error=EntryNotFound("nope"))
    with TestClient(app) as client:
        app.state.db = db
        app.state.translation_service = service
        response = client.get(f"/api/v1/entries/{VALID_REF}/translation")

    assert response.status_code == 404
    assert response.json()["error"]["type"] == "entry_not_found"


def test_post_translation_generates_and_second_post_is_cache_hit(tmp_path):
    db, _, provider, service = wire(tmp_path)
    configure(db)
    with TestClient(app) as client:
        app.state.db = db
        app.state.translation_service = service
        first = client.post(f"/api/v1/entries/{VALID_REF}/translation")
        second = client.post(f"/api/v1/entries/{VALID_REF}/translation")
        reread = client.get(f"/api/v1/entries/{VALID_REF}/translation")

    assert first.status_code == 200
    body = first.json()
    assert body["status"] == "success"
    assert body["translatedTitle"] == "翻译后的标题"
    assert body["translatedText"] == "翻译后的正文。"
    assert body["promptVersion"] == "translation-v1"
    assert body["targetLanguage"] == "zh-CN"
    assert body["cached"] is False
    assert second.json()["cached"] is True
    assert reread.json()["status"] == "success"
    assert provider.calls == 1


def test_post_translation_failure_maps_to_stable_error_and_retry_works(tmp_path):
    class FlakyProvider(FakeProvider):
        def __init__(self) -> None:
            super().__init__()
            self.error = AiRateLimited("rate limited")

        async def complete(self, *, messages) -> str:
            self.calls += 1
            if self.error is not None:
                raise self.error
            return f"{TITLE_MARKER}\n标题\n{BODY_MARKER}\n正文"

    db, _, provider, service = wire(tmp_path, provider=FlakyProvider())
    configure(db)
    with TestClient(app) as client:
        app.state.db = db
        app.state.translation_service = service
        failed = client.post(f"/api/v1/entries/{VALID_REF}/translation")
        state_after_failure = client.get(f"/api/v1/entries/{VALID_REF}/translation")
        provider.error = None
        recovered = client.post(f"/api/v1/entries/{VALID_REF}/translation")

    assert failed.status_code == 429
    assert failed.json()["error"]["type"] == "ai_rate_limited"
    assert state_after_failure.json()["status"] == "failed"
    assert state_after_failure.json()["failureType"] == "rate_limited"
    assert recovered.status_code == 200
    assert recovered.json()["status"] == "success"


def test_post_translation_without_configuration_returns_503(tmp_path):
    db, _, _, service = wire(tmp_path)
    with TestClient(app) as client:
        app.state.db = db
        app.state.translation_service = service
        response = client.post(f"/api/v1/entries/{VALID_REF}/translation")

    assert response.status_code == 503
    assert response.json()["error"]["type"] == "ai_not_configured"


def test_translation_response_never_contains_secrets(tmp_path):
    db, _, _, service = wire(tmp_path)
    configure(db)
    with TestClient(app) as client:
        app.state.db = db
        app.state.translation_service = service
        response = client.post(f"/api/v1/entries/{VALID_REF}/translation")

    text = response.text
    assert "sk-" not in text
    assert "apiKey" not in text
    assert "Authorization" not in text
    assert "Bearer" not in text
