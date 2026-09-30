"""NEW-396 新功能回退偏好 — 并存面注册、兼容期限、过期回新、A/B 隔离。"""

from datetime import UTC, datetime, timedelta

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册


def test_new396_surface_registry_and_modes(ab_env):  # noqa: F811
    client, a = ab_env["client"], ab_env["a"]
    listing = client.get("/api/v1/interaction-modes", headers=a).json()
    assert listing["surfaces"], "注册表不应为空（search_advanced 与单框搜索并存）"
    surface = next(s for s in listing["surfaces"] if s["key"] == "search_advanced")
    assert surface["mode"] == "new" and surface["chosenMode"] is None
    assert surface["expired"] is False
    # classic 必带兼容期限（面注册值）
    chosen = client.put(
        "/api/v1/interaction-modes/search_advanced",
        json={"mode": "classic"},
        headers=a,
    )
    assert chosen.status_code == 200, chosen.text
    body = chosen.json()
    assert body["mode"] == "classic"
    assert body["expiresAt"] is not None
    assert body["compatDays"] == surface["compatDays"]
    # new 无期限
    back = client.put(
        "/api/v1/interaction-modes/search_advanced", json={"mode": "new"}
    , headers=a).json()
    assert back["mode"] == "new" and back["expiresAt"] is None
    # 校验：坏模式 422 / 未注册面 404
    assert (
        client.put(
            "/api/v1/interaction-modes/search_advanced",
            json={"mode": "old"},
            headers=a,
        ).status_code
        == 422
    )
    assert (
        client.put(
            "/api/v1/interaction-modes/not-a-surface",
            json={"mode": "classic"},
            headers=a,
        ).status_code
        == 404
    )


def test_new396_expiry_forces_new(ab_env):  # noqa: F811
    """过期读取侧如实标注并强制新交互——旧实现没有无限期保留。"""
    client, a = ab_env["client"], ab_env["a"]
    client.put(
        "/api/v1/interaction-modes/search_advanced",
        json={"mode": "classic"},
        headers=a,
    )
    # 直接把期限改到过去（模拟时间流逝；无固定日历日期常量）
    from lumirss.storage import Database

    expired_at = (datetime.now(UTC) - timedelta(days=1)).isoformat(
        timespec="seconds"
    )
    database = Database(str(ab_env["db_path"] / "lumi.sqlite"))

    async def expire():
        await database.migrate()
        await database.execute(
            "UPDATE interaction_mode_prefs SET expires_at = ? WHERE surface = ?",
            (expired_at, "search_advanced"),
        )

    import asyncio

    asyncio.run(expire())
    listing = client.get("/api/v1/interaction-modes", headers=a).json()
    entry = next(s for s in listing["surfaces"] if s["key"] == "search_advanced")
    assert entry["chosenMode"] == "classic"
    assert entry["effectiveMode"] == "new"
    assert entry["mode"] == "new"
    assert entry["expired"] is True


def test_new396_ab_isolation(ab_env):  # noqa: F811
    client, a, b = ab_env["client"], ab_env["a"], ab_env["b"]
    client.put(
        "/api/v1/interaction-modes/search_advanced",
        json={"mode": "classic"},
        headers=a,
    )
    mine = client.get("/api/v1/interaction-modes", headers=a).json()
    theirs = client.get("/api/v1/interaction-modes", headers=b).json()
    my_entry = next(s for s in mine["surfaces"] if s["key"] == "search_advanced")
    their_entry = next(
        s for s in theirs["surfaces"] if s["key"] == "search_advanced"
    )
    assert my_entry["chosenMode"] == "classic"
    assert their_entry["chosenMode"] is None and their_entry["mode"] == "new"
