"""NEW-377 后台任务阻塞定位 — 四类阻塞来自真实信号；处置只指向既有
安全治理面（无 shell、无强制解锁）；观测落台账。"""

from datetime import UTC, datetime, timedelta

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册


def _user_db(user_id: str):
    from lumirss.storage import Database

    routing = _ROUTING[0]
    return Database(routing.user_db_path(user_id))


def test_new377_diagnose_reports_structure_and_dependency_facts(ab_env):  # noqa: F811
    """干净实例：quota/rate_limit/lock 为零；未绑定 FreshRSS 的活跃
    账户如实计入 dependency；响应只含计数/键名/账户 id。"""
    client = ab_env["client"]
    owner = ab_env["owner"]
    _ROUTING[0] = ab_env["app"].state.db

    payload = client.get("/api/v1/admin/task-blockers", headers=owner)
    assert payload.status_code == 200, payload.text
    data = payload.json()
    assert data["counts"]["quota"] == 0
    assert data["counts"]["rate_limit"] == 0
    assert data["counts"]["lock"] == 0
    # 三个活跃账户（owner/alice/bob）都未绑定 FreshRSS。
    assert data["counts"]["dependency"] >= 1
    assert any("shell" not in action for action in data["safeActions"].values())
    assert any("强制解锁" in note for note in data["notes"])
    text = str(data)
    assert "http://" not in text and "https://" not in text  # 无来源 URL
    assert "feed_url" not in text


_ROUTING = [None]


def test_new377_quota_blocker_detected(ab_env):  # noqa: F811
    """alice 当日 AI 已用 ≥ 管理员日上限 → quota 阻塞（含计数与上限）。"""
    import asyncio

    client = ab_env["client"]
    owner, alice = ab_env["owner"], ab_env["a"]

    _ROUTING[0] = ab_env["app"].state.db

    # 管理员为 alice 设日上限 3（与单人设置同一执行点 + step-up；
    # FIX-218：作用域 target 必须是 alice 本人）。
    from new2xx_ab import PASSWORD

    minted = client.post(
        "/api/v1/admin/step-up",
        headers=owner,
        json={
            "password": PASSWORD,
            "operation": "user_quota_set",
            "targetUserId": alice["userId"],
        },
    )
    assert minted.status_code == 200, minted.text
    setcap = client.put(
        f"/api/v1/admin/users/{alice['userId']}/quota",
        headers={**owner, "X-Lumi-Step-Up": minted.json()["token"]},
        json={"aiQuotaPerDay": 3},
    )
    assert setcap.status_code == 200, setcap.text

    # alice 库写当日 ai_usage=3（与 ai_quota 同窗口键）。
    from lumirss.ai_quota import window_bounds

    async def seed():
        db = _user_db(alice["userId"])
        await db.migrate()
        bounds = window_bounds(window="day")
        await db.execute(
            "INSERT INTO ai_usage (window_key, window_start, calls) VALUES (?, ?, 3)",
            (bounds.key, bounds.start_iso),
        )

    asyncio.run(seed())

    data = client.get("/api/v1/admin/task-blockers", headers=owner).json()
    hits = [
        b
        for b in data["blockers"]
        if b["category"] == "quota" and b.get("userId") == alice["userId"]
    ]
    assert hits, data["blockers"]
    assert hits[0]["aiCallsToday"] == 3
    assert hits[0]["dailyCap"] == 3
    assert "NEW-375" in hits[0]["safeAction"]


def test_new377_lock_blocker_detected_without_force_unlock(ab_env):  # noqa: F811
    """alice 库存在未过期租约 → lock 阻塞（只给 scope 前缀与到期时刻）；
    处置入口如实声明「无强制解锁」。"""
    import asyncio

    client = ab_env["client"]
    owner, alice = ab_env["owner"], ab_env["a"]
    _ROUTING[0] = ab_env["app"].state.db
    future = (datetime.now(UTC) + timedelta(minutes=10)).isoformat(timespec="seconds")

    async def seed():
        db = _user_db(alice["userId"])
        await db.migrate()
        await db.execute(
            "INSERT INTO runtime_leases (scope, owner, expires_at, acquired_at)"
            " VALUES ('digest:2026-test', 'proc-test', ?, ?)",
            (future, datetime.now(UTC).isoformat(timespec="seconds")),
        )

    asyncio.run(seed())

    data = client.get("/api/v1/admin/task-blockers", headers=owner).json()
    locks = [
        b
        for b in data["blockers"]
        if b["category"] == "lock" and b.get("userId") == alice["userId"]
    ]
    assert locks
    assert locks[0]["scopeKind"] == "digest"
    assert locks[0]["expiresAt"] == future
    assert "无强制解锁" in locks[0]["safeAction"]


def test_new377_ledger_recorded(ab_env):  # noqa: F811
    """诊断观测落台账（ledger 端点只读）；member 403。"""
    client = ab_env["client"]
    owner = ab_env["owner"]

    client.get("/api/v1/admin/task-blockers", headers=owner)
    ledger = client.get("/api/v1/admin/task-blockers/ledger", headers=owner)
    assert ledger.status_code == 200, ledger.text
    items = ledger.json()["items"]
    assert items, "诊断应落台账"
    assert all({"category", "scope", "subject", "diagnosedAt"} <= set(item) for item in items)

    assert (
        client.get("/api/v1/admin/task-blockers", headers=ab_env["b"]).status_code
        == 403
    )
