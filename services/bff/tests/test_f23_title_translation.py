"""F23 标题按需翻译 — 缓存身份与单条语义测试。

- 首次翻译 → provider 调用一次并入库；
- 同标题/语言/模型再次请求 → 缓存命中（provider 不再调用）；
- 标题变化 → 缓存失效重新翻译；
- 空输出 → AiInvalidResponse（502 映射）。
"""

import asyncio

from lumirss.adapters.freshrss import EntryDetail
from lumirss.main import app
from lumirss.title_translation import TitleTranslationService


def run(coroutine):
    return asyncio.run(coroutine)


class _FakeAdapter:
    def __init__(self, title: str):
        self._title = title

    async def get_entry(self, item_id: str):
        return EntryDetail(
            entryRef=f"e1.{item_id}",
            title=self._title,
            feedTitle="源",
            author=None,
            url=None,
            publishedAt="2026-09-18T00:00:00Z",
            crawledAt=None,
            read=False,
            starred=False,
            contentText="正文",
            contentHtml="<p>正文</p>",
        )


class _FakeAiSettings:
    async def load(self):
        return {"ai.base_url": "http://ai.local", "ai.model": "test-model"}


class _FakeProvider:
    def __init__(self, outputs: list[str]):
        self._outputs = list(outputs)
        self.calls = 0

    async def complete(self, *, messages):
        self.calls += 1
        assert messages[0]["role"] == "system"
        return self._outputs.pop(0) if self._outputs else self._outputs[-1]


def _ok(provider):
    async def factory(base_url, model):
        return provider

    return factory


def _service():
    return TitleTranslationService(app.state.db)


def test_f23_translate_caches_by_title_language_model(client):
    provider = _FakeProvider(["Translated Title", "翻译后的标题"])
    result = run(
        _service().translate(
            _FakeAdapter("Some Title"),
            _FakeAiSettings(),
            _ok(provider),
            "e1.MDAwNjU5ZTA3YWFlZTI0ZA",
            "en",
        )
    )
    assert result["translatedTitle"] == "Translated Title"
    assert result["cached"] is False
    assert result["language"] == "en"
    assert provider.calls == 1
    # 同标题/语言/模型 → 缓存命中，provider 只调一次
    again = run(
        _service().translate(
            _FakeAdapter("Some Title"),
            _FakeAiSettings(),
            _ok(provider),
            "e1.MDAwNjU5ZTA3YWFlZTI0ZA",
            "en",
        )
    )
    assert again["translatedTitle"] == "Translated Title"
    assert again["cached"] is True
    assert provider.calls == 1
    # 语言变化 → 缓存身份变化 → 重新翻译
    third = run(
        _service().translate(
            _FakeAdapter("Some Title"),
            _FakeAiSettings(),
            _ok(provider),
            "e1.MDAwNjU5ZTA3YWFlZTI0ZA",
            "zh-CN",
        )
    )
    assert provider.calls == 2
    assert third["language"] == "zh-CN"


def test_f23_title_change_invalidates_cache(client):
    adapter = _FakeAdapter("Title V1")
    provider = _FakeProvider(["T1", "T2"])
    service = _service()
    run(
        service.translate(
            adapter, _FakeAiSettings(), _ok(provider), "e1.MDAwNjU5ZTA3YWFlZTI0ZA", "en"
        )
    )
    adapter2 = _FakeAdapter("Title V2")
    result = run(
        service.translate(
            adapter2, _FakeAiSettings(), _ok(provider), "e1.MDAwNjU5ZTA3YWFlZTI0ZA", "en"
        )
    )
    assert result["translatedTitle"] == "T2"
    assert result["cached"] is False


def test_f23_empty_output_rejected(client):
    from lumirss.ai_provider import AiInvalidResponse

    provider = _FakeProvider(["   "])
    try:
        run(
            _service().translate(
                _FakeAdapter("Some Title"),
                _FakeAiSettings(),
                _ok(provider),
                "e1.MDAwNjU5ZTA3YWFlZTI0ZA",
                "en",
            )
        )
    except AiInvalidResponse:
        pass
    else:
        raise AssertionError("empty output should raise")


def test_f23_title_cache_ignores_glossary_bump_but_keys_model_and_prompt(
    client,
):
    """FIX-144（验证另一半口径）：标题翻译的 prompt 不附带术语表，因此
    术语写操作**不得**让它失效；而 model + prompt_version 保持键入
    （换模型必须重新翻译）。两条断言共同钉住「键维度 = prompt 实际
    依赖」这一单一口径。"""
    from lumirss.glossary import bump_glossary_version

    provider = _FakeProvider(["Translated Title", "另一个模型的标题"])
    service = _service()
    entry_ref = "e1.MDAwNjU5ZTA3YWFlZTI0ZA"

    first = run(
        service.translate(
            _FakeAdapter("Stable Title"),
            _FakeAiSettings(),
            _ok(provider),
            entry_ref,
            "en",
        )
    )
    assert first["cached"] is False and provider.calls == 1

    # 术语写操作：标题缓存必须原样命中（prompt 无术语表维度）。
    run(bump_glossary_version(app.state.db))
    hit = run(
        service.translate(
            _FakeAdapter("Stable Title"),
            _FakeAiSettings(),
            _ok(provider),
            entry_ref,
            "en",
        )
    )
    assert hit["cached"] is True and provider.calls == 1

    # 换模型：缓存身份含 model → 重新翻译，绝不复用旧模型结果。
    class _OtherModelSettings(_FakeAiSettings):
        async def load(self):
            return {"ai.base_url": "http://ai.local", "ai.model": "other-model"}

    other = run(
        service.translate(
            _FakeAdapter("Stable Title"),
            _OtherModelSettings(),
            _ok(provider),
            entry_ref,
            "en",
        )
    )
    assert other["cached"] is False and provider.calls == 2
    assert other["model"] == "other-model"
