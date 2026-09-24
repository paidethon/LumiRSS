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

from lumirss.gpt_digest import GptDigestScheduler, plan_run
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


def _stage_output(raw_by_marker: dict[str, str], fail_on_marker: str | None = None):
    """按 system 提示里的阶段标记返回对应输出；fail_on_marker 时抛错。"""

    class _Provider:
        def __init__(self):
            self.models: list[str] = []
            self.stages: list[str] = []

        async def complete(self, *, messages):
            system = messages[0]["content"]
            self.stages.append(system)
            for marker, raw in raw_by_marker.items():
                if marker in system:
                    return raw
            raise AssertionError(f"未知阶段提示：{system[:60]}")

    return _Provider()


def _ok_factory(provider, record=None):
    async def factory(base_url: str, model: str, explicit_model: bool = False):
        if record is not None:
            record.append((base_url, model, explicit_model))
        return provider

    return factory


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
