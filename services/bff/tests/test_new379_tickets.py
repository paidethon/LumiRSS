"""NEW-379 用户问题工单 — 提交/指派/回复/关闭；会员只见自己的；
处理人必须是管理员；系统绝不自动附带成员私人正文。"""

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册


def test_new379_member_submit_and_isolation(ab_env):  # noqa: F811
    """alice 提交 → 自己可见（列表无正文，详情含正文与回复线）；
    bob 看 alice 的工单 404（不泄露存在性）。"""
    client = ab_env["client"]
    alice, bob = ab_env["a"], ab_env["b"]

    created = client.post(
        "/api/v1/support/tickets",
        headers=alice,
        json={"subject": "导出失败", "body": "导出 EPUB 时报 500。"},
    )
    assert created.status_code == 201, created.text
    ticket_id = created.json()["id"]

    mine = client.get("/api/v1/support/tickets", headers=alice)
    assert mine.status_code == 200
    items = mine.json()["items"]
    assert len(items) == 1
    assert "body" not in items[0]  # 列表不带正文

    detail = client.get(f"/api/v1/support/tickets/{ticket_id}", headers=alice)
    assert detail.status_code == 200
    assert detail.json()["body"] == "导出 EPUB 时报 500。"
    assert detail.json()["replies"] == []
    assert detail.json()["status"] == "open"

    foreign = client.get(f"/api/v1/support/tickets/{ticket_id}", headers=bob)
    assert foreign.status_code == 404
    assert client.get("/api/v1/support/tickets", headers=bob).json()["items"] == []


def test_new379_admin_assign_reply_close_flow(ab_env):  # noqa: F811
    """owner：列表带计数 → 指派 → 回复(answered) → 关闭(终态)；
    关闭后成员回复 409；重复关闭 409。"""
    client = ab_env["client"]
    owner, alice = ab_env["owner"], ab_env["a"]

    ticket_id = client.post(
        "/api/v1/support/tickets",
        headers=alice,
        json={"subject": "同步卡住", "body": "搜索索引 30 分钟没更新。"},
    ).json()["id"]

    session = client.get("/api/v1/auth/session", headers=owner).json()
    owner_id = str(session["userId"])

    assigned = client.post(
        f"/api/v1/admin/tickets/{ticket_id}/assign",
        headers=owner,
        json={"adminUserId": owner_id},
    )
    assert assigned.status_code == 200, assigned.text
    assert assigned.json()["status"] == "assigned"

    admin_detail = client.get(f"/api/v1/admin/tickets/{ticket_id}", headers=owner)
    assert admin_detail.status_code == 200
    assert admin_detail.json()["submittedBy"] == alice["userId"]

    reply = client.post(
        f"/api/v1/admin/tickets/{ticket_id}/replies",
        headers=owner,
        json={"body": "已定位，下个版本修复。"},
    )
    assert reply.status_code == 200, reply.text
    assert reply.json()["status"] == "answered"

    closed = client.post(f"/api/v1/admin/tickets/{ticket_id}/close", headers=owner)
    assert closed.status_code == 200, closed.text

    member_reply = client.post(
        f"/api/v1/support/tickets/{ticket_id}/replies",
        headers=alice,
        json={"body": "追问一句。"},
    )
    assert member_reply.status_code == 409
    again = client.post(f"/api/v1/admin/tickets/{ticket_id}/close", headers=owner)
    assert again.status_code == 409

    listing = client.get("/api/v1/admin/tickets", headers=owner)
    assert listing.json()["counts"]["closed"] == 1


def test_new379_assignee_must_be_admin(ab_env):  # noqa: F811
    client = ab_env["client"]
    owner, bob = ab_env["owner"], ab_env["b"]
    ticket_id = client.post(
        "/api/v1/support/tickets",
        headers=bob,
        json={"subject": "问一下", "body": "配额怎么算？"},
    ).json()["id"]
    denied = client.post(
        f"/api/v1/admin/tickets/{ticket_id}/assign",
        headers=owner,
        json={"adminUserId": bob["userId"]},
    )
    assert denied.status_code == 422
    assert denied.json()["error"]["type"] == "invalid_assignee"


def test_new379_no_private_content_auto_attached(ab_env):  # noqa: F811
    """结构钉定：工单模块对 per-user 业务表零查询——admin 端点没有
    任何自动抓取成员文章/资料库正文的路径。"""
    import inspect

    from lumirss import new379_tickets as mod

    source = inspect.getsource(mod)
    for forbidden in ("search_entries", "library_items", "library_clips", "search_library"):
        assert forbidden not in source

    client = ab_env["client"]
    denied = client.get("/api/v1/admin/tickets", headers=ab_env["b"])
    assert denied.status_code == 403


def test_new379_validation(ab_env):  # noqa: F811
    client = ab_env["client"]
    alice = ab_env["a"]
    assert (
        client.post(
            "/api/v1/support/tickets", headers=alice, json={"subject": "", "body": "b"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/support/tickets", headers=alice, json={"subject": "s", "body": "  "}
        ).status_code
        == 422
    )
    unknown = client.get("/api/v1/support/tickets/nope", headers=alice)
    assert unknown.status_code == 404
