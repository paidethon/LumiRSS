"""FIX-367: 资源 id 必须是规范整数字符串——非法 id 一律 422，不得经
Pydantic 宽松 coercion 命中他人/其他记录。

基线缺陷（pydantic v2 lax int）：路径参数 ``config_id: int`` 会把
``"01"`` / ``" 1"`` / ``"1.0"`` / ``"+1"`` 全部 coerce 成 1 —— 非规范的
id 文本照样命中同号记录（缓存键混淆 / 日志别名 / 越过规范化预期）。
修复后：仅 ``^(0|[1-9][0-9]*)$`` 形态可到达路由；其余 → 422 invalid_request。
"""

import pytest
from fastapi.testclient import TestClient

from lumirss.main import app

# GET /api/v1/gpt-digest/configs/{config_id}/feed：默认配置 id=1 恒存在，
# 适合做「同号命中」探针。
_MALFORMED_IDS = ["01", " 1", "1.0", "+1", "-1", "1.5", "0x1", "１"]


def test_canonical_id_still_resolves():
    with TestClient(app) as client:
        response = client.get("/api/v1/gpt-digest/configs/1/feed")
    assert response.status_code == 200
    assert "atomPath" in response.json()


@pytest.mark.parametrize("raw", _MALFORMED_IDS)
def test_malformed_id_text_is_rejected_not_coerced(raw):
    """'01'、' 1'、'1.0'、'+1' 此前都被 coerce 成 1 并 200 命中配置。"""
    with TestClient(app) as client:
        response = client.get(f"/api/v1/gpt-digest/configs/{raw}/feed")
    assert response.status_code == 422, (raw, response.status_code)
    assert response.json()["error"]["type"] == "invalid_request"


def test_malformed_id_never_mutates_the_coerced_record():
    """真实记录在场：'0001' 此前 coerce 成规则 1 并改写它的 value；
    修复后必须 422 且记录原样。"""
    with TestClient(app) as client:
        ws = client.post(
            "/api/v1/workspaces", json={"name": "ID 规范"}
        ).json()["id"]
        rule = client.post(
            "/api/v1/inbox/rules",
            json={
                "field": "title",
                "operator": "contains",
                "value": "规范",
                "targetWorkspaceId": ws,
            },
        ).json()
        padded_id = f"{rule['id']:04d}"  # 1 -> "0001"
        patched = client.patch(
            f"/api/v1/inbox/rules/{padded_id}", json={"value": "改写"}
        )
        assert patched.status_code == 422
        listing = client.get("/api/v1/inbox/rules").json()["items"]
        assert [r["value"] for r in listing] == ["规范"]
