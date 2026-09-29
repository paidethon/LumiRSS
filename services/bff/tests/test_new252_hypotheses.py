"""NEW-252 假设登记册 — 待检验假设 + 可支持/可反驳条件 + 材料分配。

- 登记门槛：statement + supportCondition + refuteCondition 三栏必填
  （缺一即 422——可反驳性是登记门槛）；
- 状态 proposed → supported/refuted/retired 全部用户显式 PATCH；
- 材料分配：support / refute 两侧挂 ItemRef，同侧幂等、可同材料双挂；
- 隔离：A 的假设对 B 404。
"""

import uuid

from fastapi.testclient import TestClient

from lumirss.entryref import encode_entry_ref
from new2xx_ab import ab_env  # noqa: F401,F811


def _project(client: TestClient) -> dict:
    made = client.post("/api/v1/research/projects", json={"title": "假设项目"})
    assert made.status_code == 201, made.text
    return made.json()


def _ref() -> str:
    return f"library:{uuid.uuid4()}"


def test_new252_hypothesis_lifecycle_and_sides(client):  # noqa: F811
    """登记 → 双侧挂材料 → 状态裁决 supported → 材料视图带侧别。"""
    project = _project(client)
    made = client.post(
        f"/api/v1/research/projects/{project['id']}/hypotheses",
        json={
            "statement": "水厂改造先于市政档案记载发生",
            "supportCondition": "找到早于 1935 的施工照片",
            "refuteCondition": "1936 年图纸仍标「原设计」",
        },
    )
    assert made.status_code == 201, made.text
    hyp = made.json()
    assert hyp["status"] == "proposed"
    hid = hyp["id"]

    ref = _ref()
    support = client.post(
        f"/api/v1/research/hypotheses/{hid}/materials",
        json={"itemRef": ref, "side": "support", "note": "照片底片编号"},
    )
    assert support.status_code == 201, support.text
    assert support.json()["outcome"] == "created"
    # 同侧重复 → 幂等；同材料挂另一侧 → 允许（用户自己判断）
    dup = client.post(
        f"/api/v1/research/hypotheses/{hid}/materials",
        json={"itemRef": ref, "side": "support"},
    )
    assert dup.status_code == 200 and dup.json()["outcome"] == "duplicate"
    cross = client.post(
        f"/api/v1/research/hypotheses/{hid}/materials",
        json={"itemRef": ref, "side": "refute"},
    )
    assert cross.status_code == 201

    listed = client.get(
        f"/api/v1/research/projects/{project['id']}/hypotheses"
    ).json()
    materials = listed["items"][0]["materials"]
    assert sorted(m["side"] for m in materials) == ["refute", "support"]

    # rss 引用同样可挂
    rss_made = client.post(
        f"/api/v1/research/hypotheses/{hid}/materials",
        json={"itemRef": f"rss:{encode_entry_ref('n252-rss')}", "side": "support"},
    )
    assert rss_made.status_code == 201

    verdict = client.patch(
        f"/api/v1/research/hypotheses/{hid}", json={"status": "supported"}
    )
    assert verdict.status_code == 200, verdict.text
    assert verdict.json()["status"] == "supported"


def test_new252_validation_and_errors(client):  # noqa: F811
    """缺可反驳条件 → 422；坏 side / 坏 status / 坏 itemRef → 422；
    未知假设 → 404。"""
    project = _project(client)
    base = f"/api/v1/research/projects/{project['id']}/hypotheses"
    assert (
        client.post(
            base, json={"statement": "S", "supportCondition": "A"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            base,
            json={"statement": "S", "supportCondition": "A", "refuteCondition": " "},
        ).status_code
        == 422
    )
    hid = client.post(
        base,
        json={"statement": "S", "supportCondition": "A", "refuteCondition": "B"},
    ).json()["id"]

    assert (
        client.post(
            f"/api/v1/research/hypotheses/{hid}/materials",
            json={"itemRef": _ref(), "side": "left"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/v1/research/hypotheses/{hid}/materials",
            json={"itemRef": "not-a-ref", "side": "support"},
        ).status_code
        == 422
    )
    assert (
        client.patch(
            f"/api/v1/research/hypotheses/{hid}", json={"status": "proven"}
        ).status_code
        == 422
    )
    assert (
        client.patch(
            "/api/v1/research/hypotheses/missing-hid", json={"status": "retired"}
        ).status_code
        == 404
    )
    # 删除后从项目列表消失
    assert client.delete(f"/api/v1/research/hypotheses/{hid}").status_code == 204
    remaining = client.get(
        f"/api/v1/research/projects/{project['id']}/hypotheses"
    ).json()
    assert remaining["items"] == []


def test_new252_ab_isolation(ab_env):  # noqa: F811
    """A 的假设与材料分配对 B 不可见；A 的裁决不影响 B。"""
    client = ab_env["client"]
    project = client.post(
        "/api/v1/research/projects", json={"title": "A 假设"}, headers=ab_env["a"]
    ).json()
    hid = client.post(
        f"/api/v1/research/projects/{project['id']}/hypotheses",
        json={
            "statement": "A 的假设",
            "supportCondition": "A1",
            "refuteCondition": "A2",
        },
        headers=ab_env["a"],
    ).json()["id"]

    assert (
        client.get(
            f"/api/v1/research/projects/{project['id']}/hypotheses",
            headers=ab_env["b"],
        ).status_code
        == 404
    )
    # B 直接对 A 的假设做裁决 → 404（不是 B 自己的行）。
    assert (
        client.patch(
            f"/api/v1/research/hypotheses/{hid}",
            json={"status": "refuted"},
            headers=ab_env["b"],
        ).status_code
        == 404
    )
    # A 正常裁决
    assert (
        client.patch(
            f"/api/v1/research/hypotheses/{hid}",
            json={"status": "refuted"},
            headers=ab_env["a"],
        ).json()["status"]
        == "refuted"
    )
