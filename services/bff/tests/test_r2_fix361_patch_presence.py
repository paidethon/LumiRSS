"""FIX-361: PATCH 必须尊重字段存在语义——局部编辑不得静默丢字段。

全库约定（逐 store 核对过）：Optional 字段 None = 未提供 → 合并保留现值；
不存在「model_dump() 整体覆盖把未提供字段写成 NULL」的路径（BASELINE_OK
部分）。真实缺陷在 inbox 规则 PATCH：路由层 ``model_dump()`` 产出 camel
契约键 ``targetWorkspaceId``，而 store 合同读 ``target_workspace_id`` ——
键名不匹配导致该字段被**静默丢弃**（200 但值不变）。
"""

import pytest
from fastapi.testclient import TestClient

from lumirss.main import app


@pytest.fixture()
def client():
    with TestClient(app) as test_client:
        yield test_client


def _make_rule(client, ws_id: str, value: str = "周报") -> dict:
    response = client.post(
        "/api/v1/inbox/rules",
        json={
            "field": "title",
            "operator": "contains",
            "value": value,
            "targetWorkspaceId": ws_id,
        },
    )
    assert response.status_code in (200, 201)
    return response.json()


def test_patch_target_workspace_id_is_applied(client):
    """此前 model_dump 键（targetWorkspaceId）与 store 合同键
    （target_workspace_id）不匹配 → PATCH 改目标工作区被静默忽略。"""
    ws_a = client.post("/api/v1/workspaces", json={"name": "收件A"}).json()["id"]
    ws_b = client.post("/api/v1/workspaces", json={"name": "收件B"}).json()["id"]
    rule = _make_rule(client, ws_a)
    patched = client.patch(
        f"/api/v1/inbox/rules/{rule['id']}", json={"targetWorkspaceId": ws_b}
    )
    assert patched.status_code == 200
    assert patched.json()["targetWorkspaceId"] == ws_b


def test_patch_single_field_leaves_others_intact(client):
    """PATCH {一个字段} 其余字段原样保留（局部编辑不擦除）。"""
    ws_a = client.post("/api/v1/workspaces", json={"name": "保留A"}).json()["id"]
    rule = _make_rule(client, ws_a, value="旧词")
    patched = client.patch(
        f"/api/v1/inbox/rules/{rule['id']}", json={"value": "新词"}
    )
    assert patched.status_code == 200
    body = patched.json()
    assert body["value"] == "新词"
    assert body["field"] == "title"
    assert body["operator"] == "contains"
    assert body["targetWorkspaceId"] == ws_a
    assert body["enabled"] is True


def test_patch_enabled_false_still_toggles(client):
    """既有行为回归保护：显式 false 必须生效（None=未提供语义不变）。"""
    ws = client.post("/api/v1/workspaces", json={"name": "开关"}).json()["id"]
    rule = _make_rule(client, ws)
    patched = client.patch(
        f"/api/v1/inbox/rules/{rule['id']}", json={"enabled": False}
    )
    assert patched.status_code == 200
    assert patched.json()["enabled"] is False
