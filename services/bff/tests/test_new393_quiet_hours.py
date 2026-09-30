"""NEW-393 提醒静默时段 — 校验（HH:MM/时区/空窗）、结束汇总、A/B 隔离。

窗口用 datetime.now(UTC) 推导（无固定日期）：「覆盖当前时刻」与「远离
当前时刻」两种，跨午夜分支由 now±5min 构造自然覆盖。
"""

from datetime import UTC, datetime, timedelta

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册
from test_new391_notifications import _seed, _user_ids


def _hhmm(dt: datetime) -> str:
    return dt.strftime("%H:%M")


def _cover_now_window() -> tuple[str, str]:
    now = datetime.now(UTC)
    return _hhmm(now - timedelta(minutes=5)), _hhmm(now + timedelta(minutes=5))


def _away_window() -> tuple[str, str]:
    now = datetime.now(UTC)
    return _hhmm(now + timedelta(hours=3)), _hhmm(now + timedelta(hours=4))


def test_new393_set_validate_and_summary(ab_env):  # noqa: F811
    client, a = ab_env["client"], ab_env["a"]
    ids = _user_ids(ab_env)
    # 未设置 → 诚实关闭态
    initial = client.get("/api/v1/notifications/quiet-hours", headers=a).json()
    assert initial["enabled"] is False
    # 校验：空窗 / 坏 HH:MM / 坏时区
    start, end = _cover_now_window()
    equal = client.put(
        "/api/v1/notifications/quiet-hours",
        json={"startHHMM": "08:00", "endHHMM": "08:00", "timeZone": "Asia/Shanghai"},
        headers=a,
    )
    assert equal.status_code == 422
    bad_time = client.put(
        "/api/v1/notifications/quiet-hours",
        json={"startHHMM": "24:61", "endHHMM": "09:00", "timeZone": "UTC"},
        headers=a,
    )
    assert bad_time.status_code in (400, 422)
    bad_tz = client.put(
        "/api/v1/notifications/quiet-hours",
        json={"startHHMM": "01:00", "endHHMM": "02:00", "timeZone": "Mars/Olympus"},
        headers=a,
    )
    assert bad_tz.status_code == 422
    # 覆盖当前时刻的窗口 → inQuiet 真实为真
    set_done = client.put(
        "/api/v1/notifications/quiet-hours",
        json={"startHHMM": start, "endHHMM": end, "timeZone": "UTC"},
        headers=a,
    )
    assert set_done.status_code == 200, set_done.text
    assert set_done.json()["enabled"] is True
    # 静默不影响事件落库
    _seed(ab_env, ids["a"], kind="task_failed", source="digest",
          title="静默期间的失败", ref="digest:1")
    summary = client.get("/api/v1/notifications/quiet-summary", headers=a).json()
    assert summary["enabled"] is True
    assert summary["inQuiet"] is True
    assert summary["quietEndsAt"] is not None
    assert summary["unreadDuringWindow"] == 1
    assert summary["byKind"] == {"task_failed": 1}
    # 远离当前时刻的窗口 → 不在静默中（汇总仍给出未读口径）
    away_start, away_end = _away_window()
    client.put(
        "/api/v1/notifications/quiet-hours",
        json={"startHHMM": away_start, "endHHMM": away_end, "timeZone": "UTC"},
        headers=a,
    )
    away_summary = client.get(
        "/api/v1/notifications/quiet-summary", headers=a
    ).json()
    assert away_summary["inQuiet"] is False
    assert away_summary["quietEndsAt"] is None
    assert away_summary["unreadTotal"] == 1
    # 停用 → inQuiet 恒为假
    client.put(
        "/api/v1/notifications/quiet-hours",
        json={"startHHMM": start, "endHHMM": end, "timeZone": "UTC",
              "enabled": False},
        headers=a,
    )
    off = client.get("/api/v1/notifications/quiet-summary", headers=a).json()
    assert off["enabled"] is False and off["inQuiet"] is False


def test_new393_ab_isolation(ab_env):  # noqa: F811
    client, a, b = ab_env["client"], ab_env["a"], ab_env["b"]
    ids = _user_ids(ab_env)
    start, end = _cover_now_window()
    assert (
        client.put(
            "/api/v1/notifications/quiet-hours",
            json={"startHHMM": start, "endHHMM": end, "timeZone": "UTC"},
            headers=a,
        ).status_code
        == 200
    )
    _seed(ab_env, ids["a"], kind="share_event", source="space:a",
          title="A 的共享事件", ref="space:a")
    # B 未设置 → 关闭态；B 的汇总里没有 A 的未读事件
    b_setting = client.get("/api/v1/notifications/quiet-hours", headers=b).json()
    assert b_setting["enabled"] is False
    b_summary = client.get("/api/v1/notifications/quiet-summary", headers=b).json()
    assert b_summary["unreadTotal"] == 0 and b_summary["unreadDuringWindow"] == 0
    assert b_summary["byKind"] == {}
    # B 设置自己的窗口不影响 A
    b_start, b_end = _away_window()
    client.put(
        "/api/v1/notifications/quiet-hours",
        json={"startHHMM": b_start, "endHHMM": b_end, "timeZone": "UTC"},
        headers=b,
    )
    a_setting = client.get("/api/v1/notifications/quiet-hours", headers=a).json()
    assert a_setting["startHHMM"] == start and a_setting["endHHMM"] == end
