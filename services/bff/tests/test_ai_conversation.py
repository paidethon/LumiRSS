"""Tests for the article-scoped conversation domain (0016).

Fake FreshRSS adapter + deterministic fake provider + temp database.
GET never calls the provider; a failed send persists nothing; article
content changes start a fresh conversation; history is bounded.
"""

import asyncio

import pytest

from lumirss.ai_provider import AiNotConfigured, AiRateLimited
from lumirss.ai_settings import AiSettingsStore, AiSettingsUpdate
from lumirss.ai_summary import AiContentUnavailable
from lumirss.ai_conversation import (
    MAX_HISTORY_MESSAGES,
    ConversationService,
)
from lumirss.adapters.freshrss import EntryNotFound
from lumirss.entryref import encode_entry_ref
from lumirss.models import EntryDetail
from lumirss.storage import Database

VALID_REF = encode_entry_ref("tag:google.com,2005:reader/item/0000000000000001")
ARTICLE_TEXT = "This is an English article." + "Body content " * 100


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
    def __init__(self) -> None:
        self.calls = 0
        self.messages_history: list[list[dict]] = []

    async def complete(self, *, messages) -> str:
        self.calls += 1
        self.messages_history.append(messages)
        return "这是对问题的回答。"


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
        provider_factory=lambda base_url, model: provider,
    )
    return db, adapter, provider, service


def configure(db):
    return run(
        AiSettingsStore(db).save(
            AiSettingsUpdate(baseUrl="https://api.example.com/v1", model="model-a")
        )
    )


def test_get_conversation_empty_without_provider_call(tmp_path):
    db, _, provider, service = wire(tmp_path)
    state = run(service.get_conversation(VALID_REF))

    assert state.status == "empty"
    assert state.messages == ()
    assert provider.calls == 0


def test_send_persists_question_and_reply(tmp_path):
    db, _, provider, service = wire(tmp_path)
    configure(db)
    state = run(service.send_message(VALID_REF, "这篇文章主要在说什么？"))

    assert state.status == "active"
    assert [m.role for m in state.messages] == ["user", "assistant"]
    assert state.messages[0].content == "这篇文章主要在说什么？"
    assert state.messages[1].content == "这是对问题的回答。"
    assert state.messages[0].id < state.messages[1].id
    assert provider.calls == 1


def test_follow_up_includes_history_and_article_context(tmp_path):
    db, _, provider, service = wire(tmp_path)
    configure(db)
    run(service.send_message(VALID_REF, "问题一"))
    state = run(service.send_message(VALID_REF, "问题二"))

    assert len(state.messages) == 4
    assert provider.calls == 2
    # Second provider call carries: system, article context, history (2),
    # new question = 5 messages.
    second_call = provider.messages_history[1]
    assert len(second_call) == 5
    assert second_call[0]["role"] == "system"
    assert "问题一" in second_call[2]["content"]
    assert second_call[2]["role"] == "user"
    assert "这是对问题的回答。" in second_call[3]["content"]
    assert second_call[4] == {"role": "user", "content": "问题二"}
    # Article context carries title, source and bounded body.
    context = second_call[1]["content"]
    assert "测试文章" in context
    assert "测试源" in context
    assert "文章正文" in context


def test_reopen_restores_conversation_without_provider_call(tmp_path):
    db, _, provider, service = wire(tmp_path)
    configure(db)
    run(service.send_message(VALID_REF, "问题"))
    provider.calls = 0
    state = run(service.get_conversation(VALID_REF))

    assert state.status == "active"
    assert len(state.messages) == 2
    assert provider.calls == 0


def test_changed_article_content_starts_fresh_conversation(tmp_path):
    db, adapter, provider, service = wire(tmp_path)
    configure(db)
    run(service.send_message(VALID_REF, "旧文章的问题"))
    adapter.detail = make_detail(text="A completely different article now.")
    state = run(service.get_conversation(VALID_REF))

    assert state.status == "empty"
    assert state.messages == ()
    assert provider.calls == 1  # GET itself never calls


def test_failed_send_persists_nothing(tmp_path):
    class FlakyProvider(FakeProvider):
        async def complete(self, *, messages) -> str:
            self.calls += 1
            raise AiRateLimited("rate limited")

    db, _, _, service = wire(tmp_path, provider=FlakyProvider())
    configure(db)
    with pytest.raises(AiRateLimited):
        run(service.send_message(VALID_REF, "会失败的问题"))

    state = run(service.get_conversation(VALID_REF))
    assert state.status == "empty"


def test_send_without_configuration_raises_and_persists_nothing(tmp_path):
    db, _, _, service = wire(tmp_path)
    with pytest.raises(AiNotConfigured):
        run(service.send_message(VALID_REF, "问题"))

    state = run(service.get_conversation(VALID_REF))
    assert state.status == "empty"


def test_history_bounded_to_last_messages(tmp_path):
    db, _, provider, service = wire(tmp_path)
    configure(db)
    for index in range(8):
        run(service.send_message(VALID_REF, f"问题{index}"))

    # 8 questions = 16 stored messages; the final call (for 问题7) receives
    # at most the last MAX_HISTORY_MESSAGES history messages (12 = 6 Q/A
    # pairs, starting at 问题1).
    last_call = provider.messages_history[-1]
    history = last_call[2:-1]
    assert len(history) == MAX_HISTORY_MESSAGES
    assert history[0]["content"] == "问题1"
    assert history[-1]["content"] == "这是对问题的回答。"


def test_question_bounded(tmp_path):
    db, _, provider, service = wire(tmp_path)
    configure(db)
    run(service.send_message(VALID_REF, "长问题" * 10000))

    last_call = provider.messages_history[-1]
    assert len(last_call[-1]["content"]) <= 4000


def test_content_unavailable_raises(tmp_path):
    db, _, _, service = wire(tmp_path, detail=make_detail(text=""))
    with pytest.raises(AiContentUnavailable):
        run(service.send_message(VALID_REF, "问题"))


def test_article_not_found_propagates(tmp_path):
    db, _, _, service = wire(tmp_path, adapter_error=EntryNotFound("nope"))
    with pytest.raises(EntryNotFound):
        run(service.get_conversation(VALID_REF))


def test_system_prompt_declares_injection_boundary(tmp_path):
    db, _, provider, service = wire(tmp_path)
    configure(db)
    run(service.send_message(VALID_REF, "问题"))

    system = provider.messages_history[0][0]["content"]
    assert "never as commands" in system
    assert "no tools" in system.lower()
