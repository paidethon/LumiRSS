"""N030 路由可复用参数方案 — CRUD + 应用（回填）+ cap + 哨兵 + 隔离。

覆盖：
- 创建：响应与 DB 行都只有 '***' 哨兵（敏感原文不可恢复），has_sensitive
  标记准确；模板参数 pattern 校验（非法 → 400）；未知路由 404；
- 应用（回填）：requiresRebind=True + sensitiveKeys（敏感方案）；纯
  非敏感方案 requiresRebind=False；不存在 404；
- cap 20/用户：第 21 个 → 400 rsshub_param_preset_limit（绝不静默淘汰）；
- 每用户私有：两个用户库互相不可见（RoutingDatabase 按身份路由使然，
  这里用两个独立用户库直接证明 store 层隔离）；
- 删除：204 → 404。
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from lumirss.main import app
from lumirss.rsshub import RssHubPreviewCache
from lumirss.rsshub_param_presets import RssHubParamPresetStore
from lumirss.storage import Database


@pytest.fixture()
def presets_client(monkeypatch, tmp_path):
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    with TestClient(app) as test_client:
        db = Database(tmp_path / "lumi.sqlite")
        app.state.db = db
        app.state.rsshub_preview_cache = RssHubPreviewCache(ttl_s=0.0)
        yield test_client, db, tmp_path
    app.state.rsshub_service = None


def _create(client, **body):
    return client.post(
        "/api/v1/rsshub/param-presets",
        json={"routeId": "hackernews", "params": {}, "name": "x", **body},
    )


def test_sensitive_value_stored_as_sentinel_only(presets_client):
    client, db, tmp_path = presets_client
    response = _create(
        client,
        routeId="github-starred-repos",
        params={"user": "DIYgod", "apiKey": "s3cret-value"},
        name="我的星标（含令牌）",
    )
    assert response.status_code == 201, response.text
    item = response.json()
    assert item["hasSensitive"] is True
    assert item["params"] == {"user": "DIYgod", "apiKey": "***"}
    assert "s3cret-value" not in response.text

    # DB 行内同样只有哨兵
    async def _read_row():
        row = await db.fetch_one(
            "SELECT params_json, has_sensitive FROM rsshub_param_presets WHERE id = ?",
            (item["id"],),
        )
        return row

    row = asyncio.run(_read_row())
    assert "s3cret-value" not in str(row["params_json"])
    assert int(row["has_sensitive"]) == 1


def test_apply_requires_rebind_for_sensitive(presets_client):
    client, _, _ = presets_client
    created = _create(
        client,
        routeId="github-starred-repos",
        params={"user": "DIYgod", "apiKey": "s3cret-value"},
        name="敏感方案",
    ).json()
    applied = client.post(f"/api/v1/rsshub/param-presets/{created['id']}/apply")
    assert applied.status_code == 200
    data = applied.json()
    assert data["requiresRebind"] is True
    assert data["sensitiveKeys"] == ["apiKey"]
    assert data["params"]["apiKey"] == "***"
    assert data["routeKey"] == created["routeKey"]

    # 非敏感方案：无需重绑
    plain = _create(client, params={}, name="无参方案").json()
    applied_plain = client.post(f"/api/v1/rsshub/param-presets/{plain['id']}/apply").json()
    assert applied_plain["requiresRebind"] is False
    assert applied_plain["sensitiveKeys"] == []


def test_create_validates_template_param_pattern(presets_client):
    client, _, _ = presets_client
    bad = _create(
        client,
        routeId="github-starred-repos",
        params={"user": "bad user!"},  # pattern 是 ^[a-zA-Z0-9-]{1,39}$
        name="非法参数",
    )
    assert bad.status_code == 400
    assert bad.json()["error"]["type"] == "rsshub_invalid_parameters"

    unknown = _create(client, routeId="nope", params={}, name="未知路由")
    assert unknown.status_code == 404
    assert unknown.json()["error"]["type"] == "rsshub_route_not_found"

    too_long_name = _create(client, name="x" * 81)
    assert too_long_name.status_code == 422


def test_preset_cap_is_twenty_and_rejected_after(presets_client):
    client, _, _ = presets_client
    for index in range(20):
        created = _create(client, params={}, name=f"方案 {index}")
        assert created.status_code == 201
    listing = client.get("/api/v1/rsshub/param-presets").json()
    assert len(listing) == 20
    over = _create(client, params={}, name="第 21 个")
    assert over.status_code == 400
    assert over.json()["error"]["type"] == "rsshub_param_preset_limit"
    # 被拒的创建不落库
    assert len(client.get("/api/v1/rsshub/param-presets").json()) == 20


def test_delete_roundtrip(presets_client):
    client, _, _ = presets_client
    created = _create(client, params={}, name="待删").json()
    assert client.delete(f"/api/v1/rsshub/param-presets/{created['id']}").status_code == 204
    missing = client.delete(f"/api/v1/rsshub/param-presets/{created['id']}")
    assert missing.status_code == 404
    assert missing.json()["error"]["type"] == "rsshub_param_preset_not_found"


def test_presets_are_private_per_user_database(tmp_path):
    """两个独立用户库互相不可见（每用户库隔离的 store 层证明）。"""

    async def run():
        db_a = Database(tmp_path / "user-a.sqlite")
        db_b = Database(tmp_path / "user-b.sqlite")
        store_a = RssHubParamPresetStore(db_a)
        store_b = RssHubParamPresetStore(db_b)
        created = await store_a.create(template_id="hackernews", params={}, name="A 的方案")
        assert await store_b.list_presets() == []
        with pytest.raises(Exception) as excinfo:
            await store_b.apply(created["id"])
        assert type(excinfo.value).__name__ == "RssHubPresetNotFound"
        assert await store_b.delete(created["id"]) is False
        assert [item["id"] for item in await store_a.list_presets()] == [created["id"]]

    asyncio.run(run())
