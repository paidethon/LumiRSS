"""N084 翻译提供方对照 — 两个已配置提供方、诚实不可用、零缓存写入。

Provider 全部 fake，绝不真实调用。
"""

import asyncio

import pytest

from lumirss.ai_profiles import AiProfileStore
from lumirss.ai_provider import AiProviderError
from lumirss.ai_settings import AiSettingsStore, AiSettingsUpdate
from lumirss.secrets_store import SecretsStore
from lumirss.storage import Database
from lumirss.translation_compare import TranslationCompareService


def run(coroutine):
    return asyncio.run(coroutine)


TEXT = "The quick brown fox jumps."


def _make_service(tmp_path, providers):
    """providers: {purpose: FakeProvider}；工厂按 purpose 取对应 fake，
    记录每次调用的 (base_url, model)。"""
    calls = {"translation": [], "chat": []}

    def factory_for(purpose):
        async def factory(base_url, model):
            calls[purpose].append((base_url, model))
            return providers[purpose]

        return factory

    db_path = tmp_path / "lumi.sqlite"
    db = Database(db_path)
    run(db.migrate())
    settings = AiSettingsStore(db)
    run(
        settings.save(
            AiSettingsUpdate(baseUrl="http://trans.local/v1", model="trans-model")
        )
    )
    secrets = SecretsStore(tmp_path / "secrets.json")
    profiles = AiProfileStore(db, secrets)
    service = TranslationCompareService(
        settings_store=settings,
        profile_store=profiles,
        translation_provider_factory=factory_for("translation"),
        chat_provider_factory=factory_for("chat"),
        secrets=secrets,
    )
    return service, db, settings, profiles, calls


class FakeProvider:
    def __init__(self, reply: str, error: Exception | None = None):
        self._reply = reply
        self._error = error
        self.prompts: list = []

    async def complete(self, messages):
        self.prompts.append(messages)
        if self._error is not None:
            raise self._error
        return self._reply


def _chat_profile(profiles):
    return run(
        profiles.create_profile(
            label="Chat profile",
            base_url="http://chat.local/v1",
            model="chat-model",
        )
    )


def test_n084_two_providers_compare_and_no_cache_writes(tmp_path):
    """chat 用途 profile 与翻译引擎是两个提供方 → 两侧各出一份译文；
    对照零缓存写入；成本口径 chars×2。"""
    providers = {
        "translation": FakeProvider("译文引擎版。"),
        "chat": FakeProvider("译文Profile版。"),
    }
    service, db, settings, profiles, calls = _make_service(tmp_path, providers)
    run(profiles.save_purposes({"chat": _chat_profile(profiles)["id"]}))

    outcome = run(service.compare(TEXT))
    assert outcome.available is True
    assert [s.text for s in outcome.sides] == ["译文引擎版。", "译文Profile版。"]
    assert [s.failure_type for s in outcome.sides] == [None, None]
    assert outcome.estimated_chars == len(TEXT) * 2
    # 每侧一次调用，各自的 (base_url, model)
    assert calls["translation"] == [("http://trans.local/v1", "trans-model")]
    assert calls["chat"] == [("http://chat.local/v1", "chat-model")]

    # 零缓存写入：ai_translation_segments 全空
    rows = run(db.fetch_all("SELECT * FROM ai_translation_segments"))
    assert rows == []


def test_n084_same_resolution_is_honestly_refused(tmp_path):
    """未映射 chat profile 时两侧解析到同一配置 → providers_identical
    （不假装对照、不发起任何 provider 调用）。"""
    providers = {
        "translation": FakeProvider("x"),
        "chat": FakeProvider("y"),
    }
    service, _db, _settings, _profiles, calls = _make_service(tmp_path, providers)
    outcome = run(service.compare(TEXT))
    assert outcome.available is False
    assert outcome.reason == "providers_identical"
    assert outcome.sides == ()
    assert calls["translation"] == []
    assert calls["chat"] == []


def test_n084_unconfigured_provider_is_honest(tmp_path):
    """翻译引擎未配置（无 base_url/model）且无 chat profile →
    provider_not_configured。"""
    db_path = tmp_path / "lumi.sqlite"
    db = Database(db_path)
    run(db.migrate())
    settings = AiSettingsStore(db)
    run(settings.save(AiSettingsUpdate(baseUrl="", model="")))
    secrets = SecretsStore(tmp_path / "secrets.json")
    profiles = AiProfileStore(db, secrets)
    service = TranslationCompareService(
        settings_store=settings,
        profile_store=profiles,
        translation_provider_factory=(lambda b, m: None),
        chat_provider_factory=(lambda b, m: None),
        secrets=secrets,
    )
    outcome = run(service.compare(TEXT))
    assert outcome.available is False
    assert outcome.reason == "provider_not_configured"


def test_n084_side_failure_reported_other_side_kept(tmp_path):
    """单侧失败：失败侧 failureType 如实上报、text=None；另一侧照常
    返回（available=True）。"""
    providers = {
        "translation": FakeProvider("译文引擎版。"),
        "chat": FakeProvider("", error=AiProviderError("boom")),
    }
    service, _db, _settings, profiles, _calls = _make_service(tmp_path, providers)
    run(profiles.save_purposes({"chat": _chat_profile(profiles)["id"]}))

    outcome = run(service.compare(TEXT))
    assert outcome.available is True
    by_label = {s.label: s for s in outcome.sides}
    assert by_label["翻译引擎"].text == "译文引擎版。"
    assert by_label["翻译引擎"].failure_type is None
    assert by_label["AI Profile（chat 用途）"].text is None
    assert by_label["AI Profile（chat 用途）"].failure_type is not None


def test_n084_compare_api_roundtrip(client, monkeypatch):
    """API：两个提供方 → available + 两侧文本；未映射 chat → 诚实
    unavailable（providers_identical）；POST 采用此版只写该段修订。"""
    from lumirss.entryref import encode_entry_ref
    from lumirss.main import app

    # 路由层的提供方工厂替换为可控 fake（避免任何真实网络）；两个
    # purpose 返回可区分的 fake provider。
    class _FakeProvider:
        def __init__(self, tag):
            self.tag = tag

        async def complete(self, messages):
            return f"{self.tag}译文。"

    factories = {
        "translation": _FakeProvider("引擎"),
        "chat": _FakeProvider("Profile"),
    }
    def _fake_factory_for(_request, purpose):
        async def factory(_base_url, _model):
            return factories[purpose]

        return factory

    monkeypatch.setattr(
        "lumirss.routers.entry_ai._provider_factory_for",
        _fake_factory_for,
        raising=True,
    )

    # 经 API 配置翻译引擎默认配置 + chat 用途 profile（请求内自带
    # 认证上下文，直接构造 store 反而绕开了 per-user secrets 路由）。
    saved = client.put(
        "/api/v1/settings/ai",
        json={"baseUrl": "http://trans.local/v1", "model": "tm"},
    )
    assert saved.status_code == 200, saved.text
    created = client.post(
        "/api/v1/settings/ai/profiles",
        json={"label": "Chat", "baseUrl": "http://chat.local/v1", "model": "cm"},
    )
    assert created.status_code == 201, created.text
    profile_id = created.json()["id"]
    mapped = client.put(
        "/api/v1/settings/ai/purposes", json={"chat": profile_id}
    )
    assert mapped.status_code == 200, mapped.text

    ref = encode_entry_ref("e1.n084api")

    # 先产生两个块的正常翻译缓存行（对照绝不新增/改写行）
    from lumirss.ai_translation_segments import (
        SegmentInput,
        SegmentTranslationService,
    )

    async def _gen():
        await app.state.db.migrate()
        service = SegmentTranslationService(
            db=app.state.db,
            settings_store=AiSettingsStore(app.state.db),
            provider_factory=_echo_marker_provider,
            secrets=app.state.secrets_store,
        )
        return await service.generate(
            ref,
            [
                SegmentInput(index=0, text="Block zero."),
                SegmentInput(index=1, text="Block one."),
            ],
        )

    run(_gen())

    url = f"/api/v1/entries/{ref}/translation-compare"
    compare = client.post(url, json={"blockIndex": 1, "text": "Block one."})
    assert compare.status_code == 200, compare.text
    payload = compare.json()
    assert payload["available"] is True
    assert [s["label"] for s in payload["sides"]] == [
        "翻译引擎",
        "AI Profile（chat 用途）",
    ]
    assert {s["text"] for s in payload["sides"]} == {"引擎译文。", "Profile译文。"}
    assert payload["estimatedChars"] == len("Block one.") * 2

    # 对照零缓存写入：只有 generate 产生的 2 行
    rows = run(app.state.db.fetch_all("SELECT * FROM ai_translation_segments"))
    assert len(rows) == 2

    # 采用此版（显式用户选择）：走既有修订端点，只写该块
    adopt = client.put(
        f"/api/v1/entries/{ref}/translation/segments/1/revision",
        json={"text": "Profile译文。"},
    )
    assert adopt.status_code == 200, adopt.text
    rows = run(
        app.state.db.fetch_all(
            "SELECT block_index, user_revision FROM ai_translation_segments WHERE user_revision IS NOT NULL"
        )
    )
    assert [(r["block_index"], r["user_revision"]) for r in rows] == [
        (1, "Profile译文。")
    ]

    # 未映射 chat 的对照（purpose 映射清空）→ providers_identical
    cleared = client.put("/api/v1/settings/ai/purposes", json={"chat": "default"})
    assert cleared.status_code == 200, cleared.text
    honest = client.post(url, json={"blockIndex": 0, "text": "Block zero."})
    assert honest.status_code == 200, honest.text
    body = honest.json()
    assert body["available"] is False
    assert body["reason"] == "providers_identical"
    assert body["sides"] == []


async def _echo_marker_provider(base_url, model):
    """generate 用 fake factory：按 marker 回显「机器译<n>」，产生成功缓存行。"""
    import re

    class _P:
        async def complete(self, messages):
            markers = re.findall(
                r"^<<<BLOCK (\d+)>>>", messages[-1]["content"], re.M
            )
            return "\n\n".join(
                f"<<<BLOCK {int(i)}>>>\n机器译{int(i)}。" for i in markers
            )

    return _P()


@pytest.fixture(autouse=True)
def _allow_fixture_endpoints(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(
        "LUMIRSS_FETCH_ALLOW_PRIVATE_HOSTS", "127.0.0.1,trans.local,chat.local"
    )
