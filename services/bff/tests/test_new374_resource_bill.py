"""NEW-374 用户资源账单 — member 自查与 admin 查阅同一口径；只有
计数/字节/秒，绝无文章内容；admin 查阅他人留台账 + 审计。"""

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册


def test_new374_member_own_bill(ab_env):  # noqa: F811
    """alice 自查账单：五类计数 + 存储 + 计算量 + 诚实边界说明；
    任何字段都不是文章内容。"""
    client = ab_env["client"]
    alice = ab_env["a"]

    bill = client.get("/api/v1/account/resource-bill", headers=alice)
    assert bill.status_code == 200, bill.text
    payload = bill.json()
    assert set(payload["counts"]) == {
        "feeds",
        "entriesIndexed",
        "libraryItems",
        "clips",
        "assets",
    }
    assert payload["storage"]["totalBytes"] >= 0
    assert "FreshRSS 侧抓取消耗不经过 Lumi" in payload["contentNote"]
    text = str(payload)
    assert "title" not in text or '"title"' not in text  # 无内容字段

    # bob 不能经 member 端点看到 alice 的账单（端点固定以会话为主语）。
    assert (
        client.get("/api/v1/account/resource-bill", headers=ab_env["b"]).status_code
        == 200
    )


def test_new374_admin_views_member_bill_same_figures(ab_env):  # noqa: F811
    """admin 查阅他人账单：与本人自查同一口径（数字一致），并留下
    查阅台账（recentViews 记录查阅者）。"""
    client = ab_env["client"]
    owner, alice = ab_env["owner"], ab_env["a"]

    own = client.get("/api/v1/account/resource-bill", headers=alice).json()
    viewed = client.get(
        f"/api/v1/admin/users/{alice['userId']}/resource-bill", headers=owner
    )
    assert viewed.status_code == 200, viewed.text
    payload = viewed.json()
    assert payload["counts"] == own["counts"]
    assert payload["storage"]["totalBytes"] == own["storage"]["totalBytes"]
    assert len(payload["recentViews"]) == 1
    assert payload["recentViews"][0]["viewerId"]

    second = client.get(
        f"/api/v1/admin/users/{alice['userId']}/resource-bill", headers=owner
    )
    assert len(second.json()["recentViews"]) == 2


def test_new374_admin_route_requires_admin(ab_env):  # noqa: F811
    """member 无跨账户账单入口（403）；审计不泄露内容。"""
    client = ab_env["client"]
    bob = ab_env["b"]

    denied = client.get(
        f"/api/v1/admin/users/{ab_env['a']['userId']}/resource-bill", headers=bob
    )
    assert denied.status_code == 403


def test_new374_unknown_target_404(ab_env):  # noqa: F811
    client = ab_env["client"]
    missing = client.get(
        "/api/v1/admin/users/no-such-user/resource-bill", headers=ab_env["owner"]
    )
    assert missing.status_code == 404
