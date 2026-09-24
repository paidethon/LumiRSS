"""N129 API 限额友好策略 — per-source hourly budget + Retry-After.

Proves: the persisted token bucket blocks the 5th run within an hour
(429 budget_exhausted + Retry-After + nextAllowedRun); old runs are
pruned (an hour-old run does not count); an upstream 429 with
Retry-After stores next_allowed_run and serves the last-good body;
budget config is editable via PATCH and surfaced on GET; the UI contract
field (nextAllowedRun) renders from the source detail.
"""

import asyncio

import pytest


def _run(coroutine):
    return asyncio.run(coroutine)


def _iso(seconds_ago: float) -> str:
    from datetime import UTC, datetime, timedelta

    moment = datetime.now(UTC) - timedelta(seconds=seconds_ago)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture()
def source_db(tmp_path):
    from lumirss.storage import Database

    db = Database(tmp_path / "lumi.sqlite")
    _run(db.migrate())
    return db


def test_token_bucket_blocks_fifth_run_within_hour(source_db):
    from lumirss.api_source_store import ApiSourceStore

    store = ApiSourceStore(source_db)
    record = _run(
        store.create(
            name="预算源",
            endpoint="https://api.example.com/items",
            items_expr="[*]",
            field_map={"id": "id", "title": "name"},
            max_runs_per_hour=4,
        )
    )
    for index in range(4):
        _run(store.record_run(record.uuid))
        blocked = _run(store.exhausted_until(record.uuid, 4))
        # 前 4 次运行都在预算内；预算耗尽后（第 5 次请求）被拦
        assert (blocked is not None) == (index == 3)
    _run(store.record_run(record.uuid))
    blocked = _run(store.exhausted_until(record.uuid, 4))
    assert blocked is not None  # 第 5 次被拦


def test_hour_old_runs_are_pruned_or_ignored(source_db):
    from lumirss.api_source_store import ApiSourceStore

    store = ApiSourceStore(source_db)
    record = _run(
        store.create(
            name="旧桶",
            endpoint="https://api.example.com/items",
            items_expr="[*]",
            field_map={"id": "id", "title": "name"},
            max_runs_per_hour=4,
        )
    )
    # 直接落 4 条 2 小时前的运行记录（超出滑动窗口）
    old = _iso(7200)
    _run(
        source_db.execute_many(
            "INSERT INTO api_source_runs (source_uuid, ran_at) VALUES (?, ?)",
            [(record.uuid, old)] * 4,
        )
    )
    assert _run(store.exhausted_until(record.uuid, 4)) is None
    # record_run 顺带裁剪窗口外旧行
    _run(store.record_run(record.uuid))
    remaining = _run(
        source_db.fetch_all(
            "SELECT ran_at FROM api_source_runs WHERE source_uuid = ?",
            (record.uuid,),
        )
    )
    assert len(remaining) == 1


def test_atom_route_blocks_over_budget_with_429_budget_exhausted(client):
    import lumirss.routers.api_sources as routes

    async def _fake_fetch(url, *args, **kwargs):
        return [{"id": 1, "name": "n"}]

    original = routes.fetch_json
    routes.fetch_json = _fake_fetch
    try:
        created = client.post(
            "/api/v1/api-sources",
            json={
                "name": "预算路由源",
                "endpoint": "https://api.example.com/x",
                "itemsExpr": "[*]",
                "fieldMap": {"id": "id", "title": "name"},
                "subscribe": False,
                "maxRunsPerHour": 2,
            },
        )
        assert created.status_code == 201
        atom_path_value = created.json()["atomPath"]
        for _ in range(2):
            ok = client.get(atom_path_value)
            assert ok.status_code == 200
        blocked = client.get(atom_path_value)
        assert blocked.status_code == 429
        assert blocked.json()["error"]["type"] == "budget_exhausted"
        assert "Retry-After" in blocked.headers
        assert blocked.json()["error"]["nextAllowedRun"]
        # GET detail 暴露下次允许运行时间（web 下次允许运行时间来源）
        sources = client.get("/api/v1/api-sources").json()["items"]
        assert sources[0]["nextAllowedRun"] is not None
        assert sources[0]["maxRunsPerHour"] == 2
        assert sources[0]["respectRetryAfter"] is True
    finally:
        routes.fetch_json = original


def test_upstream_429_retry_after_sets_next_allowed_run(client):
    import lumirss.routers.api_sources as routes

    async def _rate_limited(url, *args, **kwargs):
        raise routes.ApiSourceRateLimited(120)

    original = routes.fetch_json
    routes.fetch_json = _rate_limited
    try:
        created = client.post(
            "/api/v1/api-sources",
            json={
                "name": "限流源",
                "endpoint": "https://api.example.com/x",
                "itemsExpr": "[*]",
                "fieldMap": {"id": "id", "title": "name"},
                "subscribe": False,
            },
        )
        assert created.status_code == 201
        body = created.json()
        first = client.get(body["atomPath"])
        assert first.status_code == 502  # 无 last-known-good → 诚实 502
        detail = client.get("/api/v1/api-sources").json()["items"][0]
        assert detail["nextAllowedRun"] is not None  # Retry-After 被落库
        assert detail["lastStatus"] == "rate_limited"
        assert "429" in (detail["lastError"] or "")
        # respectRetryAfter 固定 true
        assert detail["respectRetryAfter"] is True
    finally:
        routes.fetch_json = original


def test_upstream_429_serves_last_known_good_stale(client):
    import lumirss.routers.api_sources as routes

    calls = {"n": 0}

    async def _fetch(url, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return [{"id": 1, "name": "首捕"}]
        raise routes.ApiSourceRateLimited(60)

    original = routes.fetch_json
    routes.fetch_json = _fetch
    try:
        created = client.post(
            "/api/v1/api-sources",
            json={
                "name": "限流退化源",
                "endpoint": "https://api.example.com/x",
                "itemsExpr": "[*]",
                "fieldMap": {"id": "id", "title": "name"},
                "subscribe": False,
            },
        )
        atom_path_value = created.json()["atomPath"]
        assert client.get(atom_path_value).status_code == 200
        stale = client.get(atom_path_value)
        assert stale.status_code == 200
        assert stale.headers.get("X-Lumi-Stale") == "1"
        assert "首捕" in stale.text
    finally:
        routes.fetch_json = original


def test_patch_budget_config_and_invalid_rejected(client):
    created = client.post(
        "/api/v1/api-sources",
        json={
            "name": "预算编辑源",
            "endpoint": "https://api.example.com/x",
            "itemsExpr": "[*]",
            "fieldMap": {"id": "id", "title": "name"},
            "subscribe": False,
        },
    )
    uuid = created.json()["uuid"]
    patched = client.patch(
        f"/api/v1/api-sources/{uuid}", json={"maxRunsPerHour": 12}
    )
    assert patched.status_code == 200
    assert patched.json()["maxRunsPerHour"] == 12
    invalid = client.patch(
        f"/api/v1/api-sources/{uuid}", json={"maxRunsPerHour": 0}
    )
    assert invalid.status_code == 400
    assert invalid.json()["error"]["type"] == "invalid_api_source"
