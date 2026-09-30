"""NEW-395 版本功能体验清单 — 消费真实发布清单、角色过滤、A/B 隔离。"""

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册


def test_new395_inventory_marks_and_validation(ab_env):  # noqa: F811
    client, a = ab_env["client"], ab_env["a"]
    listing = client.get("/api/v1/whats-new/experience", headers=a).json()
    # 清单来自 docs/release-notes.json（真实发布清单，不是自建）
    assert listing["version"] is not None
    assert listing["features"], "发布清单为空则该断言需按仓库清单更新"
    known = next(f for f in listing["features"] if not f.get("adminOnly"))
    assert known["mark"] is None
    # 标记「了解」→ 覆盖为「暂不使用」
    marked = client.post(
        f"/api/v1/whats-new/experience/{known['id']}/mark",
        json={"status": "learned"},
        headers=a,
    )
    assert marked.status_code == 200, marked.text
    assert marked.json()["status"] == "learned"
    later = client.post(
        f"/api/v1/whats-new/experience/{known['id']}/mark",
        json={"status": "later"},
        headers=a,
    ).json()
    assert later["status"] == "later"
    refreshed = client.get("/api/v1/whats-new/experience", headers=a).json()
    entry = next(
        f for f in refreshed["features"] if f["id"] == known["id"]
    )
    assert entry["mark"]["status"] == "later"
    # 清单外的 id 不能标记（绝不虚构已上线功能）
    unknown = client.post(
        "/api/v1/whats-new/experience/FAKE-999/mark",
        json={"status": "learned"},
        headers=a,
    )
    assert unknown.status_code == 404
    assert (
        client.post(
            f"/api/v1/whats-new/experience/{known['id']}/mark",
            json={"status": "whatever"},
            headers=a,
        ).status_code
        == 422
    )


def test_new395_role_filtering(ab_env):  # noqa: F811
    client, a, owner = ab_env["client"], ab_env["a"], ab_env["owner"]
    member_view = client.get("/api/v1/whats-new/experience", headers=a).json()
    assert all(not f.get("adminOnly") for f in member_view["features"])
    owner_view = client.get("/api/v1/whats-new/experience", headers=owner).json()
    assert any(f.get("adminOnly") for f in owner_view["features"])
    # 成员不能标记 adminOnly 条目（服务端拒绝，不是前端隐藏）
    admin_only = next(
        f for f in owner_view["features"] if f.get("adminOnly")
    )
    denied = client.post(
        f"/api/v1/whats-new/experience/{admin_only['id']}/mark",
        json={"status": "learned"},
        headers=a,
    )
    assert denied.status_code == 404


def test_new395_ab_isolation(ab_env):  # noqa: F811
    client, a, b = ab_env["client"], ab_env["a"], ab_env["b"]
    listing = client.get("/api/v1/whats-new/experience", headers=a).json()
    known = next(f for f in listing["features"] if not f.get("adminOnly"))
    client.post(
        f"/api/v1/whats-new/experience/{known['id']}/mark",
        json={"status": "learned"},
        headers=a,
    )
    mine = client.get("/api/v1/whats-new/experience", headers=a).json()
    theirs = client.get("/api/v1/whats-new/experience", headers=b).json()
    my_entry = next(f for f in mine["features"] if f["id"] == known["id"])
    their_entry = next(f for f in theirs["features"] if f["id"] == known["id"])
    assert my_entry["mark"]["status"] == "learned"
    assert their_entry["mark"] is None
