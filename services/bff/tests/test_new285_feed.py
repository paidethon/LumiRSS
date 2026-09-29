"""NEW-285 个人简报 RSS 发布 — 可撤销私有 Atom（token 一次性 / 确认才可见）。"""

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册
from new281_helpers import confirm, create_issue, iso, seed


def _enable(client, headers):
    return client.post("/api/v1/briefings/feed/enable", headers=headers)


def _atom(client, token):
    return client.get(f"/feeds/briefings/{token}.atom")


def test_enable_feed_and_confirmed_only(ab_env):  # noqa: F811
    """feed 只含已确认期次；草稿绝不出现；条目带编辑来源标记。"""
    env = ab_env
    client = env["client"]
    a = env["a"]
    enabled = _enable(client, a)
    assert enabled.status_code == 200, enabled.text
    payload = enabled.json()
    token = payload["token"]
    assert payload["path"] == f"/feeds/briefings/{token}.atom"
    assert "只显示这一次" in payload["note"]

    confirmed_card = seed(env, "a", title="已确认的文章", published=iso(hours=-5))
    issue = create_issue(client, a, title="公开的一期", cards=[confirmed_card])
    assert issue.status_code == 201
    assert confirm(client, a, issue.json()["id"]).status_code == 200
    draft_card = seed(env, "a", title="草稿里的文章", published=iso(hours=-4))
    draft = create_issue(client, a, title="草稿的一期", cards=[draft_card])
    assert draft.status_code == 201

    feed = _atom(client, token)
    assert feed.status_code == 200, feed.text
    assert feed.headers["content-type"].startswith("application/atom+xml")
    body = feed.text
    assert "公开的一期" in body
    assert "已确认的文章" in body
    assert "【编辑选入】" in body
    assert "草稿的一期" not in body
    assert "草稿里的文章" not in body

    # 状态面永不含 token（库存哈希）
    state = client.get("/api/v1/briefings/feed", headers=a).json()
    assert state["enabled"] is True
    assert "token" not in state


def test_wrong_token_same_404_body(ab_env):  # noqa: F811
    """错 token 与未启用同一 404（不泄露存在性）。"""
    env = ab_env
    client = env["client"]
    wrong = _atom(client, "deadbeef" * 4)
    assert wrong.status_code == 404
    assert wrong.text == "<error>not found</error>"


def test_rotate_invalidates_old_token(ab_env):  # noqa: F811
    """rotate：新 token 立即可用，旧 token 立即 404。"""
    env = ab_env
    client = env["client"]
    a = env["a"]
    old = _enable(client, a).json()["token"]
    rotated = client.post("/api/v1/briefings/feed/rotate", headers=a)
    assert rotated.status_code == 200
    new = rotated.json()["token"]
    assert new != old
    assert _atom(client, old).status_code == 404
    assert _atom(client, new).status_code == 200


def test_revoke_kills_feed_then_reenable(ab_env):  # noqa: F811
    """撤销 → feed 404；可再次启用（新凭据）。"""
    env = ab_env
    client = env["client"]
    a = env["a"]
    token = _enable(client, a).json()["token"]
    assert client.post("/api/v1/briefings/feed/revoke", headers=a).status_code == 204
    assert _atom(client, token).status_code == 404
    state = client.get("/api/v1/briefings/feed", headers=a).json()
    assert state["enabled"] is False
    assert state["revokedAt"]

    again = _enable(client, a)
    assert again.status_code == 200
    assert _atom(client, again.json()["token"]).status_code == 200


def test_enable_twice_conflicts(ab_env):  # noqa: F811
    """已启用再 enable → 409（轮换走 rotate，撤销走 revoke）。"""
    env = ab_env
    client = env["client"]
    a = env["a"]
    assert _enable(client, a).status_code == 200
    conflict = _enable(client, a)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["type"] == "feed_state_conflict"


def test_cross_user_feed_scoped(ab_env):  # noqa: F811
    """A 的 feed 只出 A 的期次；B 的期次绝不出现在 A 的 feed。"""
    env = ab_env
    client = env["client"]
    card_a = seed(env, "a", title="A 的独有文章", published=iso(hours=-5))
    issue_a = create_issue(client, env["a"], title="A 的期次", cards=[card_a])
    confirm(client, env["a"], issue_a.json()["id"])
    card_b = seed(env, "b", title="B 的独有文章", published=iso(hours=-5))
    issue_b = create_issue(client, env["b"], title="B 的期次", cards=[card_b])
    confirm(client, env["b"], issue_b.json()["id"])

    token_a = _enable(client, env["a"]).json()["token"]
    body_a = _atom(client, token_a).text
    assert "A 的期次" in body_a
    assert "B 的期次" not in body_a

    token_b = _enable(client, env["b"]).json()["token"]
    body_b = _atom(client, token_b).text
    assert "B 的期次" in body_b
    assert "A 的期次" not in body_b
