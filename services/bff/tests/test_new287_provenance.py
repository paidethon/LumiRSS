"""NEW-287 简报人工精选标记 — 编辑来源如实区分，读者可见。"""

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册
from new281_helpers import confirm, create_issue, iso, seed


def test_suggestions_rule_starred_and_feed(ab_env):  # noqa: F811
    """推荐是确定性规则（starred/feed），卡片 provenance 恒为 rule。"""
    env = ab_env
    client = env["client"]
    a = env["a"]
    starred = seed(env, "a", title="标星的", published=iso(hours=-5), starred=1)
    plain = seed(env, "a", title="没标星的", published=iso(hours=-4))

    picks = client.get(
        "/api/v1/briefings/suggestions",
        params={"from": iso(days=-2), "to": iso(hours=-1), "rule": "starred"},
        headers=a,
    ).json()
    assert picks["rule"] == "starred"
    refs = {c["entryRef"] for c in picks["suggestions"]}
    assert starred["entryRef"] in refs
    assert plain["entryRef"] not in refs
    assert all(c["provenance"] == "rule" for c in picks["suggestions"])
    assert all(c["provenanceLabel"] == "规则推荐" for c in picks["suggestions"])

    feeds = client.get(
        "/api/v1/briefings/suggestions",
        params={
            "from": iso(days=-2),
            "to": iso(hours=-1),
            "rule": "feed",
            "feedUrl": "https://f.example/rss",
        },
        headers=a,
    ).json()
    assert feeds["count"] >= 1

    bad_rule = client.get(
        "/api/v1/briefings/suggestions",
        params={"from": iso(days=-2), "to": iso(hours=-1), "rule": "vibes"},
        headers=a,
    )
    assert bad_rule.status_code == 422
    no_url = client.get(
        "/api/v1/briefings/suggestions",
        params={"from": iso(days=-2), "to": iso(hours=-1), "rule": "feed"},
        headers=a,
    )
    assert no_url.status_code == 422


def test_rule_provenance_kept_and_flippable(ab_env):  # noqa: F811
    """采纳推荐 → 编辑来源保留「规则推荐」；草稿期可翻转为「编辑选入」。"""
    env = ab_env
    client = env["client"]
    a = env["a"]
    card = seed(env, "a", title="推荐来的", published=iso(hours=-5))
    created = create_issue(
        client, a, title="带推荐的一期", cards=[card], provenance="rule"
    )
    assert created.status_code == 201
    issue = created.json()
    item = issue["items"][0]
    assert item["provenance"] == "rule"
    assert item["provenanceLabel"] == "规则推荐"

    flipped = client.patch(
        f"/api/v1/briefings/{issue['id']}/items/{item['id']}/provenance",
        json={"provenance": "manual"},
        headers=a,
    )
    assert flipped.status_code == 200
    assert flipped.json()["items"][0]["provenanceLabel"] == "编辑选入"

    bad = client.patch(
        f"/api/v1/briefings/{issue['id']}/items/{item['id']}/provenance",
        json={"provenance": "auto"},
        headers=a,
    )
    assert bad.status_code == 422


def test_flip_confirmed_rejected(ab_env):  # noqa: F811
    """确认后编辑来源不可翻转（读者已按确认稿阅读，不静默改写）。"""
    env = ab_env
    client = env["client"]
    a = env["a"]
    card = seed(env, "a", title="已定稿", published=iso(hours=-5))
    issue_id = create_issue(client, a, title="定稿期", cards=[card]).json()["id"]
    confirm(client, a, issue_id)
    item = client.get(f"/api/v1/briefings/{issue_id}", headers=a).json()["items"][0]
    response = client.patch(
        f"/api/v1/briefings/{issue_id}/items/{item['id']}/provenance",
        json={"provenance": "rule"},
        headers=a,
    )
    assert response.status_code == 409
    assert response.json()["error"]["type"] == "briefing_confirmed"


def test_cross_user_flip_isolated(ab_env):  # noqa: F811
    """B 翻转 A 的条目 → 404（不泄露存在性）。"""
    env = ab_env
    client = env["client"]
    card = seed(env, "a", title="A 的条目", published=iso(hours=-5))
    issue_id = create_issue(client, env["a"], title="A 的草稿", cards=[card]).json()["id"]
    item = client.get(f"/api/v1/briefings/{issue_id}", headers=env["a"]).json()["items"][0]
    response = client.patch(
        f"/api/v1/briefings/{issue_id}/items/{item['id']}/provenance",
        json={"provenance": "rule"},
        headers=env["b"],
    )
    assert response.status_code == 404
