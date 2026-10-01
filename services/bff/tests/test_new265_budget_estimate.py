"""NEW-265 翻译任务预算预估 — 提交前字数统计与基于登记单价的费用估计。

- 预检零 provider 调用、零缓存写入；
- 缓存命中 / N086 标记 / F062 修订段不计入待翻量（已有结果不重复收费）；
- 未登记单价 → estimatedCost=null + 诚实说明（不臆造默认价）；
- browser 引擎 → 诚实不可用；A/B 隔离：alice 的单价对 bob 不可见。
"""

import asyncio
import re

import pytest

from lumirss.ai_settings import (
    TRANSLATION_ENGINE_BROWSER,
    AiSettingsStore,
    AiSettingsUpdate,
)
from lumirss.ai_translation_segments import (
    SegmentInput,
    SegmentTranslationService,
)
from lumirss.entry_no_translate import mark_block
from lumirss.entryref import encode_entry_ref
from lumirss.new265_budget_estimate import (
    BudgetEngineUnavailable,
    BudgetInvalid,
    estimate,
    get_budget_settings,
    save_budget_settings,
)
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


def _make(tmp_path, calls, engine="ai"):
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    settings = AiSettingsStore(db)
    run(
        settings.save(
            AiSettingsUpdate(
                baseUrl="http://127.0.0.1:9/v1",
                model="m1",
                translationEngine=engine,
            )
        )
    )
    service = SegmentTranslationService(
        db=db,
        settings_store=settings,
        provider_factory=_echo_provider(calls),
    )
    return service, db, settings


def test_budget_settings_roundtrip_and_validation(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())

    row = run(get_budget_settings(db))
    assert row.price_per_1k_chars is None and row.currency == ""

    saved = run(save_budget_settings(db, 0.02, "USD"))
    assert saved.price_per_1k_chars == 0.02 and saved.currency == "USD"
    assert run(get_budget_settings(db)).price_per_1k_chars == 0.02

    # price=None 显式清除（回到诚实不可用态）
    cleared = run(save_budget_settings(db, None))
    assert cleared.price_per_1k_chars is None

    with pytest.raises(BudgetInvalid):
        run(save_budget_settings(db, 0.0))
    with pytest.raises(BudgetInvalid):
        run(save_budget_settings(db, -1.5))


def test_estimate_counts_and_excludes_already_done(tmp_path):
    calls = {"n": 0}
    service, db, settings = _make(tmp_path, calls)
    ref = encode_entry_ref("e1.n265a")
    blocks = [
        SegmentInput(index=0, text="First paragraph."),
        SegmentInput(index=1, text="Second paragraph."),
        SegmentInput(index=2, text="Third paragraph."),
    ]
    run(service.generate(ref, blocks[:2]))  # 只翻前两段

    live = run(service._resolve_settings())
    # 未登记单价：字数照实统计，费用诚实为 null
    plain = run(estimate(db, live, blocks, ref))
    assert plain.total_blocks == 3 and plain.total_chars > 0
    assert plain.cached_blocks == 2
    assert plain.chargeable_blocks == 1
    assert plain.chargeable_chars == len("Third paragraph.")
    assert plain.estimated_cost is None
    assert "未登记" in plain.note

    # 登记单价后：估算 = 待翻字符/1000 × 单价（round 2 位）
    run(save_budget_settings(db, 0.5, "USD"))
    priced = run(estimate(db, live, blocks, ref))
    assert priced.estimated_cost == round(priced.chargeable_chars / 1000 * 0.5, 2)
    assert priced.currency == "USD"

    # 全部命中后：零新增，明确说明
    run(service.generate(ref, blocks))
    done = run(estimate(db, live, blocks, ref))
    assert done.chargeable_blocks == 0
    assert done.estimated_cost == 0.0
    assert calls["n"] == 2  # 预检绝不追加 provider 调用


def test_estimate_excludes_no_translate_and_revised(tmp_path):
    service, db, _settings = _make(tmp_path, {"n": 0})
    ref = encode_entry_ref("e1.n265b")
    blocks = [
        SegmentInput(index=0, text="Alpha block."),
        SegmentInput(index=1, text="Beta block."),
        SegmentInput(index=2, text="Gamma block."),
    ]
    run(service.generate(ref, [blocks[2]]))  # 段 2 有缓存行才能挂修订
    from lumirss.ai_translation_revisions import save_revision

    run(save_revision(db, ref, 2, "人工版"))
    run(mark_block(db, ref, 1))
    live = run(service._resolve_settings())
    item = run(estimate(db, live, blocks, ref))
    assert item.no_translate_blocks == 1
    assert item.revised_blocks == 1
    assert item.chargeable_blocks == 1
    assert item.chargeable_chars == len("Alpha block.")


def test_estimate_browser_engine_honest_unavailable(tmp_path):
    service, db, _settings = _make(tmp_path, {"n": 0}, engine=TRANSLATION_ENGINE_BROWSER)
    live = run(service._resolve_settings())
    with pytest.raises(BudgetEngineUnavailable):
        run(estimate(db, live, [SegmentInput(index=0, text="Hi.")]))


# ---------------------------------------------------------------------------
# API 行为
# ---------------------------------------------------------------------------


def test_api_budget_roundtrip(client, tmp_path):
    made = client.put(
        "/api/v1/translation/budget/settings",
        json={"pricePer1kChars": 0.01, "currency": "CNY"},
    )
    assert made.status_code == 200, made.text
    got = client.get("/api/v1/translation/budget/settings").json()
    assert got["pricePer1kChars"] == 0.01 and got["currency"] == "CNY"

    bad = client.put(
        "/api/v1/translation/budget/settings", json={"pricePer1kChars": 0}
    )
    assert bad.status_code == 422

    cleared = client.put(
        "/api/v1/translation/budget/settings", json={"pricePer1kChars": None}
    )
    assert cleared.status_code == 200
    assert cleared.json()["pricePer1kChars"] is None


def test_api_budget_estimate_preflight(client, tmp_path):
    calls = {"n": 0}
    ref = encode_entry_ref("e1.n265api")

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
        )
        await service.generate(ref, [SegmentInput(index=0, text="Cached one.")])
        lumi_app.state.segment_translation_service = service

    run(run_seed())

    body = {
        "entryRef": ref,
        "blocks": [
            {"index": 0, "text": "Cached one."},
            {"index": 1, "text": "Fresh text."},
        ],
    }
    made = client.post("/api/v1/translation/budget/estimate", json=body)
    assert made.status_code == 200, made.text
    view = made.json()
    assert view["cachedBlocks"] == 1
    assert view["chargeableBlocks"] == 1
    assert view["estimatedCost"] is None  # 未登记单价 → 诚实为 null

    assert client.put(
        "/api/v1/translation/budget/settings",
        json={"pricePer1kChars": 1.0, "currency": "CNY"},
    ).status_code == 200
    priced = client.post("/api/v1/translation/budget/estimate", json=body).json()
    assert priced["estimatedCost"] == round(len("Fresh text.") / 1000 * 1.0, 2)
    assert priced["chargeableChars"] == len("Fresh text.")
    assert calls["n"] == 1  # 预检零 provider 调用

    malformed = client.post(
        "/api/v1/translation/budget/estimate",
        json={"entryRef": "not-a-ref", "blocks": [{"index": 0, "text": "x"}]},
    )
    assert malformed.status_code == 400


# ---------------------------------------------------------------------------
# A/B 隔离
# ---------------------------------------------------------------------------


def test_ab_budget_settings_isolated(ab_env):  # noqa: F811
    env = ab_env
    client = env["client"]
    assert (
        client.put(
            "/api/v1/translation/budget/settings",
            json={"pricePer1kChars": 9.99, "currency": "USD"},
            headers=env["a"],
        ).status_code
        == 200
    )

    a_view = client.get("/api/v1/translation/budget/settings", headers=env["a"])
    b_view = client.get("/api/v1/translation/budget/settings", headers=env["b"])
    assert a_view.json()["pricePer1kChars"] == 9.99
    assert b_view.json()["pricePer1kChars"] is None  # bob 看不到 alice 的单价
    assert b_view.json()["currency"] == ""
