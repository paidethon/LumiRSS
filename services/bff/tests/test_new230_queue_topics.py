"""NEW-230 队列重复主题提醒（服务端）。

- 主题标注是用户手动 set（空表清除；≤5 个/篇；去重、规范化）；
- 集中度报告：按主题聚合今日队列成员（itemCount/positions/minGap/
  segments），duplicatedTopics 单列；advisory note 明示「由你手动
  调换位置，服务端绝不自动重排」；
- 报告纯读取：重复 GET 不改变任何状态；
- A/B 每用户隔离（标注与报告都只在各自库）。
"""

from fastapi.testclient import TestClient

from new2xx_ab import seed_entry  # noqa: F811


def _seed_queue(client: TestClient, headers: dict, refs: list[str]) -> list[dict]:
    rows = []
    for ref in refs:
        made = client.post(
            "/api/v1/queue/today/items", json={"itemRef": ref}, headers=headers
        )
        assert made.status_code == 201, made.text
        rows.append(made.json())
    return rows


def _set_topics(client: TestClient, headers: dict, ref: str, topics: list[str]):
    return client.put(
        "/api/v1/queue/topics", json={"itemRef": ref, "topics": topics},
        headers=headers,
    )


def test_topics_set_get_and_report_concentration(ab_env):  # noqa: F811
    client = ab_env["client"]
    refs = [
        seed_entry(ab_env, "a", f"t{i}", title=f"文{i}") for i in range(4)
    ]
    rows = _seed_queue(client, ab_env["a"], refs)

    made = _set_topics(client, ab_env["a"], refs[0], ["AI", "隐私"])
    assert made.status_code == 200, made.text
    assert made.json()["topics"] == ["AI", "隐私"]
    _set_topics(client, ab_env["a"], refs[1], ["AI"])
    _set_topics(client, ab_env["a"], refs[2], ["AI"])
    _set_topics(client, ab_env["a"], refs[3], ["健身"])

    # get 单篇。
    one = client.get(
        "/api/v1/queue/topics", params={"itemRef": refs[0]}, headers=ab_env["a"]
    ).json()
    assert one["topics"] == ["AI", "隐私"]

    report = client.get("/api/v1/queue/topics/report", headers=ab_env["a"])
    assert report.status_code == 200, report.text
    body = report.json()
    assert body["advisory"] is True
    assert "手动决定" in body["note"]
    topics = {entry["topic"]: entry for entry in body["topics"]}
    assert topics["AI"]["itemCount"] == 3
    assert topics["AI"]["minGap"] == 1  # positions 1,2,3
    assert topics["隐私"]["itemCount"] == 1
    dup = {entry["topic"]: entry for entry in body["duplicatedTopics"]}
    assert set(dup) == {"AI"}

    # 报告纯读取：再取一次状态不变。
    again = client.get("/api/v1/queue/topics/report", headers=ab_env["a"]).json()
    assert again["topics"] == body["topics"]
    _ = rows


def test_set_topics_replaces_and_clears(ab_env):  # noqa: F811
    client = ab_env["client"]
    ref = seed_entry(ab_env, "a", "tset")
    _seed_queue(client, ab_env["a"], [ref])
    _set_topics(client, ab_env["a"], ref, ["旧主题", "另一个"])
    # set = 整体替换。
    replaced = _set_topics(client, ab_env["a"], ref, ["新主题"])
    assert replaced.json()["topics"] == ["新主题"]
    one = client.get(
        "/api/v1/queue/topics", params={"itemRef": ref}, headers=ab_env["a"]
    ).json()
    assert one["topics"] == ["新主题"]
    # 空表清除。
    cleared = _set_topics(client, ab_env["a"], ref, [])
    assert cleared.json()["topics"] == []
    # 重复主题去重 + 空白规范化。
    deduped = _set_topics(client, ab_env["a"], ref, ["同", "同", " 同 "])
    assert deduped.json()["topics"] == ["同"]


def test_validation(ab_env):  # noqa: F811
    client = ab_env["client"]
    ref = seed_entry(ab_env, "a", "tval")
    too_many = _set_topics(client, ab_env["a"], ref, ["一", "二", "三", "四", "五", "六"])
    # pydantic max_length=5 先拦（invalid_request）；store 层是第二道。
    assert too_many.status_code == 422
    too_long = _set_topics(client, ab_env["a"], ref, ["字" * 31])
    assert too_long.status_code == 422
    empty_topic = _set_topics(client, ab_env["a"], ref, ["  "])
    assert empty_topic.status_code == 422
    bad_ref = _set_topics(client, ab_env["a"], "nope", ["x"])
    assert bad_ref.status_code == 422


def test_ab_isolation(ab_env):  # noqa: F811
    client = ab_env["client"]
    ref_a = seed_entry(ab_env, "a", "tabc", title="A 的文")
    _seed_queue(client, ab_env["a"], [ref_a])
    _set_topics(client, ab_env["a"], ref_a, ["A 的主题"])

    # B 的单篇视图为空、报告为空。
    b_one = client.get(
        "/api/v1/queue/topics", params={"itemRef": ref_a}, headers=ab_env["b"]
    ).json()
    assert b_one["topics"] == []
    b_report = client.get("/api/v1/queue/topics/report", headers=ab_env["b"]).json()
    assert b_report["topics"] == [] and b_report["duplicatedTopics"] == []
