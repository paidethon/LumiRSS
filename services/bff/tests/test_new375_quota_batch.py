"""NEW-375 配额变更批次 — 预览（draft 不改任何账户）→ step-up 执行 →
逐账户结果；超额影响给出当日已用口径的下限估计。"""


from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册
from new37x_helpers import step_up_headers


def _seed_ai_usage(routing_db, user_id: str, calls: int) -> None:
    """直接在目标账户库写当日 ai_usage 计数（测试垫纸；键与 ai_quota
    同一口径：day:YYYY-MM-DD 本地时区）。"""
    import asyncio

    from lumirss.ai_quota import window_bounds
    from lumirss.storage import Database

    async def run():
        db = Database(routing_db.user_db_path(user_id))
        await db.migrate()
        bounds = window_bounds(window="day")
        existing = await db.fetch_one(
            "SELECT calls FROM ai_usage WHERE window_key = ?", (bounds.key,)
        )
        if existing is None:
            await db.execute(
                "INSERT INTO ai_usage (window_key, window_start, calls) VALUES (?, ?, ?)",
                (bounds.key, bounds.start_iso, calls),
            )
        else:
            await db.execute(
                "UPDATE ai_usage SET calls = ? WHERE window_key = ?",
                (calls, bounds.key),
            )

    asyncio.run(run())


def test_new375_preview_creates_draft_without_changing_accounts(ab_env):  # noqa: F811
    """预览：现有 caps → 拟值 → 当日已用 vs 新上限的下限估计；draft
    存档但 alice 的配额原样；未知账户如实 skipped。"""
    client = ab_env["client"]
    owner, alice = ab_env["owner"], ab_env["a"]
    routing = ab_env["app"].state.db

    _seed_ai_usage(routing, alice["userId"], 7)

    preview = client.post(
        "/api/v1/admin/quota-batches/preview",
        headers=owner,
        json={
            "changes": [
                {"userId": alice["userId"], "caps": {"aiQuotaPerDay": 5}},
                {"userId": "ghost-user", "caps": {"aiQuotaPerDay": 9}},
            ]
        },
    )
    assert preview.status_code == 200, preview.text
    payload = preview.json()
    assert payload["status"] == "draft"

    by_user = {item["userId"]: item for item in payload["preview"]}
    target = by_user[alice["userId"]]
    assert target["outcome"] == "preview"
    assert target["overQuotaImpact"]["aiCallsToday"] == 7
    assert target["overQuotaImpact"]["newDailyCap"] == 5
    assert target["overQuotaImpact"]["projectedDeniedMin"] == 2
    assert by_user["ghost-user"]["outcome"] == "skipped"

    # draft 不改任何账户：alice 配额原样（未设限）。
    quota = client.get(
        f"/api/v1/admin/users/{alice['userId']}/quota", headers=owner
    )
    assert quota.status_code == 200
    assert quota.json()["caps"] == {}


def test_new375_execute_requires_step_up(ab_env):  # noqa: F811
    client = ab_env["client"]
    owner = ab_env["owner"]
    batch = client.post(
        "/api/v1/admin/quota-batches/preview",
        headers=owner,
        json={"changes": [{"userId": ab_env["a"]["userId"], "caps": {"aiQuotaPerDay": 5}}]},
    ).json()
    bare = client.post(f"/api/v1/admin/quota-batches/{batch['batchId']}/execute", headers=owner)
    assert bare.status_code == 403
    assert bare.json()["error"]["type"] == "step_up_required"


def test_new375_execute_applies_per_account_results(ab_env):  # noqa: F811
    """执行：逐账户 ok + 结果落账；批次状态机 executed 后拒绝再执行/
    再取消；alice 配额真的生效。"""
    client = ab_env["client"]
    owner, alice = ab_env["owner"], ab_env["a"]

    batch = client.post(
        "/api/v1/admin/quota-batches/preview",
        headers=owner,
        json={
            "changes": [
                {"userId": alice["userId"], "caps": {"aiQuotaPerDay": 5}},
                {"userId": "ghost-user", "caps": {"aiQuotaPerDay": 9}},
            ]
        },
    ).json()

    executed = client.post(
        f"/api/v1/admin/quota-batches/{batch['batchId']}/execute",
        headers=step_up_headers(client, owner, "quota_batch_execute"),
    )
    assert executed.status_code == 200, executed.text
    payload = executed.json()
    assert payload["status"] == "executed"
    results = {item["userId"]: item for item in payload["results"]}
    assert results[alice["userId"]]["outcome"] == "ok"
    assert results[alice["userId"]]["after"] == {"aiQuotaPerDay": 5}
    assert results["ghost-user"]["outcome"] == "skipped"

    quota = client.get(f"/api/v1/admin/users/{alice['userId']}/quota", headers=owner)
    assert quota.json()["caps"] == {"aiQuotaPerDay": 5}

    detail = client.get(
        f"/api/v1/admin/quota-batches/{batch['batchId']}", headers=owner
    )
    assert detail.status_code == 200
    assert len(detail.json()["results"]) == 2

    re_exec = client.post(
        f"/api/v1/admin/quota-batches/{batch['batchId']}/execute",
        headers=step_up_headers(client, owner, "quota_batch_execute"),
    )
    assert re_exec.status_code == 409
    re_cancel = client.post(
        f"/api/v1/admin/quota-batches/{batch['batchId']}/cancel", headers=owner
    )
    assert re_cancel.status_code == 409


def test_new375_cancel_draft(ab_env):  # noqa: F811
    client = ab_env["client"]
    owner = ab_env["owner"]
    batch = client.post(
        "/api/v1/admin/quota-batches/preview",
        headers=owner,
        json={"changes": [{"userId": ab_env["a"]["userId"], "clear": True}]},
    ).json()
    cancelled = client.post(
        f"/api/v1/admin/quota-batches/{batch['batchId']}/cancel", headers=owner
    )
    assert cancelled.status_code == 200, cancelled.text
    listing = client.get("/api/v1/admin/quota-batches", headers=owner)
    assert any(
        item["status"] == "cancelled" for item in listing.json()["items"]
    )


def test_new375_invalid_changes_422(ab_env):  # noqa: F811
    client = ab_env["client"]
    owner = ab_env["owner"]
    unknown_key = client.post(
        "/api/v1/admin/quota-batches/preview",
        headers=owner,
        json={"changes": [{"userId": ab_env["a"]["userId"], "caps": {"nope": 1}}]},
    )
    assert unknown_key.status_code == 422
    clear_and_caps = client.post(
        "/api/v1/admin/quota-batches/preview",
        headers=owner,
        json={
            "changes": [
                {"userId": ab_env["a"]["userId"], "clear": True, "caps": {"aiQuotaPerDay": 5}}
            ]
        },
    )
    assert clear_and_caps.status_code == 422
    duplicate = client.post(
        "/api/v1/admin/quota-batches/preview",
        headers=owner,
        json={
            "changes": [
                {"userId": "u", "caps": {"aiQuotaPerDay": 5}},
                {"userId": "u", "caps": {"aiQuotaPerDay": 6}},
            ]
        },
    )
    assert duplicate.status_code == 422
