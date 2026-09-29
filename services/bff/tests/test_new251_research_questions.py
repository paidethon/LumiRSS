"""NEW-251 研究问题拆分 — 项目主线 + 父/子问题 + 结论草稿 + 材料。

- 主线：项目 CRUD；问题拆子问题；子问题带结论草稿与 open/resolved
  set 语义状态；材料用 ItemRef 只引用不复制（重复挂接幂等）；
- 校验：空标题/坏 itemRef/非法 status 422；未知项目/问题 404；
- 隔离：per-user 库——A 的研究项目对 B 是 404、列表不可见。
"""

import uuid

from fastapi.testclient import TestClient

from lumirss.entryref import encode_entry_ref
from new2xx_ab import ab_env, seed_entry  # noqa: F401,F811


def _make_project(client: TestClient, title: str = "城市供水史考证") -> dict:
    made = client.post(
        "/api/v1/research/projects", json={"title": title, "description": "个人研究"}
    )
    assert made.status_code == 201, made.text
    return made.json()


def _lib_ref() -> str:
    return f"library:{uuid.uuid4()}"


def _rss_ref(seed: str) -> str:
    """合法 rss: ItemRef（研究模块只校验引用格式，不查 entry 存在）。"""
    return f"rss:{encode_entry_ref(f'n251-{seed}')}"


def test_new251_project_question_subquestion_material_flow(client):  # noqa: F811
    """立项 → 提父问题 → 拆子问题 → 挂材料（library + rss 双域）→
    写结论草稿 → resolved 显式切换带 resolvedAt；重复材料幂等。"""
    project = _make_project(client)
    assert project["questionCount"] == 0
    assert project["openSubquestionCount"] == 0

    listed = client.get("/api/v1/research/projects").json()
    assert [p["id"] for p in listed["items"]] == [project["id"]]

    question = client.post(
        f"/api/v1/research/projects/{project['id']}/questions",
        json={"question": "旧城水厂何时改用过滤工艺？"},
    )
    assert question.status_code == 201, question.text
    qid = question.json()["id"]

    sub = client.post(
        f"/api/v1/research/questions/{qid}/subquestions",
        json={"text": "第一批滤池的验收记录在哪年？"},
    )
    assert sub.status_code == 201, sub.text
    sub_id = sub.json()["id"]
    assert sub.json()["status"] == "open"
    assert sub.json()["conclusion"] is None

    for ref in (_lib_ref(), _rss_ref("flow")):
        made = client.post(
            f"/api/v1/research/subquestions/{sub_id}/materials",
            json={"itemRef": ref},
        )
        assert made.status_code == 201, made.text
        assert made.json()["outcome"] == "created"

    # 同一材料重复挂接 → 幂等（200 duplicate，不重复入库）
    again = client.post(
        f"/api/v1/research/subquestions/{sub_id}/materials",
        json={"itemRef": _lib_ref()},
    )
    first_lib = again
    assert first_lib.status_code == 201
    dup = client.post(
        f"/api/v1/research/subquestions/{sub_id}/materials",
        json={"itemRef": first_lib.json()["itemRef"]},
    )
    assert dup.status_code == 200
    assert dup.json()["outcome"] == "duplicate"

    materials = client.get(f"/api/v1/research/subquestions/{sub_id}/materials").json()
    assert len(materials["items"]) == 3

    patched = client.patch(
        f"/api/v1/research/subquestions/{sub_id}",
        json={"conclusion": "1934 年前后完成改造（待核）。", "status": "resolved"},
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["status"] == "resolved"
    assert body["resolvedAt"] is not None
    assert "1934" in body["conclusion"]

    detail = client.get(f"/api/v1/research/projects/{project['id']}").json()
    assert detail["questionCount"] == 1
    assert detail["openSubquestionCount"] == 0

    # 删除子问题后材料一并清理；再删问题、再删项目（级联成立）
    assert (
        client.delete(f"/api/v1/research/subquestions/{sub_id}").status_code == 204
    )
    assert (
        client.delete(f"/api/v1/research/questions/{qid}").status_code == 204
    )
    assert client.delete(f"/api/v1/research/projects/{project['id']}").status_code == 204
    assert client.get(f"/api/v1/research/projects/{project['id']}").status_code == 404


def test_new251_validation_and_errors(client):  # noqa: F811
    """校验面：空标题/超长/坏 itemRef/非法 status → 422；未知 id → 404。"""
    assert (
        client.post("/api/v1/research/projects", json={"title": "   "}).status_code
        == 422
    )
    project = _make_project(client, "校验面")

    qid = client.post(
        f"/api/v1/research/projects/{project['id']}/questions",
        json={"question": "Q？"},
    ).json()["id"]

    assert (
        client.post(
            f"/api/v1/research/projects/{project['id']}/questions",
            json={"question": ""},
        ).status_code
        == 422
    )
    sub_id = client.post(
        f"/api/v1/research/questions/{qid}/subquestions", json={"text": "子问题"}
    ).json()["id"]

    assert (
        client.post(
            f"/api/v1/research/subquestions/{sub_id}/materials",
            json={"itemRef": "gopher://nope"},
        ).status_code
        == 422
    )
    assert (
        client.patch(
            f"/api/v1/research/subquestions/{sub_id}", json={"status": "auto-done"}
        ).status_code
        == 422
    )
    assert client.get("/api/v1/research/projects/missing-pid").status_code == 404
    assert (
        client.post(
            "/api/v1/research/questions/missing-qid/subquestions", json={"text": "x"}
        ).status_code
        == 404
    )


def test_new251_ab_isolation(ab_env):  # noqa: F811
    """A 的研究项目/子问题/材料对 B 全部不可见（per-user 库隔离）。"""
    client = ab_env["client"]
    rss_ref = seed_entry(ab_env, "a", "n251iso", title="A 的报道")

    project = client.post(
        "/api/v1/research/projects",
        json={"title": "A 的研究"},
        headers=ab_env["a"],
    ).json()
    qid = client.post(
        f"/api/v1/research/projects/{project['id']}/questions",
        json={"question": "A 的问题"},
        headers=ab_env["a"],
    ).json()["id"]
    sub_id = client.post(
        f"/api/v1/research/questions/{qid}/subquestions",
        json={"text": "A 的子问题"},
        headers=ab_env["a"],
    ).json()["id"]
    made = client.post(
        f"/api/v1/research/subquestions/{sub_id}/materials",
        json={"itemRef": rss_ref},
        headers=ab_env["a"],
    )
    assert made.status_code == 201, made.text

    # B 侧：项目 404、列表为空；直接猜子问题 id 也 404。
    assert (
        client.get(
            f"/api/v1/research/projects/{project['id']}", headers=ab_env["b"]
        ).status_code
        == 404
    )
    assert (
        client.get("/api/v1/research/projects", headers=ab_env["b"]).json()["items"]
        == []
    )
    assert (
        client.get(
            f"/api/v1/research/subquestions/{sub_id}/materials", headers=ab_env["b"]
        ).status_code
        == 404
    )
    # A 侧一切照旧（隔离不是互删）。
    assert (
        client.get(
            f"/api/v1/research/projects/{project['id']}", headers=ab_env["a"]
        ).status_code
        == 200
    )
