"""NEW-400 个人功能使用清理 — 实时计数、本人显式关闭、数据去留、无自动关闭。"""

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册

MODULE_KEYS = {"notification_aggregation", "notification_quiet_hours",
               "interaction_modes", "error_runbooks"}


def _close(client, who, key, retention):
    return client.post(
        f"/api/v1/settings/module-cleanup/{key}/close",
        json={"retention": retention},
        headers=who,
    )


def test_new400_listing_counts_and_keep_close(ab_env):  # noqa: F811
    client, a = ab_env["client"], ab_env["a"]
    listing = client.get("/api/v1/settings/module-cleanup", headers=a).json()
    assert {m["key"] for m in listing["modules"]} == MODULE_KEYS
    assert all(m["enabledCount"] == 0 and m["closure"] is None
               for m in listing["modules"])
    # 真实启用一个模块（392 聚合规则）→ 计数实时来自功能自己的表
    client.post(
        "/api/v1/notifications/aggregation-rules",
        json={"kind": "task_failed", "source": "digest"},
        headers=a,
    )
    listing = client.get("/api/v1/settings/module-cleanup", headers=a).json()
    agg = next(m for m in listing["modules"]
               if m["key"] == "notification_aggregation")
    assert agg["enabledCount"] == 1
    # 本人关闭 + 保留数据 → 开关关、数据留、留痕记录
    closed = _close(client, a, "notification_aggregation", "keep")
    assert closed.status_code == 200, closed.text
    assert closed.json()["retention"] == "keep"
    listing = client.get("/api/v1/settings/module-cleanup", headers=a).json()
    agg = next(m for m in listing["modules"]
               if m["key"] == "notification_aggregation")
    assert agg["enabledCount"] == 0
    assert agg["closure"]["retention"] == "keep" and agg["closure"]["detail"]
    rules = client.get("/api/v1/notifications/aggregation-rules", headers=a).json()
    assert len(rules["rules"]) == 1 and rules["rules"][0]["enabled"] is False
    # 校验：未知模块 / 坏 retention
    assert _close(client, a, "not-a-module", "keep").status_code == 404
    assert _close(client, a, "notification_aggregation", "auto").status_code == 422


def test_new400_delete_retention_and_runbook_cleanup(ab_env):  # noqa: F811
    client, a = ab_env["client"], ab_env["a"]
    session = client.post(
        "/api/v1/support/runbooks/connection_error/sessions", headers=a
    ).json()
    client.post(
        f"/api/v1/support/runbooks/sessions/{session['id']}/steps",
        json={"stepIndex": 1, "outcome": "tried"},
        headers=a,
    )
    listing = client.get("/api/v1/settings/module-cleanup", headers=a).json()
    books = next(m for m in listing["modules"] if m["key"] == "error_runbooks")
    assert books["enabledCount"] == 1
    closed = _close(client, a, "error_runbooks", "delete")
    assert closed.status_code == 200
    assert closed.json()["detail"]
    # delete = 数据一并清除（处理单历史消失）
    assert client.get(
        f"/api/v1/support/runbooks/sessions/{session['id']}", headers=a
    ).status_code == 404
    listing = client.get("/api/v1/settings/module-cleanup", headers=a).json()
    books = next(m for m in listing["modules"] if m["key"] == "error_runbooks")
    assert books["enabledCount"] == 0
    assert books["closure"]["retention"] == "delete"


def test_new400_no_automatic_closure_and_ab_isolation(ab_env):  # noqa: F811
    client, a, b = ab_env["client"], ab_env["a"], ab_env["b"]
    # A 启用两个模块；B 做大量相关动作，也绝不影响 A 的启用状态
    client.post(
        "/api/v1/notifications/aggregation-rules",
        json={"kind": "share_event", "source": "space:a"},
        headers=a,
    )
    start, end = "01:00", "02:00"
    client.put(
        "/api/v1/notifications/quiet-hours",
        json={"startHHMM": start, "endHHMM": end, "timeZone": "UTC"},
        headers=a,
    )
    # B 的动作（建规则/开单）不写 A 的关闭留痕，也不关 A 的模块
    client.post(
        "/api/v1/notifications/aggregation-rules",
        json={"kind": "task_failed", "source": "digest"},
        headers=b,
    )
    client.post("/api/v1/support/runbooks/connection_error/sessions", headers=b)
    b_close = _close(client, b, "notification_aggregation", "delete")
    assert b_close.status_code == 200
    a_listing = client.get("/api/v1/settings/module-cleanup", headers=a).json()
    agg = next(m for m in a_listing["modules"]
               if m["key"] == "notification_aggregation")
    quiet = next(m for m in a_listing["modules"]
                 if m["key"] == "notification_quiet_hours")
    assert agg["enabledCount"] == 1 and agg["closure"] is None
    assert quiet["enabledCount"] == 1 and quiet["closure"] is None
    # B 的关闭也不出现在 A 的留痕里
    assert all(m["closure"] is None for m in a_listing["modules"])
    # A 本人关闭 quiet（keep）→ 只影响 A
    assert _close(client, a, "notification_quiet_hours", "keep").status_code == 200
    b_listing = client.get("/api/v1/settings/module-cleanup", headers=b).json()
    b_quiet = next(m for m in b_listing["modules"]
                   if m["key"] == "notification_quiet_hours")
    assert b_quiet["enabledCount"] == 0 and b_quiet["closure"] is None
