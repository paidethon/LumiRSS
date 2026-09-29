"""NEW-372 任务优先级调整 — 会员只操作自己的；管理员可调任意账户；
已运行任务不被抢占（顺序快照语义）。"""

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册


def test_new372_member_own_priority_roundtrip_and_isolation(ab_env):  # noqa: F811
    """alice 把自己的后台优先级调高；bob 完全不受影响（per-user 隔离）。"""
    client = ab_env["client"]
    alice, bob = ab_env["a"], ab_env["b"]

    default = client.get("/api/v1/tasks/priority", headers=alice)
    assert default.status_code == 200, default.text
    assert default.json()["priority"] == 2
    assert default.json()["default"] is True

    updated = client.put(
        "/api/v1/tasks/priority", headers=alice, json={"priority": "high"}
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["priority"] == 3
    assert updated.json()["appliesAt"] == "next_sweep"
    assert updated.json()["preemption"] is False

    # bob 未受影响；且不存在 member 写他人优先级的入口（路由无该参数）。
    bob_view = client.get("/api/v1/tasks/priority", headers=bob)
    assert bob_view.status_code == 200
    assert bob_view.json()["default"] is True

    # member 打管理员面 → 403。
    assert (
        client.get("/api/v1/admin/task-priorities", headers=alice).status_code == 403
    )
    assert (
        client.put(
            f"/api/v1/admin/task-priorities/{bob['userId']}",
            headers=alice,
            json={"priority": "low"},
        ).status_code
        == 403
    )


def test_new372_admin_sets_and_lists(ab_env):  # noqa: F811
    """管理员为成员设优先级并列出（带用户名）；恢复默认（DELETE）。"""
    client = ab_env["client"]
    owner, alice = ab_env["owner"], ab_env["a"]

    updated = client.put(
        f"/api/v1/admin/task-priorities/{alice['userId']}",
        headers=owner,
        json={"priority": "low"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["priority"] == 1

    listing = client.get("/api/v1/admin/task-priorities", headers=owner)
    assert listing.status_code == 200, listing.text
    items = listing.json()["items"]
    row = next(item for item in items if item["userId"] == alice["userId"])
    assert row["priorityLabel"] == "低"
    assert row["username"] == "alice"
    assert listing.json()["preemption"] is False

    cleared = client.delete(
        f"/api/v1/admin/task-priorities/{alice['userId']}", headers=owner
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["cleared"] is True

    back = client.get("/api/v1/tasks/priority", headers=alice)
    assert back.json()["default"] is True


def test_new372_validation_and_unknown_target(ab_env):  # noqa: F811
    """非法优先级 422；未知目标账户 404。"""
    client = ab_env["client"]
    owner = ab_env["owner"]

    bad = client.put(
        "/api/v1/tasks/priority", headers=owner, json={"priority": "urgent"}
    )
    assert bad.status_code == 422

    missing = client.put(
        "/api/v1/admin/task-priorities/no-such-user",
        headers=owner,
        json={"priority": "high"},
    )
    assert missing.status_code == 404


def test_new372_sweep_order_snapshot_semantics(ab_env):  # noqa: F811
    """顺序快照：高优先级在前，同层稳定；快照是新列表（变更不打断
    已开始的清扫）；治理面故障时按原序（清扫绝不被弄停）。"""
    import asyncio

    from lumirss.new372_task_priority import background_sweep_order, set_priority

    async def run():
        db = ab_env["app"].state.control_db
        alice, bob = ab_env["a"]["userId"], ab_env["b"]["userId"]
        await set_priority(db, user_id=alice, level="high", updated_by="t")
        await set_priority(db, user_id=bob, level="low", updated_by="t")
        owner_id = ab_env["owner"].get("userId") or "owner"
        active = [owner_id, alice, bob]
        order = await background_sweep_order(db, active)
        return order, alice, bob

    order, alice, bob = asyncio.run(run())
    assert order.index(alice) < order.index(bob)
    # 顺序与输入顺序无关（重排而非覆盖）：owner 未登记 → 保持相对次序在普通层。
    assert set(order) == {ab_env["a"]["userId"], ab_env["b"]["userId"], ab_env["owner"].get("userId") or "owner"}

    # 空列表 → 空快照；坏 handle → 原序返回（fail-open 顺序优化）。
    async def run2():
        class Broken:
            async def migrate(self):
                raise RuntimeError("boom")

        active = ["u1", "u2"]
        fallback = await background_sweep_order(Broken(), active)
        empty = await background_sweep_order(ab_env["app"].state.control_db, [])
        return fallback, empty

    fallback, empty = asyncio.run(run2())
    assert fallback == ["u1", "u2"]
    assert empty == []
