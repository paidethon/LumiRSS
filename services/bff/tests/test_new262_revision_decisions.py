"""NEW-262 译文人工修订层 — 逐段「放弃修订并重翻」显式决定。

- 留底：被放弃时刻的人工文本完整入台账（0189 只追加，不销毁历史）；
- 撤销后该段回到普通未生成状态；regenerate=true 立即按缓存源段重翻
  （只发该段，一次 provider 调用）；机器原稿（translated_text）从不改写；
- 其余修订段原样保留（F062 默认语义不变）；
- A/B 隔离：A 放弃自己的修订，B 的修订原样保留。
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
from lumirss.secrets_store import SecretsStore
from lumirss.storage import Database
from new2xx_ab import ab_env, seed_entry  # noqa: F401

run = asyncio.run

BLOCKS = [
    SegmentInput(index=0, text="First paragraph body."),
    SegmentInput(index=1, text="Second paragraph body."),
]


def _marker(index: int) -> str:
    return f"<<<BLOCK {index}>>>"


def _echo_provider(calls):
    async def factory(base_url, model):
        calls["n"] += 1

        class FakeProvider:
            async def complete(self, messages):
                markers = re.findall(
                    r"^<<<BLOCK (\d+)>>>", messages[-1]["content"], re.M
                )
                return "\n\n".join(
                    f"{_marker(int(i))}\n译{int(i)}。" for i in markers
                )

        return FakeProvider()

    return factory


@pytest.fixture(autouse=True)
def _allow_fixture_endpoints(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LUMIRSS_FETCH_ALLOW_PRIVATE_HOSTS", "127.0.0.1,ai.local")


def _make_service(tmp_path, calls):
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    settings = AiSettingsStore(db)
    run(settings.save(AiSettingsUpdate(baseUrl="http://127.0.0.1:9/v1", model="m1")))
    service = SegmentTranslationService(
        db=db,
        settings_store=settings,
        provider_factory=_echo_provider(calls),
        secrets=SecretsStore(tmp_path / "secrets.json"),
    )
    return service, db


def test_discard_keeps_ledger_and_machine_text_then_regenerates(tmp_path):
    calls = {"n": 0}
    service, db = _make_service(tmp_path, calls)
    from lumirss.new262_revision_decisions import (
        RevisionDiscardInvalid,
        discard_revision,
        list_decisions,
    )

    run(service.generate("e.f262", BLOCKS))
    run(save_revision(db, "e.f262", 1, "我改过的译文。"))
    assert calls["n"] == 1

    # 无修订段 / 未知段 → 拒绝
    with pytest.raises(RevisionDiscardInvalid):
        run(discard_revision(db, "e.f262", 0))
    with pytest.raises(RevisionDiscardInvalid):
        run(discard_revision(db, "e.f262", 9))

    decision = run(discard_revision(db, "e.f262", 1))
    assert decision.overwritten_text == "我改过的译文。"
    ledger = run(list_decisions(db, "e.f262"))
    assert [d["overwrittenText"] for d in ledger] == ["我改过的译文。"]

    # 放弃时刻的机器原稿也留底（superseded_machine_text）
    assert decision.superseded_machine_text == "译1。"
    assert decision.source_text == BLOCKS[1].text

    # 该段回到真正的未生成态（机器原稿只在台账/历史里可考，不再作为
    # 成功缓存行返回——诚实，绝不让旧机器稿假装仍生效）
    states = run(service.lookup("e.f262", BLOCKS))
    assert states[1].user_revision is None
    assert states[1].status == "not_generated"
    row = run(db.fetch_one(
        "SELECT id FROM ai_translation_segments "
        "WHERE entry_ref = 'e.f262' AND block_index = 1"
    ))
    assert row is None

    # 显式重翻该段：恰好一次 provider 调用，只含块 1；未放弃的段不动
    before = calls["n"]
    regenerated = run(service.generate("e.f262", [BLOCKS[1]]))
    assert calls["n"] == before + 1
    assert regenerated[0].translated_text == "译1。"
    assert regenerated[0].status == "success"


# ---------------------------------------------------------------------------
# API 行为（conftest client 夹具 = 基础模式 TestClient）
# ---------------------------------------------------------------------------


def _seed_segments(tmp_path, entry_key: str, calls: dict | None = None):
    """在当前 client 的 app.state.db 上为 entry 生成两段缓存行，
    并把带 fake provider 的段服务显式注入 app.state（路由级替身）。"""

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
            provider_factory=_echo_provider(calls if calls is not None else {"n": 0}),
            # FIX-386：密钥文件随 per-test tmp_path，禁止固定 /tmp 路径。
            secrets=SecretsStore(tmp_path / f"n262-{entry_key}-secrets.json"),
        )
        await service.generate(encode_entry_ref(f"e1.{entry_key}"), BLOCKS)
        lumi_app.state.segment_translation_service = service

    run(run_seed())


def test_api_discard_regenerates_and_records_ledger(client, tmp_path):
    entry_key = "new262a"
    calls = {"n": 0}
    _seed_segments(tmp_path, entry_key, calls)
    generate_calls_before = calls["n"]
    entry_ref = encode_entry_ref(f"e1.{entry_key}")
    assert client.put(
        f"/api/v1/entries/{entry_ref}/translation/segments/0/revision",
        json={"text": "人工修订零。"},
    ).status_code == 200

    discarded = client.post(
        f"/api/v1/entries/{entry_ref}/translation/segments/0/revision/discard",
        json={"regenerate": True},
    )
    assert discarded.status_code == 200, discarded.text
    body = discarded.json()
    assert body["overwrittenText"] == "人工修订零。"
    assert body["supersededMachineText"] == "译0。"
    assert body["regenerated"]["status"] == "success"
    assert body["regenerated"]["translatedText"] == "译0。"
    assert calls["n"] == generate_calls_before + 1  # 恰好一次 provider 调用

    ledger = client.get(f"/api/v1/entries/{entry_ref}/translation/revision-decisions")
    assert ledger.status_code == 200
    assert [d["overwrittenText"] for d in ledger.json()["decisions"]] == ["人工修订零。"]

    bad_index = client.post(
        f"/api/v1/entries/{entry_ref}/translation/segments/99/revision/discard",
        json={},
    )
    assert bad_index.status_code == 422
    no_revision = client.post(
        f"/api/v1/entries/{entry_ref}/translation/segments/1/revision/discard",
        json={},
    )
    assert no_revision.status_code == 422
    assert no_revision.json()["error"]["type"] == "revision_discard_invalid"


def test_api_discard_without_regenerate_is_zero_provider(client, tmp_path):
    entry_key = "new262b"
    _seed_segments(tmp_path, entry_key)
    entry_ref = encode_entry_ref(f"e1.{entry_key}")
    assert client.put(
        f"/api/v1/entries/{entry_ref}/translation/segments/1/revision",
        json={"text": "修订一。"},
    ).status_code == 200
    discarded = client.post(
        f"/api/v1/entries/{entry_ref}/translation/segments/1/revision/discard",
        json={},
    )
    assert discarded.status_code == 200
    assert discarded.json()["regenerated"] is None
    # 该段回到未生成态（机器原稿只在台账里可考）；修订已撤销
    lookup = client.post(
        f"/api/v1/entries/{entry_ref}/translation/segments/lookup",
        json={"blocks": [{"index": 1, "text": "Second paragraph body."}]},
    )
    segment = lookup.json()["segments"][0]
    assert segment["status"] == "not_generated"
    assert segment["userRevision"] is None
    ledger = client.get(f"/api/v1/entries/{entry_ref}/translation/revision-decisions")
    entry = ledger.json()["decisions"][0]
    assert entry["overwrittenText"] == "修订一。"
    assert entry["supersededMachineText"] == "译1。"


# ---------------------------------------------------------------------------
# A/B 隔离：A 放弃自己的修订不影响 B 的修订
# ---------------------------------------------------------------------------


def test_ab_discard_isolation(ab_env):  # noqa: F811
    env = ab_env
    client = env["client"]
    ref = seed_entry(env, "a", "new262ab", title="隔离文")
    seed_entry(env, "b", "new262ab", title="隔离文")

    # 为两个成员各造缓存行 + 各自修订（服务层直写，RoutingDatabase 按成员分库）
    async def seed_for(who: str):
        from lumirss.main import app as lumi_app
        from lumirss.user_scope import user_context

        with user_context(env[who]["userId"]):
            db = lumi_app.state.db
            await db.migrate()
            settings = AiSettingsStore(db)
            await settings.save(
                AiSettingsUpdate(baseUrl="http://127.0.0.1:9/v1", model="m1")
            )
            service = SegmentTranslationService(
                db=db,
                settings_store=settings,
                provider_factory=_echo_provider({"n": 0}),
                secrets=lumi_app.state.secrets_store,
            )
            blocks = [SegmentInput(index=0, text=ref)]
            await service.generate(encode_entry_ref("e1.new262ab"), blocks)
            await save_revision(db, encode_entry_ref("e1.new262ab"), 0, f"{who} 的修订")

    run(seed_for("a"))
    run(seed_for("b"))

    entry_ref = encode_entry_ref("e1.new262ab")
    # A 放弃自己的修订
    discarded = client.post(
        f"/api/v1/entries/{entry_ref}/translation/segments/0/revision/discard",
        json={},
        headers=env["a"],
    )
    assert discarded.status_code == 200, discarded.text
    assert discarded.json()["overwrittenText"] == "a 的修订"

    # A 的台账有一条；B 的台账为空、修订仍在
    a_ledger = client.get(
        f"/api/v1/entries/{entry_ref}/translation/revision-decisions", headers=env["a"]
    )
    b_ledger = client.get(
        f"/api/v1/entries/{entry_ref}/translation/revision-decisions", headers=env["b"]
    )
    assert len(a_ledger.json()["decisions"]) == 1
    assert b_ledger.json()["decisions"] == []
    b_lookup = client.post(
        f"/api/v1/entries/{entry_ref}/translation/segments/lookup",
        json={"blocks": [{"index": 0, "text": ref}]},
        headers=env["b"],
    )
    assert b_lookup.json()["segments"][0]["userRevision"] == "b 的修订"
