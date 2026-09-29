"""NEW-306 API 抓取变更预警 — 必要字段漂移暂停写入/确认恢复 + 隔离。"""

import asyncio
import json

from lumirss.new306_schema_pause import evaluate_required_drift, pause_reason_text
from new2xx_ab import ab_env  # noqa: F401,F811 — pytest 夹具注册

BASELINE_ITEMS = [
    {"id": "1", "title": "甲", "body": "x", "extra": "可选一"},
    {"id": "2", "title": "乙", "body": "y", "extra": "可选二"},
]
DRIVED_ITEMS = [
    {"id": "1", "body": "x", "extra": "可选仍在"},
    {"id": "2", "body": "y", "extra": "可选仍在"},
]


def _run(coroutine):
    return asyncio.run(coroutine)


def _baseline_from(items):
    from lumirss.api_sources import observe_schema, serialize_baseline

    return serialize_baseline(observe_schema(items))


def test_new306_required_field_drift_triggers_pause_payload():
    baseline = _baseline_from(BASELINE_ITEMS)
    hit = evaluate_required_drift(baseline, json.loads(json.dumps(DRIVED_ITEMS)))
    assert hit is not None
    assert "title" in hit["missing"]
    # 仅可选字段变化 → 不暂停（advisory 归 F043）
    mild = [dict(row) for row in BASELINE_ITEMS]
    mild[0]["brandNew"] = 1
    assert evaluate_required_drift(baseline, json.loads(json.dumps(BASELINE_ITEMS + [{"id": "3", "title": "丙", "body": "z", "brandNew": 1}]))) is None
    # 无基线（从未确认）→ 永不暂停
    assert evaluate_required_drift(None, json.loads(json.dumps(DRIVED_ITEMS))) is None


def test_new306_pause_reason_text_lists_fields():
    text = pause_reason_text({"missing": ["title"], "typeChanged": ["id"]})
    assert "title" in text and "id" in text
    assert "确认新映射" in text


BOX = {"mode": "stable"}


async def _fetch_upstream(http_client, url):
    # 注意：映射管线要求 id+title 同真才保留条目，因此「必要字段漂移
    # 仍有条目流动」的故障形状是 **body 消失**（title 完全消失会坍缩
    # 进既有的 empty_response 诚实分支，不属于本预警的触发面）。
    if BOX["mode"] == "empty":
        return {"catastrophe": True}  # 映射结果为空 → 探测必须 409
    if BOX["mode"] == "broken":
        return [
            {"id": str(10 + i), "name": "无正文条目" + str(i)}
            for i in range(3)
        ]
    if BOX["mode"] == "new":
        return [
            {"uid": "k" + str(i), "heading": "新结构" + str(i)}
            for i in range(3)
        ]
    return [
        {"id": str(i), "name": "标题" + str(i), "body": "b"} for i in range(3)
    ]


def test_new306_feed_path_pauses_on_required_drift(client, monkeypatch):
    """发布路径集成：确认基线后上游必要字段消失 → 写暂停（Feed 只出
    last-known-good + 诚实暂停状态）；探测仍坏 → 409 保持暂停；上游
    换新结构 → 用户确认新映射恢复并重立基线。"""
    import lumirss.routers.api_sources as sources_routes
    import lumirss.routers.new306_schema_pause as pause_routes

    monkeypatch.setattr(sources_routes, "fetch_json", _fetch_upstream)
    monkeypatch.setattr(pause_routes, "fetch_json", _fetch_upstream)

    created = client.post(
        "/api/v1/api-sources",
        json={
            "name": "易变接口",
            "endpoint": "https://api.example.com/rel",
            "itemsExpr": "[*]",
            "fieldMap": {"id": "id", "title": "name", "body": "body"},
            "subscribe": False,
        },
    )
    assert created.status_code == 201, created.text
    source_uuid = created.json()["uuid"]
    atom_path = created.json()["atomPath"]

    assert client.get(atom_path).status_code == 200
    confirmed = client.post(f"/api/v1/api-sources/{source_uuid}/confirm-schema")
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["confirmed"] is True

    BOX["mode"] = "broken"
    stale = client.get(atom_path)
    assert stale.status_code == 200
    assert stale.headers.get("X-Lumi-Stale") == "1"
    status = client.get(f"/api/v1/api-sources/{source_uuid}/schema-pause").json()
    assert status["writePaused"] is True
    assert status["pauseReason"] and "body" in status["pauseReason"]

    BOX["mode"] = "empty"
    still_broken = client.post(
        f"/api/v1/api-sources/{source_uuid}/schema-resume", json={}
    )
    assert still_broken.status_code == 409
    assert (
        client.get(f"/api/v1/api-sources/{source_uuid}/schema-pause").json()[
            "writePaused"
        ]
        is True
    )

    BOX["mode"] = "new"
    resumed = client.post(
        f"/api/v1/api-sources/{source_uuid}/schema-resume",
        json={"fieldMap": {"id": "uid", "title": "heading", "body": "heading"}},
    )
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["resumed"] is True
    assert resumed.json()["baselineConfirmed"] is True
    final = client.get(f"/api/v1/api-sources/{source_uuid}/schema-pause").json()
    assert final["writePaused"] is False
    republished = client.get(atom_path)
    assert republished.status_code == 200
    assert "新结构" in republished.text


def test_new306_cross_user_isolated(ab_env):  # noqa: F811 — pytest 夹具注册
    """B 看不到 A 的暂停状态，也无法替 A 恢复。"""
    env = ab_env
    client = env["client"]
    a, b = env["a"], env["b"]
    created = client.post(
        "/api/v1/api-sources",
        headers=a,
        json={
            "name": "A 的易变源",
            "endpoint": "https://api.example.com/x",
            "itemsExpr": "[*]",
            "fieldMap": {"id": "id", "title": "t"},
            "subscribe": False,
        },
    )
    assert created.status_code == 201, created.text
    source_uuid = created.json()["uuid"]

    assert (
        client.get(
            f"/api/v1/api-sources/{source_uuid}/schema-pause", headers=b
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/api-sources/{source_uuid}/schema-resume", headers=b, json={}
        ).status_code
        == 404
    )
