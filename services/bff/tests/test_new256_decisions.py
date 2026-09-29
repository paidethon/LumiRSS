"""NEW-256 研究决策记录 — 基于材料作个人决策 + 只追加 followups。

- 登记：decision + basis + 依据材料（ItemRef 列表去重）；
- 演变：followups 只追加（outcome 结果 / revision 修正原因），决策行
  本身不提供改写（无 PATCH 路径——诚实边界）；
- 隔离：A 的决策对 B 404。
"""

import uuid

from fastapi.testclient import TestClient

from new2xx_ab import ab_env  # noqa: F401,F811


def _project(client: TestClient) -> dict:
    return client.post(
        "/api/v1/research/projects", json={"title": "决策项目"}
    ).json()


def test_new256_decision_with_materials_and_followups(client):  # noqa: F811
    """登记（带依据材料）→ 追加 outcome → 追加 revision → 全程可回看。"""
    project = _project(client)
    ref = f"library:{uuid.uuid4()}"
    made = client.post(
        f"/api/v1/research/projects/{project['id']}/decisions",
        json={
            "decision": "订阅源 A 改为每周人工复核一次",
            "basis": "误报率上升，且抽查发现两处旧闻重发",
            "itemRefs": [ref, ref],  # 重复项去重
        },
    )
    assert made.status_code == 201, made.text
    decision = made.json()
    assert [m["itemRef"] for m in decision["materials"]] == [ref]

    outcome = client.post(
        f"/api/v1/research/decisions/{decision['id']}/followups",
        json={"kind": "outcome", "text": "两周试行后误报明显下降"},
    )
    assert outcome.status_code == 201, outcome.text

    revision = client.post(
        f"/api/v1/research/decisions/{decision['id']}/followups",
        json={"kind": "revision", "text": "改为隔周复核（人力限制）"},
    )
    assert revision.status_code == 201

    listed = client.get(
        f"/api/v1/research/projects/{project['id']}/decisions"
    ).json()
    body = listed["items"][0]
    kinds = [f["kind"] for f in body["followUps"]]
    assert kinds == ["outcome", "revision"]  # 按时间序可回看

    # 补挂材料。
    extra = client.post(
        f"/api/v1/research/decisions/{decision['id']}/materials",
        json={"itemRef": f"library:{uuid.uuid4()}"},
    )
    assert extra.status_code == 201 and extra.json()["outcome"] == "created"


def test_new256_validation_and_append_only(client):  # noqa: F811
    """空 decision → 422；坏 kind / 坏 ref / 数组含空项 → 422；
    决策行不改写（无 PATCH → 405）；未知决策 → 404。"""
    project = _project(client)
    base = f"/api/v1/research/projects/{project['id']}/decisions"

    assert client.post(base, json={"decision": " "}).status_code == 422
    assert (
        client.post(base, json={"decision": "D", "itemRefs": "not-a-list"}).status_code
        == 422
    )
    assert (
        client.post(base, json={"decision": "D", "itemRefs": [""]}).status_code == 422
    )
    decision = client.post(base, json={"decision": "D"}).json()

    assert (
        client.post(
            f"/api/v1/research/decisions/{decision['id']}/followups",
            json={"kind": "note", "text": "x"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/v1/research/decisions/{decision['id']}/materials",
            json={"itemRef": "bad"},
        ).status_code
        == 422
    )
    # 决策行不改写：/decisions/{id} 上没有 PATCH 路径（诚实的 404/405）。
    assert (
        client.patch(
            f"/api/v1/research/decisions/{decision['id']}",
            json={"decision": "改写"},
        ).status_code
        in (404, 405)
    )
    assert (
        client.get(
            "/api/v1/research/decisions/missing-did/followups"
        ).status_code
        in (404, 405)
    )


def test_new256_ab_isolation(ab_env):  # noqa: F811
    """A 的决策与 followups 对 B 不可见。"""
    client = ab_env["client"]
    project = client.post(
        "/api/v1/research/projects", json={"title": "A 决策"}, headers=ab_env["a"]
    ).json()
    decision_id = client.post(
        f"/api/v1/research/projects/{project['id']}/decisions",
        json={"decision": "A 的决策"},
        headers=ab_env["a"],
    ).json()["id"]

    assert (
        client.get(
            f"/api/v1/research/projects/{project['id']}/decisions",
            headers=ab_env["b"],
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/research/decisions/{decision_id}/followups",
            json={"kind": "outcome", "text": "B 的结果"},
            headers=ab_env["b"],
        ).status_code
        == 404
    )
    # A 追加照常。
    assert (
        client.post(
            f"/api/v1/research/decisions/{decision_id}/followups",
            json={"kind": "outcome", "text": "A 的结果"},
            headers=ab_env["a"],
        ).json()["kind"]
        == "outcome"
    )
