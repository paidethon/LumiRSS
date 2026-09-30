"""NEW-391 应用内通知收件箱 — 真实事件集中展示、按类型处理与保留、
A/B 隔离（私人事件只给本人）。

事件种子走唯一写入口 ``record_event``（各域收尾调用的跨域登记函数，
与 NEW-399 的修订回复同一入口）——没有事件就没有通知行。
"""

import asyncio

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册


def _seed(env, user_id: str, **kwargs):
    """以跨域登记函数直接落一条真实事件（测试面等价于域收尾调用）。"""
    from lumirss.new391_notifications import record_event
    from lumirss.storage import Database

    database = Database(str(env["db_path"] / "lumi.sqlite"))

    async def run():
        return await record_event(database, user_id=user_id, **kwargs)

    return asyncio.run(run())


def _user_ids(env):
    return {"a": env["a"]["userId"], "b": env["b"]["userId"]}


def test_new391_real_events_list_filter_and_counts(ab_env):  # noqa: F811
    client, a = ab_env["client"], ab_env["a"]
    ids = _user_ids(ab_env)
    # 无事件 → 诚实空收件箱
    empty = client.get("/api/v1/notifications", headers=a).json()
    assert empty["items"] == []
    assert empty["unread"] == 0
    # 域收尾登记：A 一条任务失败 + 一条共享事件；B 一条任务完成
    _seed(ab_env, ids["a"], kind="task_failed", source="daily_digest",
          title="日报生成失败", body="上游超时", ref="digest:cfg-1",
          actionable=True)
    _seed(ab_env, ids["a"], kind="share_event", source="space:alpha",
          title="有新成员加入共享空间", ref="space:alpha")
    _seed(ab_env, ids["b"], kind="task_completed", source="backup",
          title="备份完成", ref="backup:9")
    listing = client.get("/api/v1/notifications", headers=a).json()
    assert listing["counts"]["task_failed"] == 1
    assert listing["counts"]["share_event"] == 1
    assert listing["counts"]["task_completed"] == 0
    assert listing["unread"] == 2
    kinds_view = client.get(
        "/api/v1/notifications?kind=task_failed", headers=a
    ).json()
    assert [item["kind"] for item in kinds_view["items"]] == ["task_failed"]
    unread_view = client.get(
        "/api/v1/notifications?unreadOnly=true", headers=a
    ).json()
    assert len(unread_view["items"]) == 2
    unknown = client.get("/api/v1/notifications?kind=nope", headers=a)
    assert unknown.status_code == 422
    # 新事件在前（occurred_at DESC）
    assert listing["items"][0]["kind"] == "share_event"


def test_new391_mark_read_set_semantics_and_dismiss(ab_env):  # noqa: F811
    client, a = ab_env["client"], ab_env["a"]
    ids = _user_ids(ab_env)
    event = _seed(ab_env, ids["a"], kind="task_completed", source="backup",
                  title="备份完成", ref="backup:1")
    second = _seed(ab_env, ids["a"], kind="task_failed", source="digest",
                   title="日报失败", ref="digest:1")
    marked = client.post(
        f"/api/v1/notifications/{event['id']}/read", headers=a
    ).json()
    assert marked["readAt"] is not None
    # 再次标记 = 幂等（集合语义），不报错、不产生新状态
    again = client.post(
        f"/api/v1/notifications/{event['id']}/read", headers=a
    ).json()
    assert again["readAt"] == marked["readAt"]
    all_read = client.post(
        "/api/v1/notifications/read-all",
        json={"kind": "task_failed"},
        headers=a,
    ).json()
    assert all_read["marked"] == 1
    listing = client.get("/api/v1/notifications", headers=a).json()
    assert listing["unread"] == 0
    # 本人删除一条（保留清理是显式动作）
    removed = client.delete(f"/api/v1/notifications/{second['id']}", headers=a)
    assert removed.status_code == 200
    assert removed.json()["dismissed"] is True
    assert client.get("/api/v1/notifications", headers=a).json()["counts"][
        "task_failed"
    ] == 0
    gone = client.delete(f"/api/v1/notifications/{second['id']}", headers=a)
    assert gone.status_code == 404
    assert client.post(
        "/api/v1/notifications/read-all", json={"kind": "nope"}, headers=a
    ).status_code == 422


def test_new391_ab_isolation_private_events_stay_private(ab_env):  # noqa: F811
    client, a, b = ab_env["client"], ab_env["a"], ab_env["b"]
    ids = _user_ids(ab_env)
    event = _seed(ab_env, ids["a"], kind="share_event", source="space:alpha",
                  title="A 的共享空间有变化", ref="space:alpha")
    # B 的收件箱里没有 A 的事件
    inbox_b = client.get("/api/v1/notifications", headers=b).json()
    assert all(item["id"] != event["id"] for item in inbox_b["items"])
    assert inbox_b["counts"]["share_event"] == 0
    # B 不能已读 / 删除 A 的通知（404 同形，不泄露存在性）
    assert client.post(
        f"/api/v1/notifications/{event['id']}/read", headers=b
    ).status_code == 404
    assert client.delete(
        f"/api/v1/notifications/{event['id']}", headers=b
    ).status_code == 404
    # B 的全部已读只影响 B 自己
    client.post("/api/v1/notifications/read-all", json={}, headers=b)
    still = client.get("/api/v1/notifications", headers=a).json()
    assert still["unread"] == 1
    # B 的操作也绝不能落到 A 的行上
    row_a = client.get("/api/v1/notifications", headers=a).json()["items"][0]
    assert row_a["readAt"] is None


def test_new391_revoked_action_forces_invalid(ab_env):  # noqa: F811
    """与 NEW-394 的读取时联判：撤销登记命中 → actionable 强制为假。"""
    client, a = ab_env["client"], ab_env["a"]
    ids = _user_ids(ab_env)
    event = _seed(ab_env, ids["a"], kind="task_failed", source="digest",
                  title="日报失败", ref="digest:1", actionable=True)
    from lumirss.new394_revocations import register_revocation
    from lumirss.storage import Database

    database = Database(str(ab_env["db_path"] / "lumi.sqlite"))
    asyncio.run(
        register_revocation(
            database, notification_id=event["id"], user_id=ids["a"],
            reason="原事件已撤销：日报配置已删除。",
        )
    )
    item = client.get("/api/v1/notifications", headers=a).json()["items"][0]
    assert item["actionable"] is False
    assert item["invalidReason"] == "原事件已撤销：日报配置已删除。"
