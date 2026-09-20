"""F043 API 来源结构变化预警 — 基线快照、漂移检测、空响应保护、解除与持久。

Hermetic：上游 fetch monkeypatch；数据库为 tmp 真库（迁移 0046/0047）。
"""

import asyncio
import json

import pytest

from lumirss.api_source_store import ApiSourceStore
from lumirss.api_sources import (
    diff_schema,
    observe_schema,
    serialize_baseline,
)


def _run(coroutine):
    return asyncio.run(coroutine)


def test_f043_observe_and_diff_matrix():
    """新增可选字段不告警；必需字段缺失/类型变化告警；new_optional 仅提示。"""
    baseline_items = [
        {"id": "a", "title": "甲", "url": "https://e.com/a", "published": "2026-09-01"},
        {"id": "b", "title": "乙", "url": "https://e.com/b", "published": "2026-09-02"},
    ]
    baseline = serialize_baseline(observe_schema(baseline_items))

    # 1) 新增可选字段 → 仅 new_optional 提示，无 missing/type_changed
    drift = diff_schema(
        baseline,
        observe_schema(
            [
                {"id": "a", "title": "甲", "url": "https://e.com/a", "published": "2026-09-01", "tag": "x"},
            ]
        ),
    )
    assert drift is not None
    assert drift["missing"] == []
    assert drift["type_changed"] == []
    assert drift["new_optional"] == ["tag"]

    # 2) 必需字段丢失 → missing 告警
    drift = diff_schema(baseline, observe_schema([{"id": "a", "title": "甲"}]))
    assert drift is not None
    assert "url" in drift["missing"]
    assert "published" in drift["missing"]

    # 3) 数字 → 字符串 → type_changed 告警
    drift = diff_schema(
        baseline,
        observe_schema([{"id": "a", "title": "甲", "url": "https://e.com/a", "published": 3}]),
    )
    assert drift is not None
    assert drift["type_changed"] == ["published"]


def test_f043_baseline_bounded_and_deterministic():
    """基线 ≤64 字段、序列化 ≤2KB、字段序确定。"""
    items = [{f"f{i:03d}": i for i in range(200)}]
    schema = observe_schema(items)
    assert len(schema) == 64
    payload = serialize_baseline(schema)
    assert payload is not None
    assert len(payload.encode("utf-8")) <= 2048
    assert serialize_baseline(observe_schema(items)) == payload


@pytest.fixture()
def source_db(tmp_path):
    from lumirss.storage import Database

    db = Database(tmp_path / "lumi.sqlite")
    _run(db.migrate())
    return db


def _create(store: ApiSourceStore) -> object:
    return _run(
        store.create(
            name="Scores",
            endpoint="https://api.example.com/scores",
            items_expr="[*]",
            field_map={"id": "id", "title": "title", "url": "url", "published": "published"},
        )
    )


def test_f043_confirm_clears_drift_and_restart_keeps_baseline(source_db, tmp_path):
    """确认→漂移→再确认解除；重启后基线与漂移状态保留。"""
    store = ApiSourceStore(source_db)
    record = _create(store)
    baseline_items = [
        {"id": "a", "title": "甲", "url": "https://e.com/a", "published": "2026-09-01"},
        {"id": "b", "title": "乙", "url": "https://e.com/b", "published": "2026-09-02"},
    ]
    _run(store.confirm_schema(record.uuid, baseline_items))
    confirmed = _run(store.get(record.uuid))
    assert confirmed is not None and confirmed.confirmed_schema is not None

    # 上游结构变化 → 漂移记录
    drifted_items = [{"id": "a", "title": "甲", "url": None, "published": "2026-09-05"}]
    from lumirss.api_sources import diff_schema as _diff
    from lumirss.api_sources import observe_schema as _obs

    drift = _diff(confirmed.confirmed_schema, _obs(drifted_items))
    assert drift is not None
    _run(store.mark_drift(record.uuid, drift))
    drifted = _run(store.get(record.uuid))
    assert drifted is not None
    assert json.loads(drifted.schema_drift)["missing"] == ["url"]
    assert json.loads(drifted.schema_drift)["type_changed"] == []

    # 重新确认 → 告警解除
    _run(store.confirm_schema(record.uuid, drifted_items))
    cleared = _run(store.get(record.uuid))
    assert cleared is not None and cleared.schema_drift is None

    # 重启（重新打开数据库）后基线保留
    reopened = ApiSourceStore(source_db)
    again = _run(reopened.get(record.uuid))
    assert again is not None
    assert again.confirmed_schema is not None
    assert json.loads(again.confirmed_schema)["published"]["type"] == "string"


def test_f043_empty_response_keeps_last_known_good(client, monkeypatch):
    """空映射结果不覆盖 last-known-good feed：stale 诚实服务 + 状态标记。"""
    import lumirss.routers.api_sources as routes

    payload_pages = [
        [{"id": "k1", "title": "保留我", "published_at": "2026-09-01T00:00:00Z"}],
    ]

    async def ok_fetch(client_arg, endpoint):
        _ = client_arg, endpoint
        return payload_pages[0]

    monkeypatch.setattr(routes, "fetch_json", ok_fetch)
    created = client.post(
        "/api/v1/api-sources",
        json={
            "name": "EmptyLater",
            "endpoint": "https://api.example.com/x",
            "itemsExpr": "[*]",
            "fieldMap": {"id": "id", "title": "title", "published": "published_at"},
            "subscribe": False,
        },
    )
    body = created.json()
    first = client.get(body["atomPath"])
    assert first.status_code == 200
    etag = first.headers["etag"]

    # 上游变空
    async def empty_fetch(client_arg, endpoint):
        _ = client_arg, endpoint
        return []

    monkeypatch.setattr(routes, "fetch_json", empty_fetch)
    second = client.get(body["atomPath"])
    assert second.status_code == 200
    assert second.headers.get("x-lumi-stale") == "1"
    assert "保留我" in second.text  # 上次内容仍在，未被空响应覆盖
    listing = client.get("/api/v1/api-sources").json()["items"]
    assert listing[0]["lastStatus"] == "empty_response"

    # 条件请求仍然 304（last-good ETag 生效）
    cached = client.get(body["atomPath"], headers={"if-none-match": etag})
    assert cached.status_code == 304


def test_f043_confirm_schema_endpoint_and_drift_surface(client, monkeypatch):
    """POST confirm-schema 快照基线；漂移出现在 GET 响应的 schemaDrift。"""
    import lumirss.routers.api_sources as routes

    current = [
        {"id": "a", "title": "甲", "published": "2026-09-01"},
        {"id": "b", "title": "乙", "published": "2026-09-02"},
    ]

    async def fetch_a(client_arg, endpoint):
        _ = client_arg, endpoint
        return current

    monkeypatch.setattr(routes, "fetch_json", fetch_a)
    created = client.post(
        "/api/v1/api-sources",
        json={
            "name": "Drifty",
            "endpoint": "https://api.example.com/x",
            "itemsExpr": "[*]",
            "fieldMap": {"id": "id", "title": "title", "published": "published"},
            "subscribe": False,
        },
    )
    body = created.json()
    client.get(body["atomPath"])  # 一次成功抓取（无基线 → 无漂移）
    listed = client.get("/api/v1/api-sources").json()["items"][0]
    assert listed["confirmedSchema"] is False
    assert listed["schemaDrift"] is None

    confirmed = client.post(f"/api/v1/api-sources/{body['uuid']}/confirm-schema")
    assert confirmed.status_code == 200
    assert confirmed.json() == {"confirmed": True, "sampledItems": 2}

    # 上游后续把 score 变成字符串 → 下一次抓取记漂移
    current[:] = [
        {"id": "a", "title": "甲", "published": 20260901},
        {"id": "b", "title": "乙", "published": 20260902},
    ]
    client.get(body["atomPath"])
    listed = client.get("/api/v1/api-sources").json()["items"][0]
    assert listed["confirmedSchema"] is True
    assert listed["schemaDrift"] is not None
    assert listed["schemaDrift"]["type_changed"] == ["published"]
    assert listed["schemaDrift"]["missing"] == []
