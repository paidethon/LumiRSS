"""NEW-259 结论变更记录 — 结论台账只追加，旧结论永不覆盖。

- 首次登记 old_text=null；再登记把旧结论、触发材料与原因存入台账；
- 当前结论 PUT 更新；history 完整可回看（不改写不删除）；
- 校验：空 text / 坏 triggerRefs / 超 50 条 → 422；未知项目 → 404；
- 隔离：A 的结论与台账对 B 404。
"""

import uuid

from fastapi.testclient import TestClient

from new2xx_ab import ab_env  # noqa: F401,F811


def _project(client: TestClient) -> dict:
    return client.post(
        "/api/v1/research/projects", json={"title": "结论项目"}
    ).json()


def test_new259_conclusion_history_preserves_old(client):  # noqa: F811
    """v1 → v2（带触发材料+原因）→ v3：台账 3 条、旧表述全保留、
    当前文本=最新、previousText 可核对。"""
    project = _project(client)
    base = f"/api/v1/research/projects/{project['id']}/conclusion"

    first = client.get(base).json()
    assert first["text"] is None and first["historyCount"] == 0

    v1 = client.put(base, json={"text": "初判：1934 年投产。"})
    assert v1.status_code == 200, v1.text
    assert v1.json()["previousText"] is None  # 首次登记

    ref = f"library:{uuid.uuid4()}"
    v2 = client.put(
        base,
        json={
            "text": "修正：以 1935 年验收为准。",
            "triggerRefs": [ref],
            "reason": "NEW-253 反例排除 1934 说",
        },
    )
    assert v2.status_code == 200, v2.text
    assert v2.json()["previousText"] == "初判：1934 年投产。"
    assert v2.json()["latestChange"]["triggerRefs"] == [ref]

    v3 = client.put(base, json={"text": "维持 1935 说，补充县志佐证。"})
    assert v3.status_code == 200

    current = client.get(base).json()
    assert current["text"].startswith("维持 1935 说")
    assert current["historyCount"] == 3

    history = client.get(f"{base}/history").json()
    assert history["historyCount"] == 3
    texts_new_to_old = [item["newText"] for item in history["items"]]
    assert texts_new_to_old[0] == current["text"]
    olds = {item["oldText"] for item in history["items"]}
    assert "初判：1934 年投产。" in olds  # 原结论可回看，未被覆盖
    assert history["items"][2]["oldText"] is None  # 首条台账诚实记 null
    trigger = [i for i in history["items"] if i["triggerRefs"]]
    assert trigger and trigger[0]["reason"] == "NEW-253 反例排除 1934 说"


def test_new259_validation_and_errors(client):  # noqa: F811
    """空 text → 422；非数组/空项/超量 triggerRefs → 422；未知项目 → 404。"""
    project = _project(client)
    base = f"/api/v1/research/projects/{project['id']}/conclusion"

    assert client.put(base, json={"text": " "}).status_code == 422
    assert (
        client.put(base, json={"text": "T", "triggerRefs": "not-a-list"}).status_code
        == 422
    )
    assert (
        client.put(base, json={"text": "T", "triggerRefs": [""]}).status_code == 422
    )
    assert (
        client.put(
            base, json={"text": "T", "triggerRefs": [f"library:{uuid.uuid4()}"] * 51}
        ).status_code
        == 422
    )
    assert (
        client.get("/api/v1/research/projects/missing-pid/conclusion").status_code
        == 404
    )
    assert (
        client.put(
            "/api/v1/research/projects/missing-pid/conclusion", json={"text": "T"}
        ).status_code
        == 404
    )


def test_new259_ab_isolation(ab_env):  # noqa: F811
    """A 的结论与变更台账对 B 不可见；B 不能改 A 的结论。"""
    client = ab_env["client"]
    project = client.post(
        "/api/v1/research/projects", json={"title": "A 结论"}, headers=ab_env["a"]
    ).json()
    base = f"/api/v1/research/projects/{project['id']}/conclusion"

    assert (
        client.put(base, json={"text": "A 的结论"}, headers=ab_env["a"]).status_code
        == 200
    )
    assert (
        client.get(base, headers=ab_env["b"]).status_code == 404
    )
    assert (
        client.put(base, json={"text": "B 乱改"}, headers=ab_env["b"]).status_code
        == 404
    )
    # A 的结论未被 B 触碰。
    assert (
        client.get(base, headers=ab_env["a"]).json()["text"] == "A 的结论"
    )
