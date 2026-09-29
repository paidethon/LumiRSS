"""NEW-290 简报历史更正 — 追加式；读者看到更正提示而非静默替换。"""

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册
from new281_helpers import confirm, create_issue, iso, seed


def test_corrections_append_only_readback(ab_env):  # noqa: F811
    """追加更正 → 按时间读回；期次正文原样（绝不静默替换）。"""
    env = ab_env
    client = env["client"]
    a = env["a"]
    card = seed(env, "a", title="有误的文章", published=iso(hours=-5))
    issue_id = create_issue(client, a, title="需要更正的一期", cards=[card]).json()["id"]
    confirm(client, a, issue_id)
    before = client.get(f"/api/v1/briefings/{issue_id}", headers=a).json()
    items_before = before["items"]

    first = client.post(
        f"/api/v1/briefings/{issue_id}/corrections",
        json={"body": "标题中的日期写错了。"},
        headers=a,
    )
    assert first.status_code == 201, first.text
    second = client.post(
        f"/api/v1/briefings/{issue_id}/corrections",
        json={"body": "补充：来源名也有笔误。"},
        headers=a,
    )
    assert second.status_code == 201

    listed = client.get(f"/api/v1/briefings/{issue_id}/corrections", headers=a).json()
    assert listed["count"] == 2
    assert [c["body"] for c in listed["corrections"]] == [
        "标题中的日期写错了。",
        "补充：来源名也有笔误。",
    ]
    assert "只增不改不删" in listed["honestyNote"]

    # 期次正文不变：更正不改历史
    after = client.get(f"/api/v1/briefings/{issue_id}", headers=a).json()
    assert after["items"] == items_before
    assert after["confirmedAt"] == before["confirmedAt"]


def test_correction_validation(ab_env):  # noqa: F811
    """草稿 → 409（没有已发布历史）；空内容 → 422；未知期次 → 404。"""
    env = ab_env
    client = env["client"]
    a = env["a"]
    card = seed(env, "a", title="草稿文章", published=iso(hours=-5))
    draft_id = create_issue(client, a, title="还是草稿", cards=[card]).json()["id"]
    draft = client.post(
        f"/api/v1/briefings/{draft_id}/corrections",
        json={"body": "草稿不用更正"},
        headers=a,
    )
    assert draft.status_code == 409
    assert draft.json()["error"]["type"] == "briefing_not_confirmed"

    empty = client.post(
        f"/api/v1/briefings/{draft_id}/corrections", json={"body": "   "}, headers=a
    )
    assert empty.status_code == 422
    too_long = client.post(
        f"/api/v1/briefings/{draft_id}/corrections",
        json={"body": "x" * 2001},
        headers=a,
    )
    assert too_long.status_code == 422
    assert (
        client.post(
            "/api/v1/briefings/no-such-issue/corrections",
            json={"body": "更正"},
            headers=a,
        ).status_code
        == 404
    )


def test_no_mutation_paths_exist(ab_env):  # noqa: F811
    """机制保证（不靠自觉）：PATCH/DELETE 更正路径 → 405（处理器不存在）。"""
    env = ab_env
    client = env["client"]
    a = env["a"]
    card = seed(env, "a", title="正文", published=iso(hours=-5))
    issue_id = create_issue(client, a, title="一期", cards=[card]).json()["id"]
    confirm(client, a, issue_id)
    assert (
        client.patch(
            f"/api/v1/briefings/{issue_id}/corrections",
            json={"body": "改历史"},
            headers=a,
        ).status_code
        == 405
    )
    assert (
        client.delete(
            f"/api/v1/briefings/{issue_id}/corrections", headers=a
        ).status_code
        == 405
    )


def test_cross_user_corrections_isolated(ab_env):  # noqa: F811
    """B 不能给 A 的期次追加更正，也读不到它（404 同形）。"""
    env = ab_env
    client = env["client"]
    card = seed(env, "a", title="A 的文章", published=iso(hours=-5))
    issue_id = create_issue(client, env["a"], title="A 的一期", cards=[card]).json()["id"]
    confirm(client, env["a"], issue_id)
    assert (
        client.post(
            f"/api/v1/briefings/{issue_id}/corrections",
            json={"body": "B 的更正"},
            headers=env["b"],
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/briefings/{issue_id}/corrections", headers=env["b"]
        ).status_code
        == 404
    )
