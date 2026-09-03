"""Tests for the cached article summary domain (0015 Gate 4).

Deterministic fake provider + fake FreshRSS adapter + temp database —
zero network, zero paid calls, and the provider call counter proves the
cache actually avoids regeneration.
"""

import asyncio

import pytest

from lumirss.ai_provider import AiNotConfigured, AiRateLimited
from lumirss.ai_settings import AiSettingsStore
from lumirss.ai_summary import (
    AiContentUnavailable,
    SummaryService,
    content_hash,
    normalize_content,
)
from lumirss.entryref import encode_entry_ref
from lumirss.models import EntryDetail
from lumirss.storage import Database

ITEM_ID = "tag:google.com,2005:reader/item/0000000000000001"
VALID_REF = encode_entry_ref(ITEM_ID)

ARTICLE_TEXT = "这是一篇关于人工智能的长文章。" + "内容" * 200


def make_detail(text: str = ARTICLE_TEXT) -> EntryDetail:
    return EntryDetail(
        entryRef=VALID_REF,
        title="测试文章",
        feedTitle="测试源",
        contentText=text,
        contentHtml=f"<p>{text}</p>",
        read=False,
        starred=False,
    )


class FakeAdapter:
    def __init__(self, detail=None) -> None:
        self.detail = detail if detail is not None else make_detail()

    async def get_entry(self, item_id: str) -> EntryDetail:
        return self.detail


class FakeProvider:
    def __init__(self, summary: str = "确定性的测试摘要。", error=None) -> None:
        self.summary = summary
        self.error = error
        self.calls = 0

    async def summarize(self, *, text: str, language: str) -> str:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.summary


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "lumi.sqlite")


def run(coroutine):
    return asyncio.run(coroutine)


def make_service(db, provider=None, detail=None):
    provider = provider if provider is not None else FakeProvider()
    return (
        SummaryService(
            db=db,
            adapter=FakeAdapter(detail),
            settings_store=AiSettingsStore(db),
            provider_factory=lambda base_url, model: provider,
        ),
        provider,
    )


async def configure_settings(db):
    store = AiSettingsStore(db)
    from lumirss.ai_settings import AiSettingsUpdate

    await store.save(
        AiSettingsUpdate(
            baseUrl="https://api.example.com/v1", model="model-a"
        )
    )


# ---- normalization / hashing ----


def test_normalize_collapses_whitespace_and_is_deterministic():
    raw = "第一段\n\n\n第二段\t结尾  "
    first = normalize_content(raw)
    second = normalize_content(raw)

    assert first == second
    assert "第一段 第二段 结尾" == first


def test_normalize_bounds_input_length():
    huge = "词" * (15000)
    normalized = normalize_content(huge)

    assert len(normalized) == 12000


def test_content_hash_changes_with_content():
    assert content_hash("a") != content_hash("b")


# ---- GET semantics ----


def test_get_without_row_is_not_generated_and_makes_no_provider_call(db):
    service, provider = make_service(db)

    state = run(service.get_summary(VALID_REF))

    assert state.status == "not_generated"
    assert state.summary is None
    assert provider.calls == 0


def test_get_never_calls_provider_even_without_configuration(db):
    service, provider = make_service(db)

    state = run(service.get_summary(VALID_REF))

    assert state.status == "not_generated"
    assert provider.calls == 0


# ---- generation + cache ----


def test_generate_calls_provider_once_and_persists(db):
    service, provider = make_service(db)
    run(configure_settings(db))

    first = run(service.generate_summary(VALID_REF))
    second = run(service.generate_summary(VALID_REF))
    reread = run(service.get_summary(VALID_REF))

    assert first.status == "success"
    assert first.summary == "确定性的测试摘要。"
    assert first.cached is False
    assert second.cached is True
    assert reread.cached is True
    assert provider.calls == 1


def test_changed_content_produces_new_cache_identity(db):
    service, provider = make_service(db)
    run(configure_settings(db))

    run(service.generate_summary(VALID_REF))
    service._adapter.detail = make_detail("完全不同的一篇文章内容。")

    state = run(service.get_summary(VALID_REF))

    assert state.status == "not_generated"
    assert provider.calls == 1


def test_model_change_produces_new_cache_identity(db):
    service, provider = make_service(db)
    store = AiSettingsStore(db)
    from lumirss.ai_settings import AiSettingsUpdate

    run(store.save(AiSettingsUpdate(baseUrl="https://api.example.com/v1", model="model-a")))
    run(service.generate_summary(VALID_REF))
    run(store.save(AiSettingsUpdate(model="model-b")))

    state = run(service.get_summary(VALID_REF))
    assert state.status == "not_generated"
    run(service.generate_summary(VALID_REF))

    assert provider.calls == 2


def test_language_change_produces_new_cache_identity(db):
    service, provider = make_service(db)
    store = AiSettingsStore(db)
    from lumirss.ai_settings import AiSettingsUpdate

    run(store.save(AiSettingsUpdate(baseUrl="https://api.example.com/v1", model="model-a")))
    run(service.generate_summary(VALID_REF))
    run(store.save(AiSettingsUpdate(summaryLanguage="en")))

    state = run(service.get_summary(VALID_REF))
    assert state.status == "not_generated"


# ---- failure states ----


def test_provider_failure_persists_failed_state_with_type(db):
    provider = FakeProvider(error=AiRateLimited("rate limited"))
    service, _ = make_service(db, provider)
    run(configure_settings(db))

    with pytest.raises(AiRateLimited):
        run(service.generate_summary(VALID_REF))

    state = run(service.get_summary(VALID_REF))
    assert state.status == "failed"
    assert state.failure_type == "rate_limited"
    assert provider.calls == 1


def test_retry_after_failure_calls_provider_again_and_recovers(db):
    provider = FakeProvider(error=AiRateLimited("rate limited"))
    service, _ = make_service(db, provider)
    run(configure_settings(db))

    with pytest.raises(AiRateLimited):
        run(service.generate_summary(VALID_REF))
    provider.error = None

    state = run(service.generate_summary(VALID_REF))

    assert state.status == "success"
    assert provider.calls == 2


def test_not_configured_raises_without_persisting_failed_row(db):
    service, provider = make_service(db)

    with pytest.raises(AiNotConfigured):
        run(service.generate_summary(VALID_REF))
    state = run(service.get_summary(VALID_REF))

    assert state.status == "not_generated"
    assert provider.calls == 0


def test_empty_content_raises_content_unavailable(db):
    service, provider = make_service(db, detail=make_detail("   \n  "))
    run(configure_settings(db))

    with pytest.raises(AiContentUnavailable):
        run(service.generate_summary(VALID_REF))
    with pytest.raises(AiContentUnavailable):
        run(service.get_summary(VALID_REF))

    assert provider.calls == 0


def test_stale_generating_row_reports_interrupted(db):
    service, provider = make_service(db)
    run(configure_settings(db))
    run(service._db.migrate())
    # Simulate a row left behind by a crashed process.
    run(
        service._db.execute(
            "INSERT INTO ai_summaries (entry_ref, content_hash, provider, model, "
            "prompt_version, language, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                VALID_REF,
                content_hash(normalize_content(ARTICLE_TEXT)),
                "openai_compatible",
                "model-a",
                "summary-v1",
                "zh-CN",
                "generating",
                "2020-01-01T00:00:00+00:00",
                "2020-01-01T00:00:00+00:00",
            ),
        )
    )

    state = run(service.get_summary(VALID_REF))

    assert state.status == "failed"
    assert state.failure_type == "interrupted"
    assert provider.calls == 0


def test_concurrent_generation_makes_exactly_one_provider_call(db):
    service, provider = make_service(db)
    run(configure_settings(db))

    async def generate_both():
        await asyncio.gather(
            service.generate_summary(VALID_REF),
            service.generate_summary(VALID_REF),
        )

    run(generate_both())

    assert provider.calls == 1
