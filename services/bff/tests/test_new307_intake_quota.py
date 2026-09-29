"""NEW-307 自动接入来源配额 — 原子预占/pending 保留/用户调整 + 隔离。"""

import asyncio

import pytest

from lumirss.new307_intake_quota import (
    IntakeQuotaInvalid,
    IntakeQuotaStore,
    clean_max_items,
)
from new2xx_ab import ab_env  # noqa: F401,F811 — pytest 夹具注册


def _run(coroutine):
    return asyncio.run(coroutine)


def test_new307_bounds():
    assert clean_max_items(1) == 1 and clean_max_items(100000) == 100000
    for bad in (0, 100001, True, "5", None):
        with pytest.raises(IntakeQuotaInvalid):
            clean_max_items(bad)


@pytest.fixture()
def quota_db(tmp_path):
    from lumirss.storage import Database

    database = Database(tmp_path / "lumi.sqlite")
    _run(database.migrate())
    return database


def test_new307_claim_atomic_hold(quota_db):
    """配额 3：预占 2+2 → 第二次只放行 1，超出 1 条进 pending（不丢）。"""
    store = IntakeQuotaStore(quota_db)
    assert _run(store.set_quota("src-1", 3))["maxItemsPerDay"] == 3
    first = _run(store.claim("src-1", 2))
    assert first["granted"] == 2 and first["heldBack"] == 0
    assert first["used"] == 2 and first["pending"] == 0
    second = _run(store.claim("src-1", 2))
    assert second["granted"] == 1
    assert second["heldBack"] == 1
    assert second["pending"] == 1  # 待处理计数保留
    snapshot = _run(store.snapshot("src-1"))
    assert snapshot["configured"] is True
    assert snapshot["used"] == 3 and snapshot["pending"] == 1
    assert snapshot["remaining"] == 0


def _quota_client_client(client, monkeypatch, items):
    import lumirss.routers.api_sources as routes

    async def fake_fetch(http_client, url):
        return items

    monkeypatch.setattr(routes, "fetch_json", fake_fetch)
    return client


def test_new307_feed_path_publishes_up_to_quota(client, monkeypatch):
    """配额 1 + 上游 3 条：首次拉取只发布 1 条，2 条进 pending；用户调
    高上限后同一窗口内继续发布剩余条目。"""
    _client = _quota_client_client(
        client,
        monkeypatch,
        [
            {"id": "i1", "name": "条目一"},
            {"id": "i2", "name": "条目二"},
            {"id": "i3", "name": "条目三"},
        ],
    )
    created = client.post(
        "/api/v1/api-sources",
        json={
            "name": "配额源",
            "endpoint": "https://api.example.com/q",
            "itemsExpr": "[*]",
            "fieldMap": {"id": "id", "title": "name"},
            "subscribe": False,
        },
    )
    assert created.status_code == 201, created.text
    source_uuid = created.json()["uuid"]
    atom_path = created.json()["atomPath"]

    limited = client.put(
        f"/api/v1/api-sources/{source_uuid}/intake-quota",
        json={"maxItemsPerDay": 1},
    )
    assert limited.status_code == 200, limited.text

    first_pull = client.get(atom_path)
    assert first_pull.status_code == 200
    assert first_pull.text.count("<entry>") == 1
    snapshot = client.get(
        f"/api/v1/api-sources/{source_uuid}/intake-quota"
    ).json()
    assert snapshot["used"] == 1 and snapshot["pending"] == 2

    # 用户选择调整：调高上限 → 剩余条目在同一窗口内可继续发布
    raised = client.put(
        f"/api/v1/api-sources/{source_uuid}/intake-quota",
        json={"maxItemsPerDay": 10},
    )
    assert raised.status_code == 200
    second_pull = client.get(atom_path)
    assert second_pull.status_code == 200
    assert second_pull.text.count("<entry>") == 3
    final = client.get(f"/api/v1/api-sources/{source_uuid}/intake-quota").json()
    assert final["used"] == 4 and final["pending"] == 2

    # 取消配额 = 不限
    assert (
        client.delete(
            f"/api/v1/api-sources/{source_uuid}/intake-quota"
        ).status_code
        == 204
    )
    gone = client.get(f"/api/v1/api-sources/{source_uuid}/intake-quota").json()
    assert gone["configured"] is False


def test_new307_cross_user_quota_invisible(ab_env):  # noqa: F811 — pytest 夹具注册
    """A 给自己来源设的配额与用量，B 查不到也改不了。"""
    env = ab_env
    client = env["client"]
    a, b = env["a"], env["b"]
    created = client.post(
        "/api/v1/api-sources",
        headers=a,
        json={
            "name": "A 的配额源",
            "endpoint": "https://api.example.com/qa",
            "itemsExpr": "[*]",
            "fieldMap": {"id": "id", "title": "t"},
            "subscribe": False,
        },
    )
    assert created.status_code == 201, created.text
    source_uuid = created.json()["uuid"]
    assert (
        client.put(
            f"/api/v1/api-sources/{source_uuid}/intake-quota",
            headers=a,
            json={"maxItemsPerDay": 5},
        ).status_code
        == 200
    )
    assert (
        client.get(
            f"/api/v1/api-sources/{source_uuid}/intake-quota", headers=b
        ).status_code
        == 404
    )
    assert (
        client.put(
            f"/api/v1/api-sources/{source_uuid}/intake-quota",
            headers=b,
            json={"maxItemsPerDay": 1},
        ).status_code
        == 404
    )
    mine = client.get(
        f"/api/v1/api-sources/{source_uuid}/intake-quota", headers=a
    ).json()
    assert mine["maxItemsPerDay"] == 5
