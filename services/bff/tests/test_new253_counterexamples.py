"""NEW-253 反例收集视图 — 冲突证据单独立项收集 + 显式处理。

- 收集：excerpt 必填，出处可后补（attach_source）；
- 处理：resolve 必须回答 conclusionAdjusted + resolutionNote；
  handled 重复 resolve → 422（不覆盖第一次处理说明）；
- 边界：本模块绝不代用户改项目结论（那走 NEW-259）；
- 隔离：A 的反例对 B 404。
"""

import uuid

from fastapi.testclient import TestClient

from new2xx_ab import ab_env  # noqa: F401,F811


def _project(client: TestClient) -> dict:
    return client.post(
        "/api/v1/research/projects", json={"title": "反例项目"}
    ).json()


def _ref() -> str:
    return f"library:{uuid.uuid4()}"


def test_new253_counterexample_collect_resolve(client):  # noqa: F811
    """先记证据（无出处）→ 后补出处 → resolve（结论未调整）→ 过滤视图。"""
    project = _project(client)
    made = client.post(
        f"/api/v1/research/projects/{project['id']}/counterexamples",
        json={"excerpt": "「1933 年已有滤池运行」——与现有结论冲突", "note": "报纸影印件"},
    )
    assert made.status_code == 201, made.text
    body = made.json()
    assert body["status"] == "unhandled"
    assert body["itemRef"] is None
    cid = body["id"]

    attached = client.post(
        f"/api/v1/research/counterexamples/{cid}/source",
        json={"itemRef": _ref()},
    )
    assert attached.status_code == 200, attached.text
    assert attached.json()["itemRef"] is not None

    resolved = client.post(
        f"/api/v1/research/counterexamples/{cid}/resolve",
        json={"conclusionAdjusted": False, "resolutionNote": "影印件年份系排印错误"},
    )
    assert resolved.status_code == 200, resolved.text
    resolved_body = resolved.json()
    assert resolved_body["status"] == "handled"
    assert resolved_body["conclusionAdjusted"] is False
    assert resolved_body["resolvedAt"] is not None

    # handled 再 resolve → 422（不覆盖第一次处理说明）
    again = client.post(
        f"/api/v1/research/counterexamples/{cid}/resolve",
        json={"conclusionAdjusted": True, "resolutionNote": "改口"},
    )
    assert again.status_code == 422
    kept = client.get(
        f"/api/v1/research/projects/{project['id']}/counterexamples"
    ).json()
    assert kept["items"][0]["resolutionNote"] == "影印件年份系排印错误"

    # 第二条保持 unhandled；按状态过滤
    client.post(
        f"/api/v1/research/projects/{project['id']}/counterexamples",
        json={"excerpt": "第二条冲突证据"},
    )
    unhandled = client.get(
        f"/api/v1/research/projects/{project['id']}/counterexamples",
        params={"status": "unhandled"},
    ).json()
    assert unhandled["unhandledCount"] == 1 and len(unhandled["items"]) == 1
    handled = client.get(
        f"/api/v1/research/projects/{project['id']}/counterexamples",
        params={"status": "handled"},
    ).json()
    assert handled["handledCount"] == 1


def test_new253_validation_and_errors(client):  # noqa: F811
    """空 excerpt → 422；坏 status 过滤/坏出处/非布尔 adjusted → 422；
    未知反例 → 404。"""
    project = _project(client)
    base = f"/api/v1/research/projects/{project['id']}/counterexamples"

    assert client.post(base, json={"excerpt": " "}).status_code == 422
    cid = client.post(base, json={"excerpt": "证据"}).json()["id"]

    assert (
        client.get(base, params={"status": "done"}).status_code == 422
    )
    assert (
        client.post(
            f"/api/v1/research/counterexamples/{cid}/source",
            json={"itemRef": "ftp://bad"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/v1/research/counterexamples/{cid}/resolve",
            json={"conclusionAdjusted": "maybe", "resolutionNote": "n"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/research/counterexamples/missing-cid/resolve",
            json={"conclusionAdjusted": True, "resolutionNote": "n"},
        ).status_code
        == 404
    )
    assert (
        client.delete(
            f"/api/v1/research/counterexamples/{cid}"
        ).status_code
        == 204
    )
    assert client.get(base).json()["items"] == []


def test_new253_ab_isolation(ab_env):  # noqa: F811
    """A 收集的反例对 B 不可见；A 的处理不进 B 的视图。"""
    client = ab_env["client"]
    project = client.post(
        "/api/v1/research/projects", json={"title": "A 反例"}, headers=ab_env["a"]
    ).json()
    cid = client.post(
        f"/api/v1/research/projects/{project['id']}/counterexamples",
        json={"excerpt": "A 的冲突证据"},
        headers=ab_env["a"],
    ).json()["id"]

    assert (
        client.get(
            f"/api/v1/research/projects/{project['id']}/counterexamples",
            headers=ab_env["b"],
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/v1/research/counterexamples/{cid}/resolve",
            json={"conclusionAdjusted": True, "resolutionNote": "B 改口"},
            headers=ab_env["b"],
        ).status_code
        == 404
    )
    # A 自己正常处理。
    assert (
        client.post(
            f"/api/v1/research/counterexamples/{cid}/resolve",
            json={"conclusionAdjusted": False, "resolutionNote": "A 判定误读"},
            headers=ab_env["a"],
        ).json()["status"]
        == "handled"
    )
