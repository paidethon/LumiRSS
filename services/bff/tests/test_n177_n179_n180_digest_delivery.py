"""N177 可见订正标记 + N179 缺刊处理策略 + N180 日报材料使用追踪。

N177：修订（updated_at > published_at）→ HTML 与 Atom 顶端出现
「【已订正 …】」块；未修订 → 绝不出现。
N179：missed_issue_policy（backfill/merge_into_next/skip）三条路径
（固定时钟）+ 幂等双跑 + skip 记录（cap 30）。
N180：refs_json 反向索引 → 条目的期刊/栏目/引用锚点；跨用户（库）
诚实为空。
"""

import asyncio
import json
from datetime import UTC, datetime

import pytest

from lumirss.gpt_digest import (
    GptDigestScheduler,
    capture_missed_window_into_pool,
    is_revised_issue,
    plan_missed,
    revision_banner_html,
)
from lumirss.gpt_digest_configs import (
    GptDigestConfigStore,
    append_skip_log,
    parse_missed_issue_policy,
)
from lumirss.gpt_digest_issues import GptDigestIssuesStore, digest_usage_for_entry
from lumirss.gpt_digest_pool import DigestMaterialPoolStore
from lumirss.main import app
from lumirss.storage import Database


def run(coroutine):
    return asyncio.run(coroutine)


# ---- N177 可见订正标记 --------------------------------------------------------


def test_revision_marker_pure_helpers():
    assert is_revised_issue("2026-09-18T09:00:00+00:00", "2026-09-18T08:00:00+00:00")
    assert not is_revised_issue("2026-09-18T08:00:00+00:00", "2026-09-18T08:00:00+00:00")
    assert not is_revised_issue(None, "2026-09-18T08:00:00+00:00")
    assert not is_revised_issue("垃圾", "2026-09-18T08:00:00+00:00")

    banner = revision_banner_html("更正第二段", "2026-09-18T09:00:00+00:00", "2026-09-18T08:00:00+00:00")
    assert "已订正" in banner and "更正第二段" in banner
    assert banner.startswith('<div class="lumi-digest-revision"')
    # note 里的 HTML 被转义
    unsafe = revision_banner_html("<b>x</b>", "2026-09-18T09:00:00+00:00", "2026-09-18T08:00:00+00:00")
    assert "<b>" not in unsafe and "&lt;b&gt;" in unsafe
    assert revision_banner_html("n", "2026-09-18T08:00:00+00:00", "2026-09-18T08:00:00+00:00") == ""


def test_revision_marker_flows_into_atom(client):
    issues = GptDigestIssuesStore(app.state.db)
    row = run(
        issues.upsert_issue(
            config_id=1,
            issue_key="2026-09-18",
            title="日报",
            body_html="<p>正文</p>",
            sections_json="[]",
            refs_json="{}",
            model="m",
            published_at="2026-09-18T08:00:00+00:00",
        )
    )
    assert row["updated_at"] == row["published_at"]
    # 未修订：DTO 无订正标记
    dto = issues.issue_to_dto(run(issues.get_issue(1, "2026-09-18")))
    assert dto["revised"] is False
    assert dto["note"] == ""

    revised = run(
        issues.revise_issue(
            config_id=1,
            issue_key="2026-09-18",
            title="日报（改）",
            body_html="<p>改正文</p>",
            sections=[],
            note="更正一处数字",
            updated_at="2026-09-18T09:30:00+00:00",
        )
    )
    assert revised is not None
    dto = issues.issue_to_dto(revised)
    assert dto["revised"] is True
    assert dto["note"] == "更正一处数字"

    # Atom：顶端出现订正块（Web 与 Atom 同一判定口径）
    token = client.get("/api/v1/gpt-digest/feed").json().get("atomPath")
    token = token.split("/")[-1][: -len(".atom")] if token else None
    if token is None:
        pytest.skip("feed token 只展示一次（哈希存储）——旧测试已消费")
    atom = client.get(f"/feeds/gpt-digest/{token}.atom")
    assert atom.status_code == 200
    assert "lumi-digest-revision" in atom.text
    assert "已订正" in atom.text and "更正一处数字" in atom.text


# ---- N179 缺刊处理策略 --------------------------------------------------------


def _slots_config(policy: str, **over) -> dict:
    base = {
        "id": 7,
        "name": "策略日报",
        "enabled": True,
        "hour": 8,
        "timezone": "UTC",
        "windowHours": 24,
        "limitCount": 10,
        "perSourceCap": 0,
        "feedUrlAllow": "",
        "sourceKind": "window",
        "lookbackDays": 0,
        "slots": [8, 20],
        "days": [],
        "weekendHours": [],
        "stageModels": {},
        "columns": [],
        "targetReadingMinutes": 0,
        "clusterEnabled": False,
        "missedIssuePolicy": policy,
        "skipLog": [],
    }
    base.update(over)
    return base


def _nine_thirty() -> datetime:
    return datetime(2026, 9, 18, 9, 30, 0, tzinfo=UTC)


def test_policy_parse_and_skip_log_helpers():
    assert parse_missed_issue_policy(None) == "backfill"
    assert parse_missed_issue_policy("nonsense") == "backfill"
    assert parse_missed_issue_policy("merge_into_next") == "merge_into_next"
    log = []
    log = append_skip_log(log, "2026-09-18-08", "policy_skip")
    log = append_skip_log(log, "2026-09-18-08", "policy_skip")  # 幂等
    assert log == [{"date": "2026-09-18-08", "reason": "policy_skip"}]
    for index in range(40):
        log = append_skip_log(log, f"2026-09-{index:02d}-08", "policy_skip")
    assert len(log) == 30  # cap 30，最旧先裁


def test_plan_missed_detects_beyond_catchup():
    # slots [8, 20]；09:30 距 08:00 已超 65 分钟 → 缺刊目标 = 2026-09-18-08
    plan = plan_missed(_slots_config("backfill"), _nine_thirty())
    assert plan is not None
    assert plan.issue_key == "2026-09-18-08"
    assert plan.window_end.startswith("2026-09-18T08:00:00")
    # 仍在补刊窗口内（08:50）→ 不算缺刊（plan_run 的领地）
    within = plan_missed(
        _slots_config("backfill"),
        datetime(2026, 9, 18, 8, 50, 0, tzinfo=UTC),
    )
    assert within is None


def test_scheduler_backfill_generates_missed_issue(client):
    issues = GptDigestIssuesStore(app.state.db)
    generated = []

    async def generate_fn(plan):
        generated.append(plan.issue_key)
        return await issues.upsert_issue(
            config_id=7,
            issue_key=plan.issue_key,
            title="补刊",
            body_html="<p>x</p>",
            sections_json="[]",
            refs_json="{}",
            model="m",
            published_at="2026-09-18T09:30:00+00:00",
        )

    scheduler = GptDigestScheduler(app.state.db)
    config = _slots_config("backfill")
    row = run(scheduler.maybe_generate_config(generate_fn, config, issues, now=_nine_thirty()))
    assert row is not None and generated == ["2026-09-18-08"]
    # 幂等双跑：期号已存在 → 绝不重写
    again = run(scheduler.maybe_generate_config(generate_fn, config, issues, now=_nine_thirty()))
    assert again is None and generated == ["2026-09-18-08"]


def test_scheduler_skip_records_policy_skip(client):
    issues = GptDigestIssuesStore(app.state.db)
    configs = GptDigestConfigStore(app.state.db)
    created = run(configs.create_config({"name": "跳过刊", "slots": [8, 20], "missedIssuePolicy": "skip"}))
    config = _slots_config("skip", id=created["id"])
    generated = []

    async def generate_fn(plan):
        generated.append(plan.issue_key)
        raise AssertionError("skip 策略不应触发生成")

    scheduler = GptDigestScheduler(app.state.db)
    assert run(scheduler.maybe_generate_config(generate_fn, config, issues, now=_nine_thirty())) is None
    assert generated == []
    stored = run(configs.get_config(created["id"]))
    assert stored["skipLog"] == [{"date": "2026-09-18-08", "reason": "policy_skip"}]
    # 幂等双跑：记录不重复
    run(scheduler.maybe_generate_config(generate_fn, config, issues, now=_nine_thirty()))
    assert len(run(configs.get_config(created["id"]))["skipLog"]) == 1


def test_scheduler_merge_into_next_pools_material(client):
    issues = GptDigestIssuesStore(app.state.db)
    configs = GptDigestConfigStore(app.state.db)
    pool = DigestMaterialPoolStore(app.state.db)
    created = run(
        configs.create_config({"name": "并入刊", "slots": [8, 20], "missedIssuePolicy": "merge_into_next"})
    )
    config = _slots_config("merge_into_next", id=created["id"])
    generated = []
    pooled = []

    async def generate_fn(plan):
        generated.append(plan.issue_key)
        raise AssertionError("merge 策略不应触发生成")

    async def merge_fn(plan):
        pooled.append(plan.issue_key)
        return await capture_missed_window_into_pool(
            _MergeAdapter(), pool, created["id"], plan
        )

    scheduler = GptDigestScheduler(app.state.db)
    assert run(scheduler.maybe_generate_config(generate_fn, config, issues, now=_nine_thirty(), merge_fn=merge_fn)) is None
    assert generated == [] and pooled == ["2026-09-18-08"]
    pending = [e for e in run(pool.list_entries(created["id"])) if e["usedIssueKey"] is None]
    assert [e["entryRef"] for e in pending] == ["e1.a", "e1.b"]
    # 幂等双跑：同一缺刊只并入一次
    run(scheduler.maybe_generate_config(generate_fn, config, issues, now=_nine_thirty(), merge_fn=merge_fn))
    pending = [e for e in run(pool.list_entries(created["id"])) if e["usedIssueKey"] is None]
    assert len(pending) == 2
    stored = run(configs.get_config(created["id"]))
    assert {"date": "2026-09-18-08", "reason": "merged_into_next"} in stored["skipLog"]


class _MergeAdapter:
    class _Page:
        documents = [
            {
                "item_id": "a",
                "entryRef": "e1.a",
                "feedUrl": "https://x.example.com/rss",
                "feedTitle": "X",
                "title": "A",
                "url": "https://x.example.com/a",
                "publishedAt": "2026-09-18T07:00:00Z",
                "read": False,
                "starred": False,
                "contentText": "a",
            },
            {
                "item_id": "b",
                "entryRef": "e1.b",
                "feedUrl": "https://x.example.com/rss",
                "feedTitle": "X",
                "title": "B",
                "url": "https://x.example.com/b",
                "publishedAt": "2026-09-18T03:00:00Z",
                "read": False,
                "starred": False,
                "contentText": "b",
            },
            {
                "item_id": "c",
                "entryRef": "e1.c",
                "feedUrl": "https://x.example.com/rss",
                "feedTitle": "X",
                "title": "C",
                "url": "https://x.example.com/c",
                "publishedAt": "2026-09-18T09:00:00Z",  # 窗口外（>08:00 边界）
                "read": False,
                "starred": False,
                "contentText": "c",
            },
        ]

    async def list_entry_documents(self, limit: int = 120):
        return _MergeAdapter._Page()


def test_skip_log_cap_in_config_store(client):
    configs = GptDigestConfigStore(app.state.db)
    created = run(configs.create_config({"name": "cap 日志", "missedIssuePolicy": "skip"}))
    for index in range(35):
        run(configs.append_config_skip_log(created["id"], f"2026-01-{index:02d}", "policy_skip"))
    stored = run(configs.get_config(created["id"]))
    assert len(stored["skipLog"]) == 30


# ---- N180 日报材料使用追踪 ----------------------------------------------------


def test_digest_usage_reverse_lookup(client):
    db = app.state.db
    issues = GptDigestIssuesStore(db)
    configs = GptDigestConfigStore(db)
    created = run(configs.create_config({"name": "使用追踪日报"}))
    ref = "e1.MDAwNjU5ZTA3YWFlZTI0ZA"
    refs = {
        "s1": {"title": "甲", "url": "https://a.example.com/1", "feedTitle": "A", "publishedAt": "2026-09-18T01:00:00Z", "ref": ref},
        "s2": {"title": "乙", "url": "https://a.example.com/2", "feedTitle": "A", "publishedAt": "2026-09-18T02:00:00Z", "ref": "e1.other"},
    }
    sections = [
        {"heading": "头条", "items": [{"summary": "……", "sourceIds": ["s2"], "uncertainty": None}]},
        {"heading": "纵深", "items": [{"summary": "……", "sourceIds": ["s1"], "uncertainty": None}]},
    ]
    run(
        issues.upsert_issue(
            config_id=created["id"],
            issue_key="2026-09-18",
            title="日报",
            body_html="<p>x</p>",
            sections_json=json.dumps(sections, ensure_ascii=False),
            refs_json=json.dumps(refs, ensure_ascii=False),
            model="m",
            published_at="2026-09-18T08:00:00+00:00",
        )
    )
    usage = run(digest_usage_for_entry(db, ref))
    assert len(usage) == 1
    item = usage[0]
    assert item["configName"] == "使用追踪日报"
    assert item["issueKey"] == "2026-09-18"
    assert item["issueDate"] == "2026-09-18"
    assert item["section"] == "纵深"
    assert item["sourceId"] == "s1"
    assert item["citationAnchor"] == "2026-09-18:s1"
    # rss: 前缀归一
    assert run(digest_usage_for_entry(db, f"rss:{ref}")) == usage
    # 旧期号（refs 无 ref 键）→ 诚实空
    old_refs = {"s1": {"title": "旧", "url": "", "feedTitle": "", "publishedAt": ""}}
    run(
        issues.upsert_issue(
            config_id=created["id"],
            issue_key="2026-09-17",
            title="旧",
            body_html="<p>x</p>",
            sections_json="[]",
            refs_json=json.dumps(old_refs),
            model="m",
            published_at="2026-09-17T08:00:00+00:00",
        )
    )
    assert all(u["issueKey"] != "2026-09-17" for u in run(digest_usage_for_entry(db, ref)))


def test_digest_usage_isolated_per_user_db(tmp_path):
    """同一查询打到另一个用户的库（无该期刊行）→ 诚实空（无跨库泄漏）。"""
    db_a = Database(tmp_path / "a.sqlite")
    db_b = Database(tmp_path / "b.sqlite")
    run(db_a.migrate())
    run(db_b.migrate())
    issues_a = GptDigestIssuesStore(db_a)
    configs_a = GptDigestConfigStore(db_a)
    created = run(configs_a.create_config({"name": "A 的日报"}))
    run(
        issues_a.upsert_issue(
            config_id=created["id"],
            issue_key="2026-09-18",
            title="A",
            body_html="<p>x</p>",
            sections_json="[]",
            refs_json=json.dumps(
                {"s1": {"title": "t", "url": "u", "feedTitle": "f", "publishedAt": "", "ref": "e1.aaa"}}
            ),
            model="m",
            published_at="2026-09-18T08:00:00+00:00",
        )
    )
    assert len(run(digest_usage_for_entry(db_a, "e1.aaa"))) == 1
    assert run(digest_usage_for_entry(db_b, "e1.aaa")) == []


def test_digest_usage_route(client):
    db = app.state.db
    issues = GptDigestIssuesStore(db)
    configs = GptDigestConfigStore(db)
    created = run(configs.create_config({"name": "路由日报"}))
    ref = "e1.MDAwNjU5ZTA3YWFlZTI0ZA"
    run(
        issues.upsert_issue(
            config_id=created["id"],
            issue_key="2026-09-18",
            title="日报",
            body_html="<p>x</p>",
            sections_json=json.dumps(
                [{"heading": "头条", "items": [{"summary": "……", "sourceIds": ["s1"], "uncertainty": None}]}],
                ensure_ascii=False,
            ),
            refs_json=json.dumps(
                {"s1": {"title": "t", "url": "u", "feedTitle": "f", "publishedAt": "", "ref": ref}}
            ),
            model="m",
            published_at="2026-09-18T08:00:00+00:00",
        )
    )
    response = client.get(f"/api/v1/entries/{ref}/digest-usage")
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["citationAnchor"] == "2026-09-18:s1"
    assert items[0]["configName"] == "路由日报"
    # 非法引用 → 400
    assert client.get("/api/v1/entries/not-a-ref/digest-usage").status_code == 400
    # 无引用 → 诚实空
    fresh = "e1.MDAwNjU5ZTA3YWFlZTI0ZB"
    assert client.get(f"/api/v1/entries/{fresh}/digest-usage").json()["items"] == []
