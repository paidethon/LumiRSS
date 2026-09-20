"""F076 图谱命名视图 — 保存/恢复往返、覆盖 409 流、载荷校验、
重启持久、删除。"""

import asyncio

from lumirss.graph_views_store import (
    GraphViewExists,
    GraphViewStore,
)
from lumirss.main import app

LAYOUT = {"tag:1": {"x": 10.5, "y": -2}, "tag:2": {"x": 0, "y": 0}}
FILTERS = {"scope": "tag:1", "tablePreferred": False}


def run(coroutine):
    return asyncio.run(coroutine)


def test_f076_crud_roundtrip_and_overwrite_flow(client):
    db = app.state.db
    store = GraphViewStore(db)

    # 创建
    view = run(store.create("我的布局", LAYOUT, FILTERS, "tag:1"))
    assert view["name"] == "我的布局"
    assert view["layout"] == LAYOUT
    assert view["filters"] == FILTERS
    assert view["focusNode"] == "tag:1"

    # 同名未确认覆盖 → 409 语义（GraphViewExists）
    import pytest

    with pytest.raises(GraphViewExists):
        run(store.create("我的布局", {}, {}, None))
    # 显式 overwrite → 覆盖更新（不新增行）
    overwritten = run(store.create("我的布局", {}, {"scope": "all"}, None, overwrite=True))
    assert overwritten["id"] == view["id"]
    assert overwritten["filters"] == {"scope": "all"}
    listing = run(store.list_views())
    assert len([v for v in listing if v["name"] == "我的布局"]) == 1

    # 路由：同名再建（无 overwrite）→ 409 graph_view_exists
    resp = client.post(
        "/api/v1/graph/views",
        json={"name": "我的布局", "layout": {}, "filters": {}},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["type"] == "graph_view_exists"
    # 路由：overwrite=true → 200
    resp2 = client.post(
        "/api/v1/graph/views",
        json={"name": "我的布局", "layout": LAYOUT, "filters": FILTERS, "overwrite": True},
    )
    assert resp2.status_code == 200
    # 路由：列表
    names = [v["name"] for v in client.get("/api/v1/graph/views").json()["items"]]
    assert names == ["我的布局"]

    # 删除 → 404 再删
    assert client.delete(f"/api/v1/graph/views/{view['id']}").status_code == 204
    assert client.delete(f"/api/v1/graph/views/{view['id']}").status_code == 404


def test_f076_validation_bounds_and_restart_persistence(client):
    db = app.state.db
    store = GraphViewStore(db)

    # 载荷校验：空名 / 超长名 / 超 200 节点 / 非法位置
    import pytest

    from lumirss.graph_views_store import GraphViewInvalid

    with pytest.raises(GraphViewInvalid):
        run(store.create("   ", {}, None))
    with pytest.raises(GraphViewInvalid):
        run(store.create("x" * 51, {}, None))
    with pytest.raises(GraphViewInvalid):
        run(store.create("巨大布局", {f"n{i}": {"x": 0, "y": 0} for i in range(201)}, None))
    with pytest.raises(GraphViewInvalid):
        run(store.create("坏位置", {"n": {"x": "left", "y": 0}}, None))

    # 重启持久：同一 DB 重新进入 TestClient 后视图仍在
    view = run(store.create("持久布局", LAYOUT, FILTERS, None))
    from fastapi.testclient import TestClient

    with TestClient(app) as client2:
        client2.app.state.db = db
        items = client2.get("/api/v1/graph/views").json()["items"]
        match = next(v for v in items if v["id"] == view["id"])
        assert match["layout"] == LAYOUT
        assert match["name"] == "持久布局"
