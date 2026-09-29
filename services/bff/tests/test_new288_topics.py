"""NEW-288 跨期主题追踪 — 主题锚点 / 期次位置 / 后续更新链。"""

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册
from new281_helpers import confirm, create_issue, iso, seed


def _attach(client, headers, topic_id, issue_id, item_id):
    return client.post(
        f"/api/v1/briefings/topics/{topic_id}/entries",
        json={"briefingId": issue_id, "itemId": item_id},
        headers=headers,
    )


def test_topic_chain_across_issues(ab_env):  # noqa: F811
    """跨期链：期次位置保留；链顺序 = 期次确认时间 → 期次内位置。"""
    env = ab_env
    client = env["client"]
    a = env["a"]
    card1 = seed(env, "a", title="首期报道", published=iso(hours=-48))
    issue1 = create_issue(client, a, title="第一期", cards=[card1]).json()
    confirm(client, a, issue1["id"])

    topic = client.post(
        "/api/v1/briefings/topics", json={"name": "数据中心用水"}, headers=a
    )
    assert topic.status_code == 201
    topic_id = topic.json()["id"]

    first = _attach(client, a, topic_id, issue1["id"], issue1["items"][0]["id"])
    assert first.status_code == 201
    # 幂等：同建同取 + 重复挂载不重复
    again = client.post(
        "/api/v1/briefings/topics", json={"name": "数据中心用水"}, headers=a
    )
    assert again.status_code == 200
    assert again.json()["id"] == topic_id
    dup = _attach(client, a, topic_id, issue1["id"], issue1["items"][0]["id"])
    assert dup.status_code == 200
    assert dup.json()["attached"] is False

    card2 = seed(env, "a", title="后续报道", published=iso(hours=-5))
    issue2 = create_issue(client, a, title="第二期", cards=[card2]).json()
    confirm(client, a, issue2["id"])
    second = _attach(client, a, topic_id, issue2["id"], issue2["items"][0]["id"])
    assert second.status_code == 201

    chain = client.get(f"/api/v1/briefings/topics/{topic_id}", headers=a).json()
    assert chain["name"] == "数据中心用水"
    assert [e["title"] for e in chain["entries"]] == ["首期报道", "后续报道"]
    assert [e["issueTitle"] for e in chain["entries"]] == ["第一期", "第二期"]
    assert all(e["issueConfirmedAt"] for e in chain["entries"])
    assert chain["entries"][0]["position"] == 0
    # 链尾就是「后续更新」
    assert chain["entries"][-1]["title"] == "后续报道"
    assert "绝不自动归类" in chain["honestyNote"]

    topics = client.get("/api/v1/briefings/topics", headers=a).json()
    row = next(t for t in topics["topics"] if t["id"] == topic_id)
    assert row["entryCount"] == 2


def test_topic_attach_validation(ab_env):  # noqa: F811
    """条目不属于该期 → 404；未知主题 → 404；空名 → 422。"""
    env = ab_env
    client = env["client"]
    a = env["a"]
    card = seed(env, "a", title="普通文章", published=iso(hours=-5))
    issue = create_issue(client, a, title="普通一期", cards=[card]).json()
    other = seed(env, "a", title="不在期里的", published=iso(hours=-4))

    assert (
        client.post("/api/v1/briefings/topics", json={"name": "  "}, headers=a).status_code
        == 422
    )
    missing_topic = _attach(client, a, "no-such-topic", issue["id"], issue["items"][0]["id"])
    assert missing_topic.status_code == 404

    topic_id = client.post(
        "/api/v1/briefings/topics", json={"name": "校验主题"}, headers=a
    ).json()["id"]
    bad_item = _attach(client, a, topic_id, issue["id"], "no-such-item")
    assert bad_item.status_code == 404
    wrong_issue = _attach(
        client, a, topic_id, "no-such-issue", issue["items"][0]["id"]
    )
    assert wrong_issue.status_code == 404
    _ = other


def test_topic_chain_keeps_draft_position(ab_env):  # noqa: F811
    """草稿期次也在链上（位置=created 序，confirmedAt 为空如实呈现）。"""
    env = ab_env
    client = env["client"]
    a = env["a"]
    card = seed(env, "a", title="草稿条目", published=iso(hours=-3))
    issue = create_issue(client, a, title="未确认期", cards=[card]).json()
    topic_id = client.post(
        "/api/v1/briefings/topics", json={"name": "追踪草稿"}, headers=a
    ).json()["id"]
    assert (
        _attach(client, a, topic_id, issue["id"], issue["items"][0]["id"]).status_code
        == 201
    )
    chain = client.get(f"/api/v1/briefings/topics/{topic_id}", headers=a).json()
    assert chain["entries"][0]["issueStatus"] == "draft"
    assert chain["entries"][0]["issueConfirmedAt"] is None


def test_cross_user_topics_isolated(ab_env):  # noqa: F811
    """A 的主题对 B 404；同名主题在 B 的库里是独立实体。"""
    env = ab_env
    client = env["client"]
    topic_id = client.post(
        "/api/v1/briefings/topics", json={"name": "共享名字"}, headers=env["a"]
    ).json()["id"]
    assert (
        client.get(f"/api/v1/briefings/topics/{topic_id}", headers=env["b"]).status_code
        == 404
    )
    b_topic = client.post(
        "/api/v1/briefings/topics", json={"name": "共享名字"}, headers=env["b"]
    ).json()
    assert b_topic["id"] != topic_id
    b_list = client.get("/api/v1/briefings/topics", headers=env["b"]).json()
    assert all(t["id"] != topic_id for t in b_list["topics"])
