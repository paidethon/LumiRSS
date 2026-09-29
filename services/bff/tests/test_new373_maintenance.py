"""NEW-373 维护通知演练 — 先演练（不进维护）→ 确认后真实排程 →
全体用户经 notice 端点可见；窗口 set 语义状态机。时间全部由
datetime.now(UTC) ± timedelta 派生，无固定日历日期。"""

from datetime import UTC, datetime, timedelta

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册
from new37x_helpers import step_up_headers


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds")


def test_new373_drill_previews_all_roles_without_scheduling(ab_env):  # noqa: F811
    """演练返回四角色预览（与真实窗口同一渲染口径），但绝不创建窗口
    ——notice 端点保持 inactive。"""
    client = ab_env["client"]
    owner = ab_env["owner"]
    now = datetime.now(UTC)

    drilled = client.post(
        "/api/v1/admin/maintenance/drill",
        headers=owner,
        json={
            "title": "存储迁移演练",
            "notice": "演练文案：预计短暂只读。",
            "startsAt": _iso(now + timedelta(hours=1)),
            "endsAt": _iso(now + timedelta(hours=2)),
        },
    )
    assert drilled.status_code == 200, drilled.text
    payload = drilled.json()
    assert payload["scheduled"] is False
    assert set(payload["preview"]) == {"owner", "admin", "member", "visitor"}
    assert payload["preview"]["member"]["banner"]["title"] == "存储迁移演练"
    assert payload["preview"]["visitor"]["roleNote"]

    notice = client.get("/api/v1/maintenance/notice")
    assert notice.status_code == 200
    assert notice.json()["active"] is False  # 演练绝不触发真实维护提示

    drills = client.get("/api/v1/admin/maintenance/drills", headers=owner)
    assert drills.status_code == 200
    assert any(item["title"] == "存储迁移演练" for item in drills.json()["items"])


def test_new373_schedule_requires_step_up(ab_env):  # noqa: F811
    client = ab_env["client"]
    owner = ab_env["owner"]
    now = datetime.now(UTC)
    body = {
        "title": "真实维护",
        "notice": "索引重建中。",
        "startsAt": _iso(now + timedelta(minutes=30)),
        "endsAt": _iso(now + timedelta(minutes=90)),
    }
    bare = client.post("/api/v1/admin/maintenance/windows", headers=owner, json=body)
    assert bare.status_code == 403
    assert bare.json()["error"]["type"] == "step_up_required"

    ok = client.post(
        "/api/v1/admin/maintenance/windows",
        headers=step_up_headers(client, owner, "maintenance_schedule"),
        json=body,
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "scheduled"


def test_new373_notice_visible_during_window_and_upcoming(ab_env):  # noqa: F811
    """进行中的窗口 → active True（成员可见同一 notice）；未来窗口 →
    upcoming 预告；未登录访客也可读。"""
    client = ab_env["client"]
    owner = ab_env["owner"]
    now = datetime.now(UTC)

    active = client.post(
        "/api/v1/admin/maintenance/windows",
        headers=step_up_headers(client, owner, "maintenance_schedule"),
        json={
            "title": "进行中维护",
            "notice": "正在升级存储。",
            "startsAt": _iso(now - timedelta(minutes=10)),
            "endsAt": _iso(now + timedelta(minutes=50)),
        },
    )
    assert active.status_code == 200, active.text

    upcoming = client.post(
        "/api/v1/admin/maintenance/windows",
        headers=step_up_headers(client, owner, "maintenance_schedule"),
        json={
            "title": "下一场",
            "notice": "预告。",
            "startsAt": _iso(now + timedelta(hours=5)),
            "endsAt": _iso(now + timedelta(hours=6)),
        },
    )
    assert upcoming.status_code == 200, upcoming.text

    for headers in (ab_env["a"], ab_env["b"], {}):
        view = client.get("/api/v1/maintenance/notice", headers=headers)
        assert view.status_code == 200
        payload = view.json()
        assert payload["active"] is True
        assert payload["current"]["notice"] == "正在升级存储。"
        assert payload["upcoming"]["title"] == "下一场"


def test_new373_window_validation(ab_env):  # noqa: F811
    client = ab_env["client"]
    owner = ab_env["owner"]
    now = datetime.now(UTC)
    inverted = client.post(
        "/api/v1/admin/maintenance/drill",
        headers=owner,
        json={
            "title": "倒置",
            "notice": "n",
            "startsAt": _iso(now + timedelta(hours=2)),
            "endsAt": _iso(now + timedelta(hours=1)),
        },
    )
    assert inverted.status_code == 422
    unparseable = client.post(
        "/api/v1/admin/maintenance/drill",
        headers=owner,
        json={"title": "t", "notice": "n", "startsAt": "tomorrow", "endsAt": "later"},
    )
    assert unparseable.status_code == 422


def test_new373_settle_state_machine(ab_env):  # noqa: F811
    """complete → notice 失活；重复收尾 409；未知窗口 404。"""
    client = ab_env["client"]
    owner = ab_env["owner"]
    now = datetime.now(UTC)

    window = client.post(
        "/api/v1/admin/maintenance/windows",
        headers=step_up_headers(client, owner, "maintenance_schedule"),
        json={
            "title": "收尾演练",
            "notice": "临时。",
            "startsAt": _iso(now - timedelta(minutes=5)),
            "endsAt": _iso(now + timedelta(minutes=5)),
        },
    ).json()

    settled = client.post(
        f"/api/v1/admin/maintenance/windows/{window['id']}/settle",
        headers=owner,
        json={"status": "completed"},
    )
    assert settled.status_code == 200, settled.text

    notice = client.get("/api/v1/maintenance/notice")
    assert notice.json()["active"] is False

    again = client.post(
        f"/api/v1/admin/maintenance/windows/{window['id']}/settle",
        headers=owner,
        json={"status": "cancelled"},
    )
    assert again.status_code == 409

    missing = client.post(
        "/api/v1/admin/maintenance/windows/nope/settle",
        headers=owner,
        json={"status": "completed"},
    )
    assert missing.status_code == 404
