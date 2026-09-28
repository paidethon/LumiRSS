"""NEW-227 章节级阅读计划（服务端）。

- 计划创建（1..100 章节；一篇一个 → 重复 409）；
- 进度 = 章节整数计数（done/pending/total + 分 session 桶），绝不只给
  「文章百分比」；
- 章节完成 set 语义（done_at 记账；取消完成回到 pending）；
- 章节分配到某一次阅读（sessionNo 1..52 / clearSession）；
- A/B 每用户隔离 + 校验（空标签/越界 sessionNo/不存在章节）。
"""

from fastapi.testclient import TestClient

from new2xx_ab import ab_env, seed_entry  # noqa: F811


def _create_plan(client: TestClient, headers: dict, ref: str, sections: list[dict]):
    return client.post(
        "/api/v1/reading/section-plans",
        json={"itemRef": ref, "sections": sections},
        headers=headers,
    )


def test_plan_create_progress_and_session_buckets(ab_env):  # noqa: F811
    client = ab_env["client"]
    ref = seed_entry(ab_env, "a", "long1", title="长文")
    made = _create_plan(
        client,
        ab_env["a"],
        ref,
        [
            {"label": "引言", "sessionNo": 1},
            {"label": "方法", "sessionNo": 1},
            {"label": "结果", "sessionNo": 2},
            {"label": "讨论"},
        ],
    )
    assert made.status_code == 201, made.text
    body = made.json()
    assert body["progress"]["totalSections"] == 4
    assert body["progress"]["doneSections"] == 0
    buckets = {
        (b["sessionNo"]): b for b in body["progress"]["bySession"]
    }
    assert buckets[1]["total"] == 2 and buckets[1]["done"] == 0
    assert buckets[2]["total"] == 1
    assert buckets[None]["total"] == 1  # 未分配桶（unassigned）

    # 一篇一个计划：重复 → 409。
    conflict = _create_plan(client, ab_env["a"], ref, [{"label": "再建"}])
    assert conflict.status_code == 409
    assert conflict.json()["error"]["type"] == "section_plan_conflict"


def test_section_done_set_semantics_and_progress(ab_env):  # noqa: F811
    client = ab_env["client"]
    ref = seed_entry(ab_env, "a", "long2", title="长文二")
    made = _create_plan(
        client,
        ab_env["a"],
        ref,
        [{"label": "第一部分"}, {"label": "第二部分", "sessionNo": 1}],
    )
    sections = made.json()["sections"]
    first_id = sections[0]["id"]

    done = client.post(
        f"/api/v1/reading/section-plan-sections/{first_id}/done",
        json={"done": True},
        headers=ab_env["a"],
    )
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "done" and done.json()["doneAt"]

    view = client.get(
        "/api/v1/reading/section-plans", params={"itemRef": ref}, headers=ab_env["a"]
    ).json()
    assert view["progress"]["doneSections"] == 1
    assert view["progress"]["pendingSections"] == 1

    # set 语义：取消完成 → pending、进度回落。
    undone = client.post(
        f"/api/v1/reading/section-plan-sections/{first_id}/done",
        json={"done": False},
        headers=ab_env["a"],
    )
    assert undone.json()["status"] == "pending"
    view = client.get(
        "/api/v1/reading/section-plans", params={"itemRef": ref}, headers=ab_env["a"]
    ).json()
    assert view["progress"]["doneSections"] == 0


def test_session_assignment_and_clear(ab_env):  # noqa: F811
    client = ab_env["client"]
    ref = seed_entry(ab_env, "a", "long3", title="长文三")
    made = _create_plan(
        client, ab_env["a"], ref, [{"label": "章节甲"}, {"label": "章节乙"}]
    )
    sections = made.json()["sections"]
    target = sections[1]["id"]

    moved = client.patch(
        f"/api/v1/reading/section-plan-sections/{target}",
        json={"sessionNo": 3},
        headers=ab_env["a"],
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["sessionNo"] == 3

    cleared = client.patch(
        f"/api/v1/reading/section-plan-sections/{target}",
        json={"clearSession": True},
        headers=ab_env["a"],
    )
    assert cleared.json()["sessionNo"] is None

    # 越界 sessionNo → 422。
    bad = client.patch(
        f"/api/v1/reading/section-plan-sections/{target}",
        json={"sessionNo": 53},
        headers=ab_env["a"],
    )
    assert bad.status_code == 422

    # 删除计划（连同章节）；再查 → 404。
    deleted = client.delete(
        "/api/v1/reading/section-plans", params={"itemRef": ref},
        headers=ab_env["a"],
    )
    assert deleted.status_code == 204
    gone = client.get(
        "/api/v1/reading/section-plans", params={"itemRef": ref}, headers=ab_env["a"]
    )
    assert gone.status_code == 404
    assert gone.json()["error"]["type"] == "section_plan_not_found"


def test_validation_and_ab_isolation(ab_env):  # noqa: F811
    client = ab_env["client"]
    ref = seed_entry(ab_env, "a", "long4", title="A 的长文")
    empty_label = _create_plan(client, ab_env["a"], ref, [{"label": "  "}])
    assert empty_label.status_code == 422
    assert empty_label.json()["error"]["type"] == "invalid_section_plan"
    no_sections = _create_plan(client, ab_env["a"], ref, [])
    assert no_sections.status_code == 422

    made = _create_plan(client, ab_env["a"], ref, [{"label": "只有 A 看到"}])
    section_id = made.json()["sections"][0]["id"]

    # B 看不到 A 的计划；操作 A 的章节 → 404。
    b_view = client.get(
        "/api/v1/reading/section-plans", params={"itemRef": ref}, headers=ab_env["b"]
    )
    assert b_view.status_code == 404
    b_touch = client.post(
        f"/api/v1/reading/section-plan-sections/{section_id}/done",
        json={"done": True},
        headers=ab_env["b"],
    )
    assert b_touch.status_code == 404

    # 不存在的章节 → 404。
    assert (
        client.post(
            "/api/v1/reading/section-plan-sections/ssec-nope/done",
            json={"done": True},
            headers=ab_env["a"],
        ).status_code
        == 404
    )
