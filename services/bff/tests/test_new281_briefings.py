"""NEW-281 个人简报编排台 — 候选摘要卡 / 编排 / 预览 / 修改 / 保存（确认）。"""

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册
from new281_helpers import confirm, create_issue, get_issue, iso, seed

RANGE_FROM = iso(days=-3)
RANGE_TO = iso(hours=-1)


def test_compose_preview_edit_confirm_flow(ab_env):  # noqa: F811
    """编排主路径：候选卡 → 建稿 → 详情预览 → 整稿替换 → 确认 → 列表。"""
    env = ab_env
    client = env["client"]
    a = env["a"]
    card1 = seed(env, "a", title="窗口内文章一", content_text="  第一篇  的  摘录。", published=iso(hours=-20))
    card2 = seed(env, "a", title="窗口内文章二", content_text="第二篇摘录。", published=iso(hours=-10))

    candidates = client.get(
        "/api/v1/briefings/candidates",
        params={"from": RANGE_FROM, "to": RANGE_TO},
        headers=a,
    )
    assert candidates.status_code == 200, candidates.text
    refs = {c["entryRef"] for c in candidates.json()["candidates"]}
    assert {card1["entryRef"], card2["entryRef"]} <= refs
    card = next(c for c in candidates.json()["candidates"] if c["entryRef"] == card1["entryRef"])
    assert card["title"] == "窗口内文章一"
    assert card["excerpt"] == "第一篇 的 摘录。"  # 空白折叠后的摘要卡
    assert card["seenInIssues"] == []

    created = create_issue(
        client,
        a,
        title="周三简报",
        cards=[card1, card2],
        sections=[
            {"key": "top", "label": "要闻"},
            {"key": "deep", "label": "深度"},
        ],
        extra_items=[
            {
                "entryRef": card1["entryRef"],
                "sectionKey": "top",
                "itemId": card1["itemId"],
                "title": card1["title"],
                "publishedAt": card1.get("publishedAt", ""),
                "excerpt": "第一篇 的 摘录。",
            },
            {
                "entryRef": card2["entryRef"],
                "sectionKey": "deep",
                "itemId": card2["itemId"],
                "title": card2["title"],
                "excerpt": "第二篇摘录。",
            },
        ],
        range_from=RANGE_FROM,
        range_to=RANGE_TO,
    )
    assert created.status_code == 201, created.text
    issue = created.json()
    assert issue["status"] == "draft"
    assert [s["key"] for s in issue["sections"]] == ["top", "deep"]
    assert [i["sectionKey"] for i in issue["items"]] == ["top", "deep"]
    assert issue["items"][0]["provenanceLabel"] == "编辑选入"
    issue_id = issue["id"]

    # 预览与修改：整稿替换条目（只留第二篇）
    patched = client.patch(
        f"/api/v1/briefings/{issue_id}",
        json={
            "items": [
                {
                    "entryRef": card2["entryRef"],
                    "sectionKey": "deep",
                    "title": card2["title"],
                    "excerpt": "第二篇摘录。",
                }
            ]
        },
        headers=a,
    )
    assert patched.status_code == 200, patched.text
    assert len(patched.json()["items"]) == 1

    confirmed = confirm(client, a, issue_id)
    assert confirmed.status_code == 200, confirmed.text
    confirmed_issue = confirmed.json()
    assert confirmed_issue["status"] == "confirmed"
    assert confirmed_issue["confirmedAt"]

    listing = client.get("/api/v1/briefings", headers=a).json()
    row = next(i for i in listing["issues"] if i["id"] == issue_id)
    assert row["status"] == "confirmed"
    assert row["itemCount"] == 1

    # 确认后不可编辑/删除；重复确认 409
    assert (
        client.patch(
            f"/api/v1/briefings/{issue_id}",
            json={"title": "改名"},
            headers=a,
        ).status_code
        == 409
    )
    assert client.delete(f"/api/v1/briefings/{issue_id}", headers=a).status_code == 409
    assert confirm(client, a, issue_id).status_code == 409


def test_candidates_range_and_feed_filter(ab_env):  # noqa: F811
    """候选只落在 [from, to) 内；feedUrl 过滤如实生效。"""
    env = ab_env
    client = env["client"]
    a = env["a"]
    inside = seed(env, "a", title="范围内", published=iso(hours=-5))
    outside = seed(env, "a", title="范围外", published=iso(days=-30))
    result = client.get(
        "/api/v1/briefings/candidates",
        params={"from": iso(days=-2), "to": iso(hours=-1)},
        headers=a,
    ).json()
    refs = {c["entryRef"] for c in result["candidates"]}
    assert inside["entryRef"] in refs
    assert outside["entryRef"] not in refs

    empty = client.get(
        "/api/v1/briefings/candidates",
        params={"from": iso(days=-2), "to": iso(hours=-1), "feedUrl": "https://none.example/rss"},
        headers=a,
    ).json()
    assert empty["candidates"] == []
    assert empty["count"] == 0


def test_create_validation(ab_env):  # noqa: F811
    """标题/栏目/条目负载校验（422）；不存在的期次 404。"""
    env = ab_env
    client = env["client"]
    a = env["a"]
    card = seed(env, "a", published=iso(hours=-2))
    base = {
        "rangeFrom": "",
        "rangeTo": "",
        "sections": [{"key": "main", "label": "正文"}],
        "items": [
            {
                "entryRef": card["entryRef"],
                "sectionKey": "main",
                "title": card["title"],
            }
        ],
    }
    assert (
        client.post("/api/v1/briefings", json={**base, "title": "  "}, headers=a).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/briefings",
            json={**base, "title": "x" * 201},
            headers=a,
        ).status_code
        == 422
    )
    dup_sections = {
        **base,
        "title": "重复栏目",
        "sections": [
            {"key": "main", "label": "一"},
            {"key": "main", "label": "二"},
        ],
    }
    assert (
        client.post("/api/v1/briefings", json=dup_sections, headers=a).status_code == 422
    )
    bad_section = {
        **base,
        "title": "未知栏目",
        "items": [
            {"entryRef": card["entryRef"], "sectionKey": "ghost", "title": "t"}
        ],
    }
    assert (
        client.post("/api/v1/briefings", json=bad_section, headers=a).status_code == 422
    )
    assert (
        client.post("/api/v1/briefings", json={**base, "title": "空刊", "items": []}, headers=a).status_code
        == 422
    )
    assert client.get("/api/v1/briefings/does-not-exist", headers=a).status_code == 404


def test_blank_issue_not_confirmable(ab_env):  # noqa: F811
    """空白成功页是禁止形态：所有条目被 defer/skip → 建稿即 422。"""
    env = ab_env
    client = env["client"]
    a = env["a"]
    assert (
        client.post(
            "/api/v1/briefings",
            json={
                "title": "全跳过",
                "sections": [{"key": "main", "label": "正文"}],
                "items": [],
            },
            headers=a,
        ).status_code
        == 422
    )


def test_cross_user_isolation(ab_env):  # noqa: F811
    """A 的期次对 B 是 404；候选与列表都只见自己的库。"""
    env = ab_env
    client = env["client"]
    card_a = seed(env, "a", title="A 的文章", published=iso(hours=-3))
    card_b = seed(env, "b", title="B 的文章", published=iso(hours=-3))
    created = create_issue(client, env["a"], title="A 的简报", cards=[card_a])
    assert created.status_code == 201
    issue_id = created.json()["id"]

    assert get_issue(client, env["b"], issue_id).status_code == 404
    b_issues = client.get("/api/v1/briefings", headers=env["b"]).json()
    assert all(i["id"] != issue_id for i in b_issues["issues"])

    b_candidates = client.get(
        "/api/v1/briefings/candidates",
        params={"from": iso(days=-2), "to": iso(hours=-1)},
        headers=env["b"],
    ).json()
    b_refs = {c["entryRef"] for c in b_candidates["candidates"]}
    assert card_b["entryRef"] in b_refs
    assert card_a["entryRef"] not in b_refs


def test_candidates_requires_ordered_range(ab_env):  # noqa: F811
    """from >= to → 422（范围边界显式拒绝，不静默返回空集）。"""
    env = ab_env
    client = env["client"]
    result = client.get(
        "/api/v1/briefings/candidates",
        params={"from": iso(hours=-1), "to": iso(hours=-2)},
        headers=env["a"],
    )
    assert result.status_code == 422
