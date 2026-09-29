"""NEW-371 后台任务日历 — 计划/最近结果/暂停（含影响说明）+ 权限 +
无 shell 边界。时间一律 datetime.now 派生，无固定日历日期。"""

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册
from new37x_helpers import step_up_headers


def test_new371_calendar_lists_kinds_with_honest_plan(ab_env):  # noqa: F811
    """七个任务档齐全；间隔型相位未知 → plannedNext 为 null（诚实值）；
    digest 未配置发送 → 不编造下一次发送。"""
    client = ab_env["client"]
    owner = ab_env["owner"]

    bob = ab_env["b"]
    assert client.get("/api/v1/admin/task-calendar", headers=bob).status_code == 403

    response = client.get("/api/v1/admin/task-calendar", headers=owner)
    assert response.status_code == 200, response.text
    payload = response.json()
    kinds = {item["kind"]: item for item in payload["kinds"]}
    assert set(kinds) == {
        "search_sync",
        "obsidian_scan",
        "rag_index",
        "digest_scheduler",
        "mail_imap",
        "gpt_digest_scheduler",
        "rag_idle",
    }
    assert kinds["search_sync"]["label"]
    assert kinds["search_sync"]["plannedNext"] is None
    assert kinds["search_sync"]["enforcedBy"] == "loop"
    assert kinds["digest_scheduler"]["enforcedBy"] == "declared"
    assert any("shell" in note for note in payload["notes"])
    assert kinds["search_sync"]["intervalSeconds"] == 0  # 测试 env 显式关同步


def test_new371_pause_requires_step_up_and_impact(ab_env):  # noqa: F811
    """暂停 = 实例级敏感操作：无提权 403 step_up_required；无影响说明
    422；提权 + 影响说明 → 暂停生效，日历如实展示 enforcedBy 分档。"""
    client = ab_env["client"]
    owner = ab_env["owner"]

    bare = client.post(
        "/api/v1/admin/task-calendar/search_sync/pause",
        headers=owner,
        json={"reason": "维护", "impact": "投影暂停更新"},
    )
    assert bare.status_code == 403
    assert bare.json()["error"]["type"] == "step_up_required"

    headers = step_up_headers(client, owner, "task_kind_pause")
    # 提权令牌是单次消费（require_step_up 在载荷校验前）——无影响说明
    # 的 422 会烧掉这一枚，重试必须重新铸造。
    no_impact = client.post(
        "/api/v1/admin/task-calendar/search_sync/pause",
        headers=headers,
        json={"reason": "维护", "impact": "  "},
    )
    assert no_impact.status_code == 422

    paused = client.post(
        "/api/v1/admin/task-calendar/search_sync/pause",
        headers=step_up_headers(client, owner, "task_kind_pause"),
        json={"reason": "迁移维护", "impact": "搜索投影暂停更新；阅读不受影响。"},
    )
    assert paused.status_code == 200, paused.text
    assert paused.json()["paused"] is True

    again = client.post(
        "/api/v1/admin/task-calendar/search_sync/pause",
        headers=step_up_headers(client, owner, "task_kind_pause"),
        json={"reason": "x", "impact": "y"},
    )
    assert again.status_code == 409

    calendar = client.get("/api/v1/admin/task-calendar", headers=owner).json()
    entry = next(item for item in calendar["kinds"] if item["kind"] == "search_sync")
    assert entry["pause"]["active"] is True
    assert "阅读不受影响" in entry["impact"]
    foreign = next(item for item in calendar["kinds"] if item["kind"] == "digest_scheduler")
    assert foreign["enforcedBy"] == "declared"


def test_new371_paused_kinds_consumed_by_own_loops(ab_env):  # noqa: F811
    """真实消费点：main.py 自有循环在 tick 前读 paused_task_kinds——
    暂停 search_sync 后该 helper 返回包含它；resume（set 语义）后为空。"""
    client = ab_env["client"]
    owner = ab_env["owner"]
    headers = step_up_headers(client, owner, "task_kind_pause")

    paused = client.post(
        "/api/v1/admin/task-calendar/obsidian_scan/pause",
        headers=headers,
        json={"reason": "仓库检修", "impact": "Obsidian 扫描暂停。"},
    )
    assert paused.status_code == 200, paused.text

    import asyncio

    from lumirss.new371_task_calendar import paused_task_kinds

    kinds = asyncio.run(paused_task_kinds(ab_env["app"].state.control_db))
    assert "obsidian_scan" in kinds

    resumed = client.post(
        "/api/v1/admin/task-calendar/obsidian_scan/resume",
        headers=step_up_headers(client, owner, "task_kind_pause"),
    )
    assert resumed.status_code == 200, resumed.text
    assert asyncio.run(paused_task_kinds(ab_env["app"].state.control_db)) == set()

    # set 语义：再次 resume → 404（没有生效中的暂停）
    again = client.post(
        "/api/v1/admin/task-calendar/obsidian_scan/resume",
        headers=step_up_headers(client, owner, "task_kind_pause"),
    )
    assert again.status_code == 404


def test_new371_recent_runs_and_unknown_kind(ab_env):  # noqa: F811
    """调度器级结果台账：合法 kind 落账并出现在日历；未知 kind 拒绝。"""
    client = ab_env["client"]
    owner = ab_env["owner"]

    import asyncio

    from lumirss.new371_task_calendar import TaskKindUnknown, record_task_result

    async def run():
        db = ab_env["app"].state.control_db
        await record_task_result(db, kind="search_sync", status="ok", started_at="T0")
        try:
            await record_task_result(db, kind="not_a_kind", status="ok", started_at="T0")
        except TaskKindUnknown:
            return True
        return False

    assert asyncio.run(run()) is True

    calendar = client.get("/api/v1/admin/task-calendar", headers=owner).json()
    assert any(run["kind"] == "search_sync" and run["status"] == "ok" for run in calendar["recentRuns"])

    unknown = client.post(
        "/api/v1/admin/task-calendar/not_a_kind/pause",
        headers=owner,
        json={"reason": "x", "impact": "y"},
    )
    assert unknown.status_code == 422
