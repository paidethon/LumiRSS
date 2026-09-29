"""NEW-269 语言识别纠正 — 某文/某源识别语言的显式更正。

- 更正只影响其后的新生成（LT source 参数 / AI 源语言指令）；
- 既有缓存行不被悄悄改写或失效（缓存身份不变）；
- entry 级更正优先于 source 级；
- A/B 隔离。
"""

import asyncio
import re

import pytest

from lumirss.ai_settings import (
    TRANSLATION_ENGINE_LIBRETRANSLATE,
    AiSettingsStore,
    AiSettingsUpdate,
)
from lumirss.ai_translation_segments import (
    SegmentInput,
    SegmentTranslationService,
)
from lumirss.entryref import encode_entry_ref
from lumirss.new269_language_overrides import (
    LanguageOverrideInvalid,
    delete_override,
    get_override,
    list_overrides,
    resolve_source_language,
    set_override,
)
from lumirss.secrets_store import SecretsStore
from lumirss.storage import Database
from new2xx_ab import ab_env, seed_entry  # noqa: F401

run = asyncio.run


@pytest.fixture(autouse=True)
def _allow_fixture_endpoints(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LUMIRSS_FETCH_ALLOW_PRIVATE_HOSTS", "127.0.0.1,ai.local")


class _CaptureResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {"translatedText": ["LT译"]}


class _CaptureClient:
    def __init__(self, log):
        self._log = log

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def post(self, url, json=None):
        self._log.append(json)
        return _CaptureResponse()


def _make(tmp_path, calls, engine="ai", seed_feed_row=None):
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    settings = AiSettingsStore(db)
    run(
        settings.save(
            AiSettingsUpdate(
                baseUrl="http://127.0.0.1:9/v1",
                model="m1",
                translationEngine=engine,
                libretranslateUrl=(
                    "http://ai.local/lt" if engine == TRANSLATION_ENGINE_LIBRETRANSLATE else None
                ),
            )
        )
    )
    if seed_feed_row is not None:
        ref, feed_url = seed_feed_row
        run(
            db.execute(
                "INSERT INTO search_entries (item_id, entry_ref, feed_url, "
                "title, content_text, published_at, fetched_at) "
                "VALUES (?, ?, ?, 't', 'c', '2026-09-01T00:00:00Z', 1)",
                (f"i.{ref}", ref, feed_url),
            )
        )
    captured_prompts: list[str] = []

    async def factory(base_url, model):
        calls["n"] += 1

        class FakeProvider:
            async def complete(self, messages):
                captured_prompts.append(messages[0]["content"] + "|" + messages[-1]["content"])
                markers = re.findall(
                    r"^<<<BLOCK (\d+)>>>", messages[-1]["content"], re.M
                )
                return "\n\n".join(
                    f"<<<BLOCK {int(i)}>>>\n译{int(i)}。" for i in markers
                )

        return FakeProvider()

    service = SegmentTranslationService(
        db=db,
        settings_store=settings,
        provider_factory=factory,
        secrets=SecretsStore(tmp_path / "secrets.json"),
        httpx_client_factory=lambda: _CaptureClient(calls["payloads"]),
    )
    return service, db, captured_prompts


def test_override_crud_and_upsert_semantics(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    with pytest.raises(LanguageOverrideInvalid):
        run(set_override(db, "galaxy", "ref", "en"))
    with pytest.raises(LanguageOverrideInvalid):
        run(set_override(db, "entry", "ref", "not a lang"))
    with pytest.raises(LanguageOverrideInvalid):
        run(set_override(db, "entry", "ref", "e"))

    first = run(set_override(db, "entry", "e1.k", "fr"))
    assert first["language"] == "fr"
    second = run(set_override(db, "entry", "e1.k", "de"))  # 再次更正覆盖
    assert second["language"] == "de"
    assert second["createdAt"] == first["createdAt"]  # 首次时间保留
    assert second["updatedAt"] >= first["updatedAt"]

    assert run(get_override(db, "entry", "e1.k"))["language"] == "de"
    assert run(delete_override(db, "entry", "e1.k")) is True
    assert run(delete_override(db, "entry", "e1.k")) is False
    assert run(list_overrides(db)) == []


def test_resolution_entry_wins_over_source(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    ref = "e1.n269res"
    run(
        db.execute(
            "INSERT INTO search_entries (item_id, entry_ref, feed_url, "
            "title, content_text, published_at, fetched_at) "
            "VALUES (?, ?, 'https://feed.example/rss', 't', 'c', "
            "'2026-09-01T00:00:00Z', 1)",
            (f"i.{ref}", ref),
        )
    )
    # 只有源级更正
    run(set_override(db, "source", "https://feed.example/rss", "fr"))
    assert run(resolve_source_language(db, ref)) == "fr"
    # entry 级更正优先
    run(set_override(db, "entry", ref, "ja"))
    assert run(resolve_source_language(db, ref)) == "ja"
    # 未知条目（无投影行）→ 只有 entry 级可用
    assert run(resolve_source_language(db, "e1.unknown")) is None
    run(set_override(db, "entry", "e1.unknown", "pt"))
    assert run(resolve_source_language(db, "e1.unknown")) == "pt"


def test_ai_generation_carries_source_instruction(tmp_path):
    calls = {"n": 0}
    service, db, prompts = _make(tmp_path, calls)
    ref = encode_entry_ref("e1.n269ai")
    blocks = [SegmentInput(index=0, text="Original text.")]

    run(service.generate(ref, blocks))
    assert "source text's language" not in prompts[0]

    run(set_override(db, "entry", ref, "fr"))
    run(service.generate(ref, [SegmentInput(index=1, text="More text.")]))
    assert "The source text's language is 'fr'" in prompts[1]
    assert calls["n"] == 2

    # 已产生结果不悄悄改变：旧缓存行原样返回
    states = run(service.lookup(ref, blocks))
    assert states[0].cached is True and states[0].translated_text == "译0。"


def test_libretranslate_source_param_follows_override(tmp_path):
    calls = {"n": 0, "payloads": []}
    service, db, _prompts = _make(
        tmp_path, calls, engine=TRANSLATION_ENGINE_LIBRETRANSLATE
    )
    ref = encode_entry_ref("e1.n269lt")
    blocks = [SegmentInput(index=0, text="Original text.")]

    run(service.generate(ref, blocks))
    assert calls["payloads"][0]["source"] == "auto"

    run(set_override(db, "entry", ref, "zh-CN"))
    run(service.generate(ref, [SegmentInput(index=1, text="More.")]))
    assert calls["payloads"][1]["source"] == "zh"  # LT 源码风格（前缀归一）


# ---------------------------------------------------------------------------
# API 行为
# ---------------------------------------------------------------------------


def test_api_language_override_roundtrip(client):
    made = client.put(
        "/api/v1/translation/language-overrides",
        json={"scope": "source", "refKey": "https://feed.example/rss", "language": "fr"},
    )
    assert made.status_code == 200, made.text

    listed = client.get("/api/v1/translation/language-overrides").json()["overrides"]
    assert [o["language"] for o in listed] == ["fr"]

    bad = client.put(
        "/api/v1/translation/language-overrides",
        json={"scope": "entry", "refKey": "malformed", "language": "fr"},
    )
    assert bad.status_code == 400  # entry scope 的 refKey 必须是合法 entry_ref

    removed = client.delete(
        "/api/v1/translation/language-overrides",
        params={"scope": "source", "refKey": "https://feed.example/rss"},
    )
    assert removed.status_code == 200
    assert (
        client.delete(
            "/api/v1/translation/language-overrides",
            params={"scope": "source", "refKey": "https://feed.example/rss"},
        ).status_code
        == 404
    )


def test_api_entry_effective_override(client, tmp_path):
    ref = encode_entry_ref("e1.n269api")

    async def run_seed():
        from lumirss.main import app as lumi_app

        db = lumi_app.state.db
        await db.migrate()
        await db.execute(
            "INSERT INTO search_entries (item_id, entry_ref, feed_url, "
            "title, content_text, published_at, fetched_at) "
            "VALUES (?, ?, 'https://feed.example/api', 't', 'c', "
            "'2026-09-01T00:00:00Z', 1)",
            (f"i.{ref}", ref),
        )

    run(run_seed())

    empty = client.get(f"/api/v1/entries/{ref}/translation/language-override")
    assert empty.json()["language"] is None

    client.put(
        "/api/v1/translation/language-overrides",
        json={"scope": "source", "refKey": "https://feed.example/api", "language": "de"},
    )
    effective = client.get(f"/api/v1/entries/{ref}/translation/language-override")
    assert effective.json()["language"] == "de"


# ---------------------------------------------------------------------------
# A/B 隔离
# ---------------------------------------------------------------------------


def test_ab_language_overrides_isolated(ab_env):  # noqa: F811
    env = ab_env
    client = env["client"]
    ref = encode_entry_ref("e1.new269ab")
    seed_entry(env, "a", "new269ab")
    seed_entry(env, "b", "new269ab")

    made = client.put(
        "/api/v1/translation/language-overrides",
        json={"scope": "entry", "refKey": ref, "language": "fr"},
        headers=env["a"],
    )
    assert made.status_code == 200, made.text

    a_eff = client.get(
        f"/api/v1/entries/{ref}/translation/language-override", headers=env["a"]
    ).json()
    b_eff = client.get(
        f"/api/v1/entries/{ref}/translation/language-override", headers=env["b"]
    ).json()
    assert a_eff["language"] == "fr"
    assert b_eff["language"] is None  # bob 的库里没有 alice 的更正
