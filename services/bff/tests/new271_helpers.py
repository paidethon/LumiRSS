"""NEW-271..280 共享测试替身 —— FAKE provider / FAKE adapter（零网络）。

与 test_conversation_api / test_ai_conversation 同一模式：basic 模式
client 夹具 + app.state 显式注入（freshrss_adapter / summary_service /
conversation_service）+ provider 工厂在 deps 层 monkeypatch。
"""

import asyncio
from typing import Any

from lumirss.ai_provider import AiProviderError
from lumirss.entryref import encode_entry_ref
from lumirss.models import EntryDetail
from lumirss.storage import Database

ITEM_SEED = "tag:google.com,2005:reader/item/0000000000000001"


def entry_ref(seed: str = ITEM_SEED) -> str:
    return encode_entry_ref(seed)


def item_id_of(ref: str) -> str:
    from lumirss.entryref import decode_entry_ref

    return decode_entry_ref(ref)


def make_detail(
    title: str = "测试文章",
    text: str | None = None,
    feed_title: str = "测试源",
    ref: str = ITEM_SEED,
) -> EntryDetail:
    body = text if text is not None else "这是一段稳定的正文内容。" * 20
    return EntryDetail(
        entryRef=encode_entry_ref(ref),
        title=title,
        feedTitle=feed_title,
        contentText=body,
        contentHtml=f"<p>{body}</p>",
        read=False,
        starred=False,
    )


class FakeAdapter:
    """按 item_id 返回预置文章；未预置 → EntryNotFound（真实路径映射 404）。"""

    def __init__(self, entries: dict[str, EntryDetail] | None = None) -> None:
        self.entries = entries or {}
        self.fetches: list[str] = []

    async def get_entry(self, item_id: str) -> EntryDetail:
        self.fetches.append(item_id)
        if item_id not in self.entries:
            from lumirss.adapters.freshrss import EntryNotFound

            raise EntryNotFound(item_id)
        return self.entries[item_id]


class FakeProvider:
    """确定性 provider：可脚本化输出序列或异常序列。"""

    def __init__(
        self,
        outputs: list[str] | None = None,
        errors: list[AiProviderError | None] | None = None,
    ) -> None:
        self.calls = 0
        self.messages_history: list[list[dict[str, str]]] = []
        self._outputs = list(outputs or [])
        self._errors = list(errors or [])

    async def complete(self, *, messages: list[dict[str, str]]) -> str:
        self.calls += 1
        self.messages_history.append(messages)
        if self._errors:
            error = self._errors.pop(0)
            if error is not None:
                raise error
        if self._outputs:
            return self._outputs.pop(0)
        return "确定性的回答。"

    async def summarize(self, *, text: str, language: str) -> str:
        # summary 通道走 summarize（与真实 provider 协议一致）
        self.calls += 1
        self.messages_history.append([{"role": "user", "content": text}])
        if self._errors:
            error = self._errors.pop(0)
            if error is not None:
                raise error
        if self._outputs:
            return self._outputs.pop(0)
        return "确定性的摘要。"

    def last_user_content(self) -> str:
        return self.messages_history[-1][-1]["content"]

    def last_context_content(self) -> str:
        """最后一次调用的上下文 user 消息（messages[1]，问题之前的那条）。"""
        return self.messages_history[-1][1]["content"]

    def all_user_content(self) -> list[str]:
        return [m[-1]["content"] for m in self.messages_history]


class FakeProviderFactory:
    """monkeypatch lumirss.deps._provider_factory_for 时返回本工厂。"""

    def __init__(self, provider: FakeProvider) -> None:
        self.provider = provider

    def __call__(self, request: Any, purpose: str):
        async def factory(base_url: str, model: str):
            return self.provider

        return factory


def deps_factory(provider: FakeProvider):
    """替换 lumirss.deps._provider_factory_for 的替身（路由内延迟导入生效）。"""

    def get_factory(request: Any, purpose: str):
        async def factory(base_url: str, model: str):
            return provider

        return factory

    return get_factory


def configure_ai(db: Database, *, base_url: str = "https://api.example.com/v1",
                 model: str = "model-a") -> None:
    """basic 模式下把全局 AI 设置写到测试库（base_url/model 即已配置）。"""
    from lumirss.ai_settings import AiSettingsStore, AiSettingsUpdate

    asyncio.run(
        AiSettingsStore(db).save(
            AiSettingsUpdate(baseUrl=base_url, model=model)
        )
    )


def attach_fake_ai(app: Any, db: Database, provider: FakeProvider) -> None:
    """注入与摘要/问答服务同构的设置读取（走同一个 db）。"""
    from lumirss.ai_settings import AiSettingsStore

    app.state.db = db
    app.state.ai_settings_store = AiSettingsStore(db)


def run(coroutine: Any) -> Any:
    return asyncio.run(coroutine)
