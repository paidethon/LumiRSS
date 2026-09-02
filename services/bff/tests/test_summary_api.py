"""Tests for the summary API (0015 Gate 5).

Fake FreshRSS adapter + deterministic fake provider + temp database.
The provider call counter proves GET never spends money and a cache hit
never regenerates.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from lumirss.ai_provider import AiRateLimited
from lumirss.ai_settings import AiSettingsStore, AiSettingsUpdate
from lumirss.ai_summary import SummaryService
from lumirss.adapters.freshrss import EntryNotFound
from lumirss.entryref import encode_entry_ref
from lumirss.main import app
from lumirss.models import EntryDetail
from lumirss.storage import Database

VALID_REF = encode_entry_ref("tag:google.com,2005:reader/item/0000000000000001")
ARTICLE_TEXT = "这是一篇文章。" + "正文内容" * 100


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
    def __init__(self, summary="确定性的测试摘要。") -> None:
        self.summary = summary
        self.calls = 0

    async def summarize(self, *, text: str, language: str) -> str:
        self.calls += 1
        return self.summary


def run(coroutine):
    return asyncio.run(coroutine)


def wire(tmp_path, *, detail=None, adapter_error=None, provider=None):
    """Wire app.state with a temp DB, fake adapter and optional fake
    provider; returns (provider,)."""
    db = Database(tmp_path / "lumi.sqlite")
    adapter = FakeAdapter(detail, adapter_error)
    provider = provider if provider is not None else FakeProvider()
    service = SummaryService(
        db=db,
        adapter=adapter,
        settings_store=AiSettingsStore(db),
        provider_factory=lambda base_url, model: provider,
    )
    return db, adapter, provider, service


def test_get_summary_returns_not_generated_without_provider_call(tmp_path):
    db, _, provider, service = wire(tmp_path)
    with TestClient(app) as client:
        app.state.db = db
        app.state.summary_service = service
        response = client.get(f"/api/v1/entries/{VALID_REF}/summary")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "not_generated"
    assert body["summary"] is None
    assert provider.calls == 0


def test_get_summary_invalid_ref_rejected_before_any_service_call(tmp_path):
    db, _, provider, service = wire(tmp_path)
    with TestClient(app) as client:
        app.state.db = db
        app.state.summary_service = service
        response = client.get("/api/v1/entries/not-a-ref/summary")

    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_entry_reference"
    assert provider.calls == 0


def test_get_summary_missing_entry_maps_to_404(tmp_path):
    db, _, _, service = wire(tmp_path, adapter_error=EntryNotFound("nope"))
    with TestClient(app) as client:
        app.state.db = db
        app.state.summary_service = service
        response = client.get(f"/api/v1/entries/{VALID_REF}/summary")

    assert response.status_code == 404
    assert response.json()["error"]["type"] == "entry_not_found"


def test_post_summary_generates_and_second_post_is_cache_hit(tmp_path):
    db, _, provider, service = wire(tmp_path)
    run(
        AiSettingsStore(db).save(
            AiSettingsUpdate(baseUrl="https://api.example.com/v1", model="model-a")
        )
    )
    with TestClient(app) as client:
        app.state.db = db
        app.state.summary_service = service
        first = client.post(f"/api/v1/entries/{VALID_REF}/summary")
        second = client.post(f"/api/v1/entries/{VALID_REF}/summary")
        reread = client.get(f"/api/v1/entries/{VALID_REF}/summary")

    assert first.status_code == 200
    body = first.json()
    assert body["status"] == "success"
    assert body["summary"] == "确定性的测试摘要。"
    assert body["model"] == "model-a"
    assert body["promptVersion"] == "summary-v1"
    assert body["language"] == "zh-CN"
    assert body["cached"] is False
    assert second.json()["cached"] is True
    assert reread.json()["status"] == "success"
    assert provider.calls == 1


def test_post_summary_failure_maps_to_stable_error_and_retry_works(tmp_path):
    class FlakyProvider(FakeProvider):
        def __init__(self) -> None:
            super().__init__()
            self.error = AiRateLimited("rate limited")

        async def summarize(self, *, text: str, language: str) -> str:
            self.calls += 1
            if self.error is not None:
                raise self.error
            return self.summary

    db, _, provider, service = wire(tmp_path, provider=FlakyProvider())
    run(
        AiSettingsStore(db).save(
            AiSettingsUpdate(baseUrl="https://api.example.com/v1", model="model-a")
        )
    )
    with TestClient(app) as client:
        app.state.db = db
        app.state.summary_service = service
        failed = client.post(f"/api/v1/entries/{VALID_REF}/summary")
        state_after_failure = client.get(f"/api/v1/entries/{VALID_REF}/summary")
        provider.error = None
        recovered = client.post(f"/api/v1/entries/{VALID_REF}/summary")

    assert failed.status_code == 429
    assert failed.json()["error"]["type"] == "ai_rate_limited"
    assert state_after_failure.json()["status"] == "failed"
    assert state_after_failure.json()["failureType"] == "rate_limited"
    assert recovered.status_code == 200
    assert recovered.json()["status"] == "success"


def test_post_summary_without_configuration_returns_503(tmp_path):
    db, _, _, service = wire(tmp_path)
    with TestClient(app) as client:
        app.state.db = db
        app.state.summary_service = service
        response = client.post(f"/api/v1/entries/{VALID_REF}/summary")

    assert response.status_code == 503
    assert response.json()["error"]["type"] == "ai_not_configured"


def test_summary_response_never_contains_secrets(tmp_path):
    db, _, provider, service = wire(tmp_path)
    run(
        AiSettingsStore(db).save(
            AiSettingsUpdate(baseUrl="https://api.example.com/v1", model="model-a")
        )
    )
    with TestClient(app) as client:
        app.state.db = db
        app.state.summary_service = service
        response = client.post(f"/api/v1/entries/{VALID_REF}/summary")

    text = response.text
    assert "sk-" not in text
    assert "apiKey" not in text
    assert "Authorization" not in text
    assert "Bearer" not in text
