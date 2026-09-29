"""NEW-270 翻译完整性报告 — 逐段完成/缺失/无法翻译台账 + 显式补译。

- 分类：translated（缓存成功或人工修订）/ failed / missing /
  skipped（N086 不翻译标记）；
- fill 只发 missing+failed 段（已有结果零 provider 调用）；
- 快照历史 cap=20；A/B 隔离。
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
from lumirss.entry_no_translate import mark_block
from lumirss.entryref import encode_entry_ref
from lumirss.new270_completeness_reports import (
    REPORT_CAP,
    CompletenessInvalid,
    build_report,
    fill_missing,
    list_reports,
    save_report,
)
from lumirss.secrets_store import SecretsStore
from lumirss.storage import Database
from new2xx_ab import ab_env, seed_entry  # noqa: F401

run = asyncio.run


@pytest.fixture(autouse=True)
def _allow_fixture_endpoints(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LUMIRSS_FETCH_ALLOW_PRIVATE_HOSTS", "127.0.0.1,ai.local")


def _echo_provider(calls):
    """含 FAIL 的批次第一次调用瞬时失败（之后恢复）—— 建模真实瞬时故障。"""
    state = {"failed_once": False}

    async def factory(base_url, model):
        calls["n"] += 1

        class FakeProvider:
            async def complete(self, messages):
                user = messages[-1]["content"]
                markers = re.findall(r"^<<<BLOCK (\d+)>>>", user, re.M)
                if "FAIL" in user and not state["failed_once"]:
                    state["failed_once"] = True
                    from lumirss.ai_provider import AiUpstreamError

                    raise AiUpstreamError("transient provider outage")
                return "\n\n".join(
                    f"<<<BLOCK {int(i)}>>>\n译{int(i)}。" for i in markers
                )

        return FakeProvider()

    return factory


def _make(tmp_path, calls):
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


BLOCKS = [
    SegmentInput(index=0, text="Block zero."),
    SegmentInput(index=1, text="Block one. FAIL"),
    SegmentInput(index=2, text="Block two."),
    SegmentInput(index=3, text="Block three."),
    SegmentInput(index=4, text="Block four."),
]


def _seed(service, ref, db):
    """逐块生成但跳过块 3（保持 missing）；块 1 首次失败留 failed 行；
    块 4 标不翻译；块 2 挂人工终稿。"""
    for block in BLOCKS:
        if block.index == 3:
            continue
        run(service.generate(ref, [block]))
    run(mark_block(db, ref, 4))
    run(save_revision(db, ref, 2, "人工版"))


def test_classify_and_report(tmp_path):
    calls = {"n": 0}
    service, db = _make(tmp_path, calls)
    ref = encode_entry_ref("e1.n270a")
    _seed(service, ref, db)

    counts = run(build_report(db, service, ref, BLOCKS))
    assert counts["total"] == 5
    assert counts["translated"] == [0, 2]  # 缓存成功 + 人工终稿
    assert counts["failed"] == [1]
    assert counts["missing"] == [3]
    assert counts["skipped"] == [4]

    report = run(save_report(db, ref, counts))
    assert report["translated"] == 2 and report["filled"] == 0
    assert report["missingIndexes"] == [3]

    with pytest.raises(CompletenessInvalid):
        run(build_report(db, service, ref, []))


def test_fill_only_missing_and_failed(tmp_path):
    calls = {"n": 0}
    service, db = _make(tmp_path, calls)
    ref = encode_entry_ref("e1.n270b")
    _seed(service, ref, db)
    before_calls = calls["n"]  # 4 次逐块生成

    report = run(fill_missing(db, service, ref, BLOCKS))
    assert report["missing"] == 0 and report["failed"] == 0
    assert report["translatedIndexes"] == [0, 1, 2, 3]
    assert report["filled"] == 2  # 之前 missing(3) + failed(1) 都补成功
    assert report["skippedIndexes"] == [4]  # 有意保留原文的块不动
    assert calls["n"] == before_calls + 1  # 缺失+失败一次批量；其余零调用

    # 再补一次：全部已完整 → filled=0 且零 provider 调用
    again = run(fill_missing(db, service, ref, BLOCKS))
    assert again["filled"] == 0
    assert calls["n"] == before_calls + 1


def test_report_history_cap(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    ref = encode_entry_ref("e1.n270c")
    counts = {
        "total": 2,
        "translated": [0],
        "failed": [],
        "missing": [1],
        "skipped": [],
    }
    for _ in range(REPORT_CAP + 3):
        run(save_report(db, ref, counts))
    rows = run(db.fetch_all(
        "SELECT id FROM translation_completeness_reports WHERE entry_ref = ?", (ref,)
    ))
    assert len(rows) == REPORT_CAP
    assert len(run(list_reports(db, ref))) == REPORT_CAP


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
        for block in BLOCKS:
            if block.index == 3:
                continue  # 保持 missing
            await service.generate(ref, [block])
        await mark_block(db, ref, 4)
        await save_revision(db, ref, 2, "人工版")
        lumi_app.state.segment_translation_service = service

    run(run_seed())
    return ref


def test_api_completeness_roundtrip(client, tmp_path):
    calls = {"n": 0}
    ref = _seed_api(client, tmp_path, "n270api", calls)
    before = calls["n"]
    body = {"blocks": [ {"index": b.index, "text": b.text} for b in BLOCKS ]}

    made = client.post(
        f"/api/v1/entries/{ref}/translation/completeness/report", json=body
    )
    assert made.status_code == 200, made.text
    first = made.json()
    assert first["translatedIndexes"] == [0, 2]
    assert first["failedIndexes"] == [1]
    assert first["missingIndexes"] == [3]
    assert first["skippedIndexes"] == [4]

    filled = client.post(
        f"/api/v1/entries/{ref}/translation/completeness/fill", json=body
    )
    assert filled.status_code == 200, filled.text
    second = filled.json()
    assert second["filled"] == 2
    assert second["missingIndexes"] == [] and second["failedIndexes"] == []
    assert calls["n"] == before + 1  # 只补 missing+failed

    history = client.get(
        f"/api/v1/entries/{ref}/translation/completeness/reports"
    ).json()["reports"]
    assert [r["id"] for r in history] == [second["id"], first["id"]]

    bad = client.post(
        f"/api/v1/entries/{ref}/translation/completeness/report", json={"blocks": []}
    )
    assert bad.status_code == 422


# ---------------------------------------------------------------------------
# A/B 隔离
# ---------------------------------------------------------------------------


def test_ab_completeness_reports_isolated(ab_env):  # noqa: F811
    env = ab_env
    client = env["client"]
    ref = encode_entry_ref("e1.new270ab")
    seed_entry(env, "a", "new270ab")
    seed_entry(env, "b", "new270ab")
    body = {"blocks": [{"index": 0, "text": "Shared block."}]}

    made_a = client.post(
        f"/api/v1/entries/{ref}/translation/completeness/report",
        json=body,
        headers=env["a"],
    )
    assert made_a.status_code == 200, made_a.text

    a_history = client.get(
        f"/api/v1/entries/{ref}/translation/completeness/reports", headers=env["a"]
    ).json()["reports"]
    b_history = client.get(
        f"/api/v1/entries/{ref}/translation/completeness/reports", headers=env["b"]
    ).json()["reports"]
    assert len(a_history) == 1
    assert b_history == []  # bob 看不到 alice 的完整性台账
