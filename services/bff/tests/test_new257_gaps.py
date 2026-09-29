"""NEW-257 资料缺口任务 — 需要但尚未找到的资料类型。

- 登记：description + materialType（可空的类型标签）；
- 关闭是显式动作：必须挂上找到的材料（itemRef 必填）；已关闭再
  close → 422；reopen 可带原因（保留曾关闭痕迹，不抹历史）；
- 隔离：A 的缺口对 B 404。
"""

import uuid

from fastapi.testclient import TestClient

from new2xx_ab import ab_env  # noqa: F401,F811


def _project(client: TestClient) -> dict:
    return client.post(
        "/api/v1/research/projects", json={"title": "缺口项目"}
    ).json()


def _ref() -> str:
    return f"library:{uuid.uuid4()}"


def test_new257_gap_open_close_reopen(client):  # noqa: F811
    """开缺口 → 关闭（挂材料 + 说明）→ 重复关闭 422 → reopen（留原因）
    → 再关闭。"""
    project = _project(client)
    made = client.post(
        f"/api/v1/research/projects/{project['id']}/gaps",
        json={"description": "1936 年市政年报原件扫描件", "materialType": "档案影印"},
    )
    assert made.status_code == 201, made.text
    gap = made.json()
    assert gap["status"] == "open"

    closed = client.post(
        f"/api/v1/research/gaps/{gap['id']}/close",
        json={"itemRef": _ref(), "note": "在档案馆数据库找到"},
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["status"] == "closed"
    assert closed.json()["closedItemRef"] is not None

    dup = client.post(
        f"/api/v1/research/gaps/{gap['id']}/close", json={"itemRef": _ref()}
    )
    assert dup.status_code == 422  # 诚实拒绝，不幂等假成功

    reopened = client.post(
        f"/api/v1/research/gaps/{gap['id']}/reopen",
        json={"reason": "发现挂的是另一年份"},
    )
    assert reopened.status_code == 200, reopened.text
    reopened_body = reopened.json()
    assert reopened_body["status"] == "open"
    assert reopened_body["closedItemRef"] is None
    assert "重开原因：发现挂的是另一年份" in reopened_body["closeNote"]

    reclosed = client.post(
        f"/api/v1/research/gaps/{gap['id']}/close",
        json={"itemRef": _ref(), "note": "换成正确年份卷宗"},
    )
    assert reclosed.json()["status"] == "closed"

    listed = client.get(f"/api/v1/research/projects/{project['id']}/gaps").json()
    assert listed["openCount"] == 0 and listed["closedCount"] == 1


def test_new257_validation_and_errors(client):  # noqa: F811
    """空 description → 422；关闭不带材料/坏 ref → 422；open 再 reopen
    → 422；未知缺口 → 404。"""
    project = _project(client)
    base = f"/api/v1/research/projects/{project['id']}/gaps"

    assert client.post(base, json={"description": " "}).status_code == 422
    gap = client.post(base, json={"description": "缺一份对照表"}).json()

    assert (
        client.post(
            f"/api/v1/research/gaps/{gap['id']}/close", json={"itemRef": "bad-ref"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/v1/research/gaps/{gap['id']}/reopen", json={}
        ).status_code
        == 422
    )
    assert client.delete(f"/api/v1/research/gaps/{gap['id']}").status_code == 204
    assert (
        client.post(
            "/api/v1/research/gaps/missing-gap/close", json={"itemRef": _ref()}
        ).status_code
        == 404
    )


def test_new257_ab_isolation(ab_env):  # noqa: F811
    """A 的缺口对 B 不可见；B 不能替 A 关缺口。"""
    client = ab_env["client"]
    project = client.post(
        "/api/v1/research/projects", json={"title": "A 缺口"}, headers=ab_env["a"]
    ).json()
    gap_id = client.post(
        f"/api/v1/research/projects/{project['id']}/gaps",
        json={"description": "A 缺的材料", "materialType": "报刊"},
        headers=ab_env["a"],
    ).json()["id"]

    assert (
        client.get(
            f"/api/v1/research/projects/{project['id']}/gaps",
            headers=ab_env["b"],
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/research/gaps/{gap_id}/close",
            json={"itemRef": _ref()},
            headers=ab_env["b"],
        ).status_code
        == 404
    )
    # A 自己关闭照常。
    assert (
        client.post(
            f"/api/v1/research/gaps/{gap_id}/close",
            json={"itemRef": _ref()},
            headers=ab_env["a"],
        ).json()["status"]
        == "closed"
    )
