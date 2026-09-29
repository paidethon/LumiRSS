"""NEW-282 简报去重审批 — 重收 / 仅列后续 / 跳过，缺决定即拦截。"""

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册
from new281_helpers import confirm, create_issue, get_issue, iso, seed


def _card(env, who, title, **kw):
    return seed(env, who, title=title, content_text="摘要内容。", **kw)


def test_dup_without_decision_blocked_then_include(ab_env):  # noqa: F811
    """已刊出条目缺 dupDecision → 409 审批清单；include 后重收成功。"""
    env = ab_env
    client = env["client"]
    a = env["a"]
    card = _card(env, "a", "旧文", published=iso(hours=-30))
    first = create_issue(client, a, title="第一期", cards=[card])
    assert first.status_code == 201
    assert confirm(client, a, first.json()["id"]).status_code == 200

    blocked = create_issue(client, a, title="第二期", cards=[card])
    assert blocked.status_code == 409, blocked.text
    error = blocked.json()["error"]
    assert error["type"] == "briefing_dup_approval_required"
    dup = error["duplicates"][0]
    assert dup["entryRef"] == card["entryRef"]
    assert dup["priorIssues"][0]["issueTitle"] == "第一期"

    included = client.post(
        "/api/v1/briefings",
        json={
            "title": "第二期",
            "sections": [{"key": "main", "label": "正文"}],
            "items": [
                {
                    "entryRef": card["entryRef"],
                    "sectionKey": "main",
                    "title": card["title"],
                    "dupDecision": "include",
                }
            ],
        },
        headers=a,
    )
    assert included.status_code == 201, included.text
    assert included.json()["items"][0]["entryRef"] == card["entryRef"]


def test_defer_goes_to_followups_until_recalled(ab_env):  # noqa: F811
    """defer = 仅列后续：不进正文；后续期次收录后从清单消失。"""
    env = ab_env
    client = env["client"]
    a = env["a"]
    card = _card(env, "a", "迟到的旧闻", published=iso(hours=-40))
    first = confirm(client, a, create_issue(client, a, title="一期", cards=[card]).json()["id"])
    assert first.status_code == 200

    deferred = client.post(
        "/api/v1/briefings",
        json={
            "title": "二期",
            "sections": [{"key": "main", "label": "正文"}],
            "items": [
                {
                    "entryRef": card["entryRef"],
                    "sectionKey": "main",
                    "title": card["title"],
                    "dupDecision": "defer",
                },
                {
                    "entryRef": "rss:fresh-ref-not-seeded",
                    "sectionKey": "main",
                    "title": "新文章",
                },
            ],
        },
        headers=a,
    )
    assert deferred.status_code == 201, deferred.text
    assert [i["entryRef"] for i in deferred.json()["items"]] == [
        "rss:fresh-ref-not-seeded"
    ]

    followups = client.get("/api/v1/briefings/followups", headers=a).json()
    assert followups["count"] == 1
    assert followups["followups"][0]["entryRef"] == card["entryRef"]
    assert followups["followups"][0]["priorIssue"]

    # 后续期次重新收录（include）→ 清单消失
    recall = client.post(
        "/api/v1/briefings",
        json={
            "title": "三期",
            "sections": [{"key": "main", "label": "正文"}],
            "items": [
                {
                    "entryRef": card["entryRef"],
                    "sectionKey": "main",
                    "title": card["title"],
                    "dupDecision": "include",
                }
            ],
        },
        headers=a,
    )
    assert recall.status_code == 201
    followups_after = client.get("/api/v1/briefings/followups", headers=a).json()
    assert followups_after["count"] == 0


def test_skip_records_decision_but_lists_nothing(ab_env):  # noqa: F811
    """skip：不进正文也不进后续清单（明确跳过）。"""
    env = ab_env
    client = env["client"]
    a = env["a"]
    card = _card(env, "a", "不再收", published=iso(hours=-40))
    confirm(client, a, create_issue(client, a, title="一期", cards=[card]).json()["id"])
    skipped = client.post(
        "/api/v1/briefings",
        json={
            "title": "二期",
            "sections": [{"key": "main", "label": "正文"}],
            "items": [
                {
                    "entryRef": "rss:another-fresh",
                    "sectionKey": "main",
                    "title": "新文章",
                },
                {
                    "entryRef": card["entryRef"],
                    "sectionKey": "main",
                    "title": card["title"],
                    "dupDecision": "skip",
                },
            ],
        },
        headers=a,
    )
    assert skipped.status_code == 201
    assert all(i["entryRef"] != card["entryRef"] for i in skipped.json()["items"])
    followups = client.get("/api/v1/briefings/followups", headers=a).json()
    assert all(f["entryRef"] != card["entryRef"] for f in followups["followups"])


def test_draft_issue_not_counted_as_published(ab_env):  # noqa: F811
    """草稿不算「已刊出」：同 ref 再建稿不需要审批。"""
    env = ab_env
    client = env["client"]
    a = env["a"]
    card = _card(env, "a", "草稿中的文章", published=iso(hours=-20))
    draft = create_issue(client, a, title="还是草稿", cards=[card])
    assert draft.status_code == 201
    again = create_issue(client, a, title="另一份草稿", cards=[card])
    assert again.status_code == 201, again.text
    assert get_issue(client, a, draft.json()["id"]).status_code == 200


def test_cross_user_dup_isolation(ab_env):  # noqa: F811
    """A 刊出的条目，B 的库里没有收录记录 → B 不需要审批。"""
    env = ab_env
    client = env["client"]
    card_a = _card(env, "a", "A 的旧文", published=iso(hours=-30))
    confirm(
        client,
        env["a"],
        create_issue(client, env["a"], title="A 的一期", cards=[card_a]).json()["id"],
    )
    # B 用同一个 entry_ref（模拟同一篇文章在不同账户）建稿 → 无审批拦截
    b_issue = client.post(
        "/api/v1/briefings",
        json={
            "title": "B 的一期",
            "sections": [{"key": "main", "label": "正文"}],
            "items": [
                {
                    "entryRef": card_a["entryRef"],
                    "sectionKey": "main",
                    "title": card_a["title"],
                }
            ],
        },
        headers=env["b"],
    )
    assert b_issue.status_code == 201, b_issue.text
    followups_b = client.get("/api/v1/briefings/followups", headers=env["b"]).json()
    assert followups_b["count"] == 0
