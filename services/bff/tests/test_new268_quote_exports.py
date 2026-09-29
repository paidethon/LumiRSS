"""NEW-268 译文引用导出 — 附原文/来源/机器人工标记的引用导出。

- 人工修订段 → 人工文本 + humanRevised=true；否则机器文本；
- 未显式 confirmed → 422；无成功缓存译文 → 422；
- 来源取 search_entries 投影（feed_url/feed_title，尽力而为）；
- 台账 cap=50；A/B 隔离。
"""

import asyncio
import re

import pytest

from lumirss.ai_settings import AiSettingsStore, AiSettingsUpdate
from lumirss.ai_translation_revisions import save_revision
from lumirss.ai_translation_segments import (
    SegmentInput,
    SegmentTranslationService,
)
from lumirss.entryref import encode_entry_ref
from lumirss.new268_quote_exports import (
    QUOTE_EXPORT_CAP,
    QuoteNotConfirmed,
    QuoteUnavailable,
    export_quote,
    list_exports,
)
from lumirss.secrets_store import SecretsStore
from lumirss.storage import Database
from new2xx_ab import ab_env, seed_entry  # noqa: F401

run = asyncio.run


@pytest.fixture(autouse=True)
def _allow_fixture_endpoints(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LUMIRSS_FETCH_ALLOW_PRIVATE_HOSTS", "127.0.0.1,ai.local")


def _echo_provider(calls):
    async def factory(base_url, model):
        calls["n"] += 1

        class FakeProvider:
            async def complete(self, messages):
                markers = re.findall(
                    r"^<<<BLOCK (\d+)>>>", messages[-1]["content"], re.M
                )
                return "\n\n".join(
                    f"<<<BLOCK {int(i)}>>>\n译{int(i)}。" for i in markers
                )

        return FakeProvider()

    return factory


def _make(tmp_path, calls):
    from lumirss.entryref import encode_entry_ref as _enc

    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    settings = AiSettingsStore(db)
    run(settings.save(AiSettingsUpdate(baseUrl="http://127.0.0.1:9/v1", model="m1")))
    run(
        db.execute(
            "INSERT INTO search_entries (item_id, entry_ref, feed_url, feed_title, "
            "title, content_text, published_at, fetched_at) "
            "VALUES (?, ?, 'https://feed.example/post', '示例周刊', "
            "'t', 'c', '2026-09-01T00:00:00Z', 1)",
            ("i.e1.n268a", _enc("e1.n268a")),
        )
    )
    service = SegmentTranslationService(
        db=db,
        settings_store=settings,
        provider_factory=_echo_provider(calls),
        secrets=SecretsStore(tmp_path / "secrets.json"),
    )
    return service, db


def test_export_machine_and_human_quotes(tmp_path):
    calls = {"n": 0}
    service, db = _make(tmp_path, calls)
    ref = encode_entry_ref("e1.n268a")
    blocks = [
        SegmentInput(index=0, text="Source zero."),
        SegmentInput(index=1, text="Source one."),
    ]
    run(service.generate(ref, blocks))
    run(save_revision(db, ref, 1, "人工定稿版"))

    human = run(
        export_quote(db, service, ref, 1, "Source one.", "markdown", confirmed=True)
    )
    assert human["humanRevised"] is True
    assert human["translatedText"] == "人工定稿版"
    assert human["sourceText"] == "Source one."
    assert human["feedTitle"] == "示例周刊" and "feed.example" in human["sourceUrl"]
    assert human["rendered"].startswith("> 人工定稿版")
    assert "人工修订" in human["rendered"] and "示例周刊" in human["rendered"]

    machine = run(
        export_quote(db, service, ref, 0, "Source zero.", "text", confirmed=True)
    )
    assert machine["humanRevised"] is False
    assert machine["translatedText"] == "译0。"
    assert machine["rendered"].startswith("译0。")
    assert "机器翻译" in machine["rendered"]

    items = run(list_exports(db, ref))
    # 同秒内创建（utc_now 秒级精度）顺序不保证；集合与数量如实
    assert {i["id"] for i in items} == {machine["id"], human["id"]}

    # 缓存译文未被导出动作改写
    states = run(service.lookup(ref, blocks))
    assert states[1].user_revision == "人工定稿版"


def test_export_requires_confirmation_and_cached_text(tmp_path):
    calls = {"n": 0}
    service, db = _make(tmp_path, calls)
    ref = encode_entry_ref("e1.n268b")
    blocks = [SegmentInput(index=0, text="Source zero.")]
    run(service.generate(ref, blocks))

    with pytest.raises(QuoteNotConfirmed):
        run(export_quote(db, service, ref, 0, "Source zero.", "markdown", False))
    with pytest.raises(QuoteUnavailable):
        run(export_quote(db, service, ref, 5, "Missing block.", "markdown", True))
    with pytest.raises(QuoteUnavailable):
        run(export_quote(db, service, ref, 0, "Totally different text.", "text", True))
    with pytest.raises(QuoteUnavailable):
        run(export_quote(db, service, ref, 0, "Source zero.", "html", True))


def test_export_cap_prunes_oldest(tmp_path):
    calls = {"n": 0}
    service, db = _make(tmp_path, calls)
    ref = encode_entry_ref("e1.n268c")
    run(service.generate(ref, [SegmentInput(index=0, text="Source zero.")]))
    for _ in range(QUOTE_EXPORT_CAP + 3):
        run(export_quote(db, service, ref, 0, "Source zero.", "text", True))
    rows = run(db.fetch_all(
        "SELECT id FROM translation_quote_exports WHERE entry_ref = ?", (ref,)
    ))
    assert len(rows) == QUOTE_EXPORT_CAP


# ---------------------------------------------------------------------------
# API 行为
# ---------------------------------------------------------------------------


def _seed_api(client, tmp_path, entry_key: str, calls: dict):
    ref = encode_entry_ref(f"e1.{entry_key}")

    async def run_seed():
        from lumirss.main import app as lumi_app

        db = lumi_app.state.db
        await db.migrate()
        settings = AiSettingsStore(db)
        await settings.save(
            AiSettingsUpdate(baseUrl="http://127.0.0.1:9/v1", model="m1")
        )
        service = SegmentTranslationService(
            db=db,
            settings_store=settings,
            provider_factory=_echo_provider(calls),
            secrets=SecretsStore(str(tmp_path / f"{entry_key}-secrets.json")),
        )
        await service.generate(ref, [SegmentInput(index=0, text="Source zero.")])
        lumi_app.state.segment_translation_service = service

    run(run_seed())
    return ref


def test_api_quote_export_roundtrip(client, tmp_path):
    calls = {"n": 0}
    ref = _seed_api(client, tmp_path, "n268api", calls)

    unconfirmed = client.post(
        f"/api/v1/entries/{ref}/translation/segments/0/quote-export",
        json={"blockText": "Source zero.", "confirmed": False},
    )
    assert unconfirmed.status_code == 422
    assert unconfirmed.json()["error"]["type"] == "quote_not_confirmed"

    made = client.post(
        f"/api/v1/entries/{ref}/translation/segments/0/quote-export",
        json={"blockText": "Source zero.", "format": "markdown", "confirmed": True},
    )
    assert made.status_code == 200, made.text
    body = made.json()
    assert body["humanRevised"] is False
    assert body["rendered"].startswith("> 译0。")

    listed = client.get(f"/api/v1/entries/{ref}/translation/quote-exports")
    assert [i["id"] for i in listed.json()["exports"]] == [body["id"]]

    missing = client.post(
        f"/api/v1/entries/{ref}/translation/segments/9/quote-export",
        json={"blockText": "No such block.", "confirmed": True},
    )
    assert missing.status_code == 422
    assert missing.json()["error"]["type"] == "quote_unavailable"


# ---------------------------------------------------------------------------
# A/B 隔离
# ---------------------------------------------------------------------------


def test_ab_quote_exports_isolated(ab_env):  # noqa: F811
    env = ab_env
    client = env["client"]
    ref = encode_entry_ref("e1.new268ab")
    seed_entry(env, "a", "new268ab")
    seed_entry(env, "b", "new268ab")

    a_view = client.get(
        f"/api/v1/entries/{ref}/translation/quote-exports", headers=env["a"]
    )
    b_view = client.get(
        f"/api/v1/entries/{ref}/translation/quote-exports", headers=env["b"]
    )
    assert a_view.status_code == 200 and b_view.status_code == 200
    assert a_view.json()["exports"] == [] and b_view.json()["exports"] == []

    # 无缓存译文 → 诚实 422；台账仍按人隔离（各自为空）
    made = client.post(
        f"/api/v1/entries/{ref}/translation/segments/0/quote-export",
        json={"blockText": "Text.", "confirmed": True},
        headers=env["a"],
    )
    assert made.status_code == 422
    assert (
        client.get(
            f"/api/v1/entries/{ref}/translation/quote-exports", headers=env["b"]
        ).json()["exports"]
        == []
    )
