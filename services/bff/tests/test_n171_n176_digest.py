"""N171–N176 —— NR1 日报增强域。

N171 编辑计划（发布日集合 + 周末独立时点 + DST 只生成一次）；
N172 多模型路由（分阶段模型、草稿保留、重试润色、阶段命名错误）；
N173 事实检查视图（句子映射、逐句修订、Atom 同步、待核实标注）；
N174 栏目结构（固定栏目、空栏目策略、数量上限诚实截断）；
N175 阅读时长控制（trim 到预算、素材篮、预览前后对比）；
N176 引用去重（同事件聚合、跨日不合并、数字分歧标注）。
全部走本地假 provider，不触网；调度判定用注入的固定时钟。
"""

import asyncio
import json
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from lumirss.ai_provider import AiTimeout
from lumirss.gpt_digest import (
    DigestPolishFailed,
    GptDigestScheduler,
    generate_issue,
    plan_run,
    retry_polish_issue,
)
from lumirss.gpt_digest_configs import GptDigestConfigStore, parse_days
from lumirss.gpt_digest_issues import GptDigestIssuesStore
from lumirss.main import app


def run(coroutine):
    return asyncio.run(coroutine)


def _config_store():
    return GptDigestConfigStore(app.state.db)


def _issues_store():
    return GptDigestIssuesStore(app.state.db)


def _doc(item_id: str, published: str, title: str | None = None, content: str | None = None) -> dict:
    return {
        "item_id": item_id,
        "entryRef": item_id,
        "feedUrl": "https://tech.example.com/rss",
        "feedTitle": "示例源",
        "title": title or f"文章 {item_id}",
        "url": f"https://tech.example.com/{item_id}",
        "publishedAt": published,
        "read": False,
        "starred": False,
        "contentText": content or f"{item_id} 的正文内容。",
    }


def _fixed_now() -> datetime:
    return datetime(2026, 9, 18, 8, 5, 0, tzinfo=UTC)  # 周五


_DEFAULT_CONFIG = {
    "id": 1,
    "name": "默认日报",
    "enabled": True,
    "hour": 8,
    "timezone": "UTC",
    "windowHours": 24,
    "limitCount": 10,
    "perSourceCap": 0,
    "feedUrlAllow": "",
    "sourceKind": "window",
    "lookbackDays": 7,
    "slots": [],
    "days": [],
    "weekendHours": [],
    "stageModels": {},
    "columns": [],
    "targetReadingMinutes": 0,
    "clusterEnabled": False,
}


def _config(**over) -> dict:
    base = dict(_DEFAULT_CONFIG)
    base.update(over)
    return base


class _FakeAiSettings:
    async def load(self):
        return {"ai.base_url": "https://ai.local", "ai.model": "base-model"}


class _FakeAdapter:
    def __init__(self, docs: list[dict]):
        self._docs = docs

    class _Page:
        def __init__(self, docs):
            self.documents = docs

    async def list_entry_documents(self, limit: int = 120):
        return _FakeAdapter._Page(self._docs)


def _ok_factory(provider, record=None):
    async def factory(base_url: str, model: str, explicit_model: bool = False):
        if record is not None:
            record.append((base_url, model, explicit_model))
        return provider

    return factory


class _StagedProvider:
    """按 system 提示里的阶段标记返回对应输出；fail_stage 时抛错。"""

    def __init__(
        self,
        select_raw: str,
        summarize_raw: str,
        polish_raw: str | None = None,
        fail_stage: str | None = None,
    ):
        self.select_raw = select_raw
        self.summarize_raw = summarize_raw
        self.polish_raw = polish_raw
        self.fail_stage = fail_stage
        self.calls: list[str] = []

    async def complete(self, *, messages):
        system = messages[0]["content"]
        if "（select）" in system:
            self.calls.append("select")
            if self.fail_stage == "select":
                raise AiTimeout("上游超时")
            return self.select_raw
        if "（summarize）" in system:
            self.calls.append("summarize")
            if self.fail_stage == "summarize":
                raise AiTimeout("上游超时")
            return self.summarize_raw
        if "（polish）" in system:
            self.calls.append("polish")
            if self.fail_stage == "polish":
                raise AiTimeout("上游超时")
            assert self.polish_raw is not None
            return self.polish_raw
        raise AssertionError(f"未知阶段提示：{system[:60]}")


def _select_raw(groups: list[list[str]]) -> str:
    return json.dumps(
        {
            "title": "测试日报",
            "assignments": [
                {"heading": f"栏目{i + 1}", "sourceIds": group}
                for i, group in enumerate(groups)
            ],
        },
        ensure_ascii=False,
    )


def _summarize_raw(items: list[dict], title: str = "测试日报") -> str:
    return json.dumps(
        {
            "title": title,
            "sections": [{"heading": s["heading"], "items": s["items"]} for s in items],
            "limitations": [],
        },
        ensure_ascii=False,
    )


def _item(summary: str, sids: list[str]) -> dict:
    return {"summary": summary, "sourceIds": sids, "uncertainty": None}


def _single_raw(items: list[dict], heading: str = "主题", title: str = "测试日报") -> str:
    return _summarize_raw([{"heading": heading, "items": items}], title=title)


# ---- N171 编辑计划 -----------------------------------------------------------


def test_n171_parse_days_accepts_shapes_and_bounds():
    assert parse_days([]) == []
    assert parse_days("[1,3,5]") == [1, 3, 5]
    assert parse_days([6, "2", 2, 9, -1]) == [2, 6]
    assert parse_days("1,3") == [1, 3]
    assert parse_days("nope") == []


def test_n171_weekend_only_config_skips_tuesday():
    """验收：仅周末发布的配置在周二不运行；周六/周日按计划运行。"""
    config = _config(days=[5, 6])
    tuesday = datetime(2026, 9, 15, 8, 30, 0, tzinfo=UTC)  # 周二
    assert tuesday.weekday() == 1
    assert plan_run(config, tuesday) is None
    saturday = datetime(2026, 9, 19, 8, 30, 0, tzinfo=UTC)
    assert saturday.weekday() == 5
    plan = plan_run(config, saturday)
    assert plan is not None and plan.issue_key == "2026-09-19"
    # 空集合 = 每天发布（历史行为）
    assert plan_run(_config(days=[]), tuesday) is not None


def test_n171_weekend_hours_replace_weekday_plan():
    """周末独立时点：周六用 weekendHours（10 点），平日仍用 hour=8。"""
    config = _config(hour=8, weekendHours=[10])
    saturday_1030 = datetime(2026, 9, 19, 10, 30, 0, tzinfo=UTC)
    plan = plan_run(config, saturday_1030)
    assert plan is not None and plan.issue_key == "2026-09-19-10"
    # 周六 08:30 未到周末时点 10 点 → 不运行
    assert plan_run(config, datetime(2026, 9, 19, 8, 30, 0, tzinfo=UTC)) is None
    # 周五 08:30 仍走平日 hour=8
    friday = plan_run(config, _fixed_now())
    assert friday is not None and friday.issue_key == "2026-09-18"


def test_n171_dst_transition_generates_once_with_fixed_clock(client):
    """验收：DST 切换日（美东 2026-11-01 回拨）墙钟 01:00 出现两次，
    同一期号只生成一次；第二次调度命中已有期号跳过。"""
    store_config = run(
        _config_store().update_config(
            1,
            {
                "enabled": True,
                "hour": 8,
                "timezone": "America/New_York",
                "slots": [1],
            },
        )
    )
    ny = ZoneInfo("America/New_York")
    first_one_oclock = datetime(2026, 11, 1, 1, 0, 0, tzinfo=ny)  # EDT（fold=0）
    second_one_oclock = datetime(2026, 11, 1, 1, 0, 0, tzinfo=ny, fold=1)  # EST
    assert (
        second_one_oclock.astimezone(UTC) - first_one_oclock.astimezone(UTC)
    ).total_seconds() == 3600
    generated: list[str] = []

    async def generate_fn(plan):
        generated.append(plan.issue_key)
        await _issues_store().upsert_issue(
            config_id=1,
            issue_key=plan.issue_key,
            title="dst",
            body_html="",
            sections_json="[]",
            refs_json="{}",
            model="m",
            published_at="2026-11-01T06:00:00+00:00",
        )
        return {"issue_key": plan.issue_key}

    issues = _issues_store()
    scheduler = GptDigestScheduler(
        app.state.db, clock=lambda _tz: first_one_oclock
    )
    first = run(scheduler.maybe_generate_config(generate_fn, store_config, issues))
    assert first == {"issue_key": "2026-11-01-01"}
    # 回拨后的第二次墙钟 01:00（EST）：期号相同 → 已存在 → 不再生成
    scheduler2 = GptDigestScheduler(
        app.state.db, clock=lambda _tz: second_one_oclock
    )
    assert (
        run(scheduler2.maybe_generate_config(generate_fn, store_config, issues))
        is None
    )
    assert generated == ["2026-11-01-01"]
    assert len(run(issues.recent_issues(1, 10))) == 1


def test_n171_config_roundtrip_days_and_weekend_hours(client):
    config = run(
        _config_store().update_config(1, {"days": [0, 6], "weekendHours": [9, 21]})
    )
    assert config["days"] == [0, 6]
    assert config["weekendHours"] == [9, 21]
    # 非法值收敛：越界日 / 越界小时被丢弃
    config = run(
        _config_store().update_config(1, {"days": [9, -1, 3], "weekendHours": [99, 5]})
    )
    assert config["days"] == [3]
    assert config["weekendHours"] == [5]
    # 清空 = 回到每天 + 沿用平日计划
    config = run(_config_store().update_config(1, {"days": [], "weekendHours": []}))
    assert config["days"] == [] and config["weekendHours"] == []


# ---- N172 多模型路由 ---------------------------------------------------------


def _polished_raw(sections: list[dict], title: str = "润色后的标题") -> str:
    return json.dumps(
        {"title": title, "sections": sections, "limitations": []},
        ensure_ascii=False,
    )


def _summarize_sections(heading: str = "要点", summary: str = "这是总结。") -> list[dict]:
    return [{"heading": heading, "items": [_item(summary, ["s1"])]}]


async def _generate(config, provider, record=None, draft=True):
    adapter = _FakeAdapter([_doc("a", "2026-09-18T00:10:00+00:00")])
    return await generate_issue(
        _config_store(),
        _issues_store(),
        config=config,
        adapter=adapter,
        ai_settings=_FakeAiSettings(),
        provider_factory=_ok_factory(provider, record),
        db=app.state.db,
        now=_fixed_now(),
        draft=draft,
    )


def test_n172_stage_models_used_per_stage(client):
    """验收：每个阶段用配置的阶段模型调用（fake factory 逐次记录）。"""
    provider = _StagedProvider(
        _select_raw([["s1"]]),
        _summarize_raw(_summarize_sections()),
        _polished_raw([{"heading": "要点", "items": [_item("润色后的总结。", ["s1"])]}]),
    )
    record: list[tuple] = []
    config = _config(
        stageModels={"select": "m-sel", "summarize": "m-sum", "polish": "m-pol"}
    )
    row = run(_generate(config, provider, record))
    assert [model for _url, model, _exp in record] == ["m-sel", "m-sum", "m-pol"]
    assert provider.calls == ["select", "summarize", "polish"]
    assert all(exp for _url, _model, exp in record)  # 显式阶段路由
    meta = json.loads(row["meta_json"])
    assert meta["stageModels"] == {
        "select": "m-sel",
        "summarize": "m-sum",
        "polish": "m-pol",
    }
    assert "polishFailed" not in meta
    # 显式草稿路径：润色后的输出落库
    assert json.loads(row["sections_json"])["title"] == "润色后的标题"


def test_n172_partial_stage_models_fall_back_to_base(client):
    """未配置的阶段回退基础模型（非显式路由——P17 profile 语义保留）。"""
    provider = _StagedProvider(
        _select_raw([["s1"]]),
        _summarize_raw(_summarize_sections()),
        _polished_raw(_summarize_sections()),
    )
    record: list[tuple] = []
    config = _config(stageModels={"polish": "m-pol"})
    run(_generate(config, provider, record))
    assert [(model, exp) for _url, model, exp in record] == [
        ("base-model", False),
        ("base-model", False),
        ("m-pol", True),
    ]


def test_n172_no_stage_models_single_call_unchanged(client):
    """未配置分阶段模型 = 单次调用（历史行为）；meta 为空对象。"""

    class _SingleProvider:
        def __init__(self, raw):
            self.raw = raw
            self.calls = 0

        async def complete(self, *, messages):
            self.calls += 1
            assert "阶段" not in messages[0]["content"]
            return self.raw

    single = _SingleProvider(_single_raw([_item("总结。", ["s1"])]))
    record: list[tuple] = []
    row = run(_generate(_config(), single, record))
    assert single.calls == 1
    assert record == [("https://ai.local", "base-model", False)]
    assert json.loads(row["meta_json"]) == {}


def test_n172_polish_failure_keeps_draft_and_retry_polish(client):
    """验收：润色失败 → 选材+总结草稿保留（polishFailed 如实标注），
    retry-polish 仅补润色成功。"""
    provider = _StagedProvider(
        _select_raw([["s1"]]),
        _summarize_raw(_summarize_sections(summary="选材总结成果。"), title="草稿标题"),
        fail_stage="polish",
    )
    config = _config(
        stageModels={"select": "m-sel", "summarize": "m-sum", "polish": "m-pol"}
    )
    issues = _issues_store()
    with pytest.raises(DigestPolishFailed) as excinfo:
        run(_generate(config, provider))
    assert "润色阶段（polish）" in str(excinfo.value)
    row = run(issues.get_issue(1, "2026-09-18"))
    assert row is not None and row["status"] == "draft"
    stored = json.loads(row["sections_json"])
    assert stored["title"] == "草稿标题"  # 选材+总结成果保留
    meta = json.loads(row["meta_json"])
    assert meta["polishFailed"] is True
    last_error = run(_config_store().get_config(1))["lastError"] or ""
    assert "润色阶段（polish）" in last_error

    # retry-polish：仅润色——好的 provider 只被 ask polish
    good = _StagedProvider(
        _select_raw([["s1"]]),
        _summarize_raw(_summarize_sections()),
        _polished_raw([{"heading": "要点", "items": [_item("重试润色后的总结。", ["s1"])]}]),
    )
    fixed = run(
        retry_polish_issue(
            issues,
            _config_store(),
            config_id=1,
            issue_key="2026-09-18",
            config=config,
            ai_settings=_FakeAiSettings(),
            provider_factory=_ok_factory(good),
        )
    )
    assert good.calls == ["polish"]  # 只补润色，不重跑选材/总结
    assert fixed["status"] == "draft"  # 状态不变
    assert json.loads(fixed["sections_json"])["title"] == "润色后的标题"
    meta = json.loads(fixed["meta_json"])
    assert "polishFailed" not in meta
    assert meta["stageModels"]["polish"] == "m-pol"
    assert meta["polishedAt"]
    assert fixed["model"] == "m-pol"


def test_n172_select_failure_aborts_cleanly(client):
    """验收：选材失败 → 带阶段名的干净中止，不产生任何期号。"""
    provider = _StagedProvider(
        _select_raw([["s1"]]),
        _summarize_raw(_summarize_sections()),
        fail_stage="select",
    )
    config = _config(stageModels={"select": "m-sel"})
    with pytest.raises(AiTimeout) as excinfo:
        run(_generate(config, provider))
    assert "选材阶段（select）" in str(excinfo.value)
    assert provider.calls == ["select"]  # 失败后不再调用后续阶段
    assert run(_issues_store().recent_issues(1, 10)) == []
    last_error = run(_config_store().get_config(1))["lastError"] or ""
    assert "选材阶段（select）" in last_error


def test_n172_summarize_failure_names_stage(client):
    """总结失败同样带阶段名，且不落任何期号。"""
    provider = _StagedProvider(
        _select_raw([["s1"]]),
        _summarize_raw(_summarize_sections()),
        fail_stage="summarize",
    )
    config = _config(stageModels={"summarize": "m-sum"})
    with pytest.raises(AiTimeout) as excinfo:
        run(_generate(config, provider))
    assert "总结阶段（summarize）" in str(excinfo.value)
    assert run(_issues_store().recent_issues(1, 10)) == []


def test_n172_retry_polish_endpoint(client, monkeypatch):
    """路由面：retry-polish 成功 200；期号不存在 422 no_material。"""
    issues = _issues_store()
    run(
        issues.upsert_issue(
            config_id=1,
            issue_key="2026-09-18",
            title="草稿",
            body_html="<p>x</p>",
            sections_json=json.dumps(
                {
                    "title": "草稿",
                    "sections": [{"heading": "要点", "items": [_item("原文。", ["s1"])]}],
                    "limitations": [],
                },
                ensure_ascii=False,
            ),
            refs_json='{"s1": {"title": "T", "url": "https://a.example.com/x", "feedTitle": "F", "publishedAt": "2026-09-18T00:00:00+00:00"}}',
            model="m",
            published_at="2026-09-18T00:00:00+00:00",
            status_for_new="draft",
            meta_json=json.dumps({"polishFailed": True}, ensure_ascii=False),
        )
    )
    good = _StagedProvider(
        _select_raw([["s1"]]),
        _summarize_raw(_summarize_sections()),
        _polished_raw([{"heading": "要点", "items": [_item("润色文。", ["s1"])]}]),
    )

    def _fake_ai_deps(_state):
        return _FakeAiSettings(), _ok_factory(good)

    monkeypatch.setattr("lumirss.gpt_digest._build_ai_deps", _fake_ai_deps)
    ok = client.post("/api/v1/gpt-digest/configs/1/issues/2026-09-18/retry-polish")
    assert ok.status_code == 200, ok.text
    body = ok.json()["issue"]
    assert body["meta"]["stageModels"]["polish"] == "base-model"
    assert "polishFailed" not in body["meta"]

    missing = client.post("/api/v1/gpt-digest/configs/1/issues/1999-01-01/retry-polish")
    assert missing.status_code == 422
    assert missing.json()["error"]["type"] == "no_material"


def test_n172_stage_models_config_roundtrip_and_bounds(client):
    config = run(
        _config_store().update_config(
            1, {"stageModels": {"select": " sel-model ", "bogus": "x", "polish": ""}}
        )
    )
    assert config["stageModels"] == {"select": "sel-model"}
    config = run(_config_store().update_config(1, {"stageModels": {}}))
    assert config["stageModels"] == {}
    config = run(_config_store().update_config(1, {"stageModels": "not-json"}))
    assert config["stageModels"] == {}
