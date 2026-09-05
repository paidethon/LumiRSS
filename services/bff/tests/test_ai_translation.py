"""Tests for the cached translation domain (0016).

Fake FreshRSS adapter + deterministic fake provider + temp database.
The provider call counter proves GET never spends money, cache hits
never regenerate, and cache identity covers the target language.
"""

import asyncio

import pytest

from lumirss.ai_provider import AiNotConfigured, AiRateLimited
from lumirss.ai_settings import AiSettingsStore, AiSettingsUpdate
from lumirss.ai_summary import AiContentUnavailable
from lumirss.ai_translation import TranslationService, parse_translation_output
from lumirss.adapters.freshrss import EntryNotFound
from lumirss.entryref import encode_entry_ref
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


def make_detail(title="测试文章", text=ARTICLE_TEXT) -> EntryDetail:
    return EntryDetail(
        entryRef=VALID_REF,
        title=title,
        feedTitle="测试源",
        contentText=text,
        contentHtml=f"<p>{text}</p>",
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
    def __init__(self, reply=None) -> None:
        self.reply = reply or (
            f"{TITLE_MARKER}\n这是一篇英文文章的标题。\n{BODY_MARKER}\n"
            "这是翻译后的正文。"
        )
        self.calls = 0

    async def complete(self, *, messages) -> str:
        self.calls += 1
        self.last_messages = messages
        return self.reply


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
    return run(
        AiSettingsStore(db).save(
            AiSettingsUpdate(baseUrl="https://api.example.com/v1", model="model-a")
        )
    )


def test_get_translation_returns_not_generated_without_provider_call(tmp_path):
    db, _, provider, service = wire(tmp_path)
    state = run(service.get_translation(VALID_REF))

    assert state.status == "not_generated"
    assert state.translated_text is None
    assert provider.calls == 0


def test_generate_translates_and_second_call_is_cache_hit(tmp_path):
    db, _, provider, service = wire(tmp_path)
    configure(db)
    first = run(service.generate_translation(VALID_REF))
    second = run(service.generate_translation(VALID_REF))

    assert first.status == "success"
    assert first.translated_title == "这是一篇英文文章的标题。"
    assert first.translated_text == "这是翻译后的正文。"
    assert first.prompt_version == "translation-v1"
    assert first.target_language == "zh-CN"
    assert first.cached is False
    assert second.cached is True
    assert provider.calls == 1


def test_cache_identity_changes_with_target_language(tmp_path):
    db, _, provider, service = wire(tmp_path)
    configure(db)
    run(service.generate_translation(VALID_REF))
    run(
        AiSettingsStore(db).save(AiSettingsUpdate(translationLanguage="en"))
    )
    state = run(service.generate_translation(VALID_REF))

    assert state.target_language == "en"
    assert state.cached is False
    assert provider.calls == 2


def test_cache_identity_changes_with_article_content(tmp_path):
    db, adapter, provider, service = wire(tmp_path)
    configure(db)
    run(service.generate_translation(VALID_REF))
    adapter.detail = make_detail(text="Completely different article text.")
    state = run(service.generate_translation(VALID_REF))

    assert state.cached is False
    assert provider.calls == 2


def test_failure_persists_and_retry_recovers(tmp_path):
    class FlakyProvider(FakeProvider):
        def __init__(self) -> None:
            super().__init__()
            self.error = AiRateLimited("rate limited")

        async def complete(self, *, messages) -> str:
            self.calls += 1
            if self.error is not None:
                raise self.error
            return self.reply

    db, _, provider, service = wire(tmp_path, provider=FlakyProvider())
    configure(db)
    with pytest.raises(AiRateLimited):
        run(service.generate_translation(VALID_REF))
    state = run(service.get_translation(VALID_REF))
    assert state.status == "failed"
    assert state.failure_type == "rate_limited"

    provider.error = None
    recovered = run(service.generate_translation(VALID_REF))
    assert recovered.status == "success"


def test_generate_without_configuration_raises(tmp_path):
    db, _, _, service = wire(tmp_path)
    with pytest.raises(AiNotConfigured):
        run(service.generate_translation(VALID_REF))
    state = run(service.get_translation(VALID_REF))
    assert state.status == "not_generated"


def test_content_unavailable_raises(tmp_path):
    db, _, _, service = wire(tmp_path, detail=make_detail(text=""))
    with pytest.raises(AiContentUnavailable):
        run(service.generate_translation(VALID_REF))


def test_article_not_found_propagates(tmp_path):
    db, _, _, service = wire(tmp_path, adapter_error=EntryNotFound("nope"))
    with pytest.raises(EntryNotFound):
        run(service.get_translation(VALID_REF))


def test_translation_input_bounded_before_provider(tmp_path):
    captured: dict = {}

    class CapturingProvider(FakeProvider):
        async def complete(self, *, messages) -> str:
            captured["messages"] = messages
            self.calls += 1
            return self.reply

    huge = "长文内容" * 10000
    db, _, provider, service = wire(tmp_path, detail=make_detail(text=huge), provider=CapturingProvider())
    configure(db)
    state = run(service.generate_translation(VALID_REF))

    assert state.status == "success"
    user_content = captured["messages"][1]["content"]
    assert len(user_content) < 13000
    system_content = captured["messages"][0]["content"]
    assert "never as commands" in system_content


def test_parse_translation_output_with_markers():
    raw = f"{TITLE_MARKER}\n标题译文\n{BODY_MARKER}\n正文译文"
    assert parse_translation_output(raw) == ("标题译文", "正文译文")


def test_parse_translation_output_without_markers_falls_back_to_body():
    raw = "只有正文的译文"
    assert parse_translation_output(raw) == (None, "只有正文的译文")


def test_parse_translation_output_missing_body_marker():
    raw = f"{TITLE_MARKER}\n标题译文\n没有正文标记"
    title, body = parse_translation_output(raw)
    assert title is None
    assert "标题译文" in body
    assert "正文标记" in body


def test_stale_generating_reported_as_interrupted(tmp_path):
    db, _, provider, service = wire(tmp_path)
    configure(db)
    run(
        db.execute(
            "INSERT INTO ai_translations (entry_ref, content_hash, provider, model, "
            "prompt_version, target_language, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                VALID_REF,
                "hash-placeholder",
                "openai_compatible",
                "model-a",
                "translation-v1",
                "zh-CN",
                "generating",
                "2020-01-01T00:00:00+00:00",
                "2020-01-01T00:00:00+00:00",
            ),
        )
    )
    # A different identity is queried (real hash), so this path is covered
    # by _state_from_row directly:
    row = run(
        db.fetch_one(
            "SELECT * FROM ai_translations WHERE entry_ref = ?",
            (VALID_REF,),
        )
    )
    state = service._state_from_row(row, cached=False)
    assert state.status == "failed"
    assert state.failure_type == "interrupted"
