"""N083 专有名词保留清单 —— glossary protect 标记 + 还原后处理 + 缓存失效。

- 受保护术语在译文里大小写漂移 → 还原为词表原始词形（存进缓存行）；
- 术语被整体改写/翻译掉 → 如实上报未保护（不臆造）；
- prompt 指令列出受保护术语（AI 引擎）；
- protect 翻转推进 glossary_version → 旧缓存行不再匹配（重新生成），
  未受 glossary 影响之前缓存保持原样。
"""

import asyncio
import json

import httpx
import pytest

from lumirss.ai_settings import AiSettingsStore, AiSettingsUpdate
from lumirss.ai_translation_segments import (
    SegmentInput,
    SegmentTranslationService,
)
from lumirss.glossary import GlossaryStore, get_glossary_version
from lumirss.glossary_hits import (
    apply_term_protection,
    term_protection_report,
)
from lumirss.secrets_store import SecretsStore
from lumirss.storage import Database

run = asyncio.run


@pytest.fixture(autouse=True)
def _allow_fixture_endpoints(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LUMIRSS_FETCH_ALLOW_PRIVATE_HOSTS", "127.0.0.1,ai.local")


def _marker(index: int) -> str:
    return f"<<<BLOCK {index}>>>"

def _make_service(tmp_path, provider_factory=None, transport=None):
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    settings = AiSettingsStore(db)
    secrets = SecretsStore(tmp_path / "secrets.json")
    httpx_factory = (
        (lambda: httpx.AsyncClient(transport=transport))
        if transport is not None
        else None
    )
    service = SegmentTranslationService(
        db=db,
        settings_store=settings,
        provider_factory=provider_factory or _never_provider,
        secrets=secrets,
        httpx_client_factory=httpx_factory,
    )
    return service, settings, secrets, db


async def _never_provider(base_url, model):
    raise AssertionError("provider must never be built in this flow")


async def _configure_ai(settings):
    await settings.save(
        AiSettingsUpdate(baseUrl="http://127.0.0.1:9999/v1", model="m1")
    )


def _reply(indexes_texts: dict[int, str]) -> str:
    return "\n\n".join(
        _marker(index) + "\n" + text for index, text in indexes_texts.items()
    )


# ---------------------------------------------------------------------------
# 还原后处理（纯函数）
# ---------------------------------------------------------------------------


def test_apply_protection_restores_case_drift():
    assert apply_term_protection("graphql 查询语言很流行。", ["GraphQL"]) == (
        "GraphQL 查询语言很流行。"
    )


def test_apply_protection_exact_is_identity():
    text = "GraphQL 查询语言很流行。"
    assert apply_term_protection(text, ["GraphQL"]) == text


def test_protection_report_absent_term_unprotected():
    report = term_protection_report("被完全改写的译文。", ["GraphQL"])
    assert report == [
        {
            "term": "GraphQL",
            "protected": False,
            "reason": "term not found in translation",
        }
    ]


def test_protection_report_counts_exact_and_restored():
    exact = term_protection_report("GraphQL 很好。GraphQL 为主。", ["GraphQL"])
    assert exact == [{"term": "GraphQL", "protected": True, "count": 2}]
    restored = term_protection_report("graphql 很好。", ["GraphQL"])
    assert restored == [
        {"term": "GraphQL", "protected": True, "count": 1, "restored": True}
    ]


# ---------------------------------------------------------------------------
# 生成链路（fake provider）
# ---------------------------------------------------------------------------


def test_generate_restores_protected_term_and_reports(tmp_path):
    seen_messages: list[list[dict]] = []

    async def factory(base_url, model):
        class FakeProvider:
            async def complete(self, messages):
                seen_messages.append(messages)
                return _reply({0: "graphql 查询语言很流行。"})

        return FakeProvider()

    service, settings, _secrets, db = _make_service(tmp_path, factory)
    run(_configure_ai(settings))
    run(GlossaryStore(db).create("GraphQL", "一种查询语言", None, True))

    blocks = [SegmentInput(index=0, text="GraphQL is a query language.")]
    states = run(service.generate("e1.n083", blocks))

    assert states[0].status == "success"
    # 大小写漂移被还原为词表原始词形（这就是缓存/返回的文本）。
    assert "GraphQL" in states[0].translated_text
    assert "graphql" not in states[0].translated_text
    assert states[0].protected_terms == (
        {"term": "GraphQL", "protected": True, "count": 1, "restored": True},
    )
    # 存储行同样是还原后的文本（lookup 自然返回）。
    row = run(db.fetch_one(
        "SELECT translated_text FROM ai_translation_segments WHERE entry_ref = 'e1.n083'"
    ))
    assert "GraphQL" in str(row["translated_text"])
    # prompt 指令逐条列出受保护术语。
    system = seen_messages[0][0]["content"]
    assert "GraphQL" in system
    assert "VERBATIM" in system


def test_generate_reports_unprotected_when_term_translated_away(tmp_path):
    async def factory(base_url, model):
        class FakeProvider:
            async def complete(self, messages):
                return _reply({0: "这种查询语言很流行。"})

        return FakeProvider()

    service, settings, _secrets, db = _make_service(tmp_path, factory)
    run(_configure_ai(settings))
    run(GlossaryStore(db).create("GraphQL", "一种查询语言", None, True))

    blocks = [SegmentInput(index=0, text="GraphQL is popular.")]
    states = run(service.generate("e1.n083b", blocks))
    assert states[0].status == "success"
    assert states[0].protected_terms == (
        {
            "term": "GraphQL",
            "protected": False,
            "reason": "term not found in translation",
        },
    )


def test_lookup_recomputes_protection_report_for_cached_rows(tmp_path):
    async def factory(base_url, model):
        class FakeProvider:
            async def complete(self, messages):
                return _reply({0: "GraphQL 查询语言。"})

        return FakeProvider()

    service, settings, _secrets, db = _make_service(tmp_path, factory)
    run(_configure_ai(settings))
    run(GlossaryStore(db).create("GraphQL", "一种查询语言", None, True))
    blocks = [SegmentInput(index=0, text="GraphQL rocks.")]
    run(service.generate("e1.n083c", blocks))

    states = run(service.lookup("e1.n083c", blocks))
    assert states[0].cached is True
    assert states[0].protected_terms == (
        {"term": "GraphQL", "protected": True, "count": 1},
    )


def test_unprotected_terms_never_enter_report(tmp_path):
    """protect=0 的术语不参与还原，也不出现在报告里。"""

    async def factory(base_url, model):
        class FakeProvider:
            async def complete(self, messages):
                return _reply({0: "graphql 查询语言。"})

        return FakeProvider()

    service, settings, _secrets, db = _make_service(tmp_path, factory)
    run(_configure_ai(settings))
    run(GlossaryStore(db).create("GraphQL", "一种查询语言", None, False))

    blocks = [SegmentInput(index=0, text="GraphQL rocks.")]
    states = run(service.generate("e1.n083d", blocks))
    assert "graphql" in states[0].translated_text  # 未保护 → 不还原
    assert states[0].protected_terms == ()


# ---------------------------------------------------------------------------
# 缓存失效：protect 翻转推进 glossary_version
# ---------------------------------------------------------------------------


def test_protect_flip_invalidates_segment_cache(tmp_path):
    calls = {"n": 0}

    async def factory(base_url, model):
        class FakeProvider:
            async def complete(self, messages):
                calls["n"] += 1
                return _reply({0: "graphql 查询语言。"})

        return FakeProvider()

    service, settings, _secrets, db = _make_service(tmp_path, factory)
    run(_configure_ai(settings))
    store = GlossaryStore(db)
    term = run(store.create("GraphQL", "一种查询语言", None, False))

    blocks = [SegmentInput(index=0, text="GraphQL rocks.")]
    first = run(service.generate("e1.n083e", blocks))
    assert calls["n"] == 1
    assert "graphql" in first[0].translated_text
    version_before = run(get_glossary_version(db))

    # 未写术语表时缓存稳定命中（版本号未动）。
    cached = run(service.generate("e1.n083e", blocks))
    assert cached[0].cached is True
    assert calls["n"] == 1

    # protect 翻转 = glossary 写操作 → 版本推进 → 旧行不再匹配。
    run(store.update(term["id"], "GraphQL", "一种查询语言", True))
    version_after = run(get_glossary_version(db))
    assert version_after != version_before

    looked = run(service.lookup("e1.n083e", blocks))
    assert looked[0].status == "not_generated"  # 旧缓存不再返回

    second = run(service.generate("e1.n083e", blocks))
    assert calls["n"] == 2  # 重新生成（provider 再次被调用）
    assert second[0].cached is False
    assert second[0].translated_text == "GraphQL 查询语言。"  # 还原生效
    assert second[0].protected_terms == (
        {"term": "GraphQL", "protected": True, "count": 1, "restored": True},
    )


# ---------------------------------------------------------------------------
# LibreTranslate 引擎同样做保留后处理
# ---------------------------------------------------------------------------


def test_libretranslate_protect_restore(tmp_path):
    def responder(request):
        payload = json.loads(request.read())
        sources = payload["q"]
        translated = [text.replace("GraphQL", "graphql") for text in sources]
        return httpx.Response(200, json={"translatedText": translated})

    service, settings, _secrets, db = _make_service(
        tmp_path, transport=httpx.MockTransport(responder)
    )
    run(settings.save(AiSettingsUpdate(translationEngine="libretranslate")))
    run(settings.save(AiSettingsUpdate(libretranslateUrl="http://127.0.0.1:5000")))
    run(GlossaryStore(db).create("GraphQL", "一种查询语言", None, True))

    blocks = [SegmentInput(index=0, text="GraphQL is a query language.")]
    states = run(service.generate("e1.n083f", blocks))
    assert states[0].status == "success"
    assert states[0].translated_text == "GraphQL is a query language."
    assert states[0].protected_terms == (
        {"term": "GraphQL", "protected": True, "count": 1, "restored": True},
    )
