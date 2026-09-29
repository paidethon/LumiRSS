"""NEW-316 书签意图字段 — 记录为什么保存/何时使用、按意图筛选、A/B 隔离。"""

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册


def _mk(client, headers, title: str, url: str) -> str:
    made = client.post(
        "/api/v1/library/bookmarks", json={"title": title, "url": url}, headers=headers
    )
    assert made.status_code == 201, made.text
    return str(made.json()["ref"])


def _uuid_of(ref: str) -> str:
    return ref.split(":", 1)[1]


def _intent_path(ref: str) -> str:
    return f"/api/v1/library/bookmarks/{_uuid_of(ref)}/intent"


def test_new316_record_intent_and_filter_by_it(ab_env):  # noqa: F811
    client, a = ab_env["client"], ab_env["a"]
    weekend = _mk(client, a, "周末读的架构文", "https://a.example/arch")
    work = _mk(client, a, "工作参考：部署清单", "https://a.example/deploy")
    plain = _mk(client, a, "没写意图的书签", "https://a.example/plain")

    # 空意图拒绝：至少一项
    empty = client.put(
        _intent_path(weekend), json={"reason": "", "whenToUse": ""}, headers=a
    )
    assert empty.status_code == 422
    assert empty.json()["error"]["type"] == "invalid_intent"

    first = client.put(
        _intent_path(weekend),
        json={"reason": "面试前复盘系统设计", "whenToUse": "周末"},
        headers=a,
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["reason"] == "面试前复盘系统设计"
    assert body["whenToUse"] == "周末"
    assert body["ref"] == weekend

    # 更新 = 同一行覆盖（updated_at 变化，created_at 稳定）
    updated = client.put(
        _intent_path(weekend),
        json={"reason": "改为求职材料", "whenToUse": "周末"},
        headers=a,
    )
    assert updated.status_code == 200
    assert updated.json()["reason"] == "改为求职材料"
    assert updated.json()["createdAt"] == body["createdAt"]

    assert (
        client.put(
            _intent_path(work),
            json={"reason": "上线窗口要用", "whenToUse": "工作日"},
            headers=a,
        ).status_code
        == 200
    )

    # 按用途筛选：真实过滤，没写意图的书签如实缺席
    by_when = client.get(
        "/api/v1/library/bookmark-intents", params={"when": "周末"}, headers=a
    ).json()
    assert [i["ref"] for i in by_when["items"]] == [weekend]

    by_q = client.get(
        "/api/v1/library/bookmark-intents", params={"q": "上线"}, headers=a
    ).json()
    assert [i["ref"] for i in by_q["items"]] == [work]

    all_intents = client.get("/api/v1/library/bookmark-intents", headers=a).json()
    assert all_intents["total"] == 2
    assert plain not in [i["ref"] for i in all_intents["items"]]

    # 删除意图后回 404
    assert client.delete(_intent_path(work), headers=a).status_code == 204
    assert client.get(_intent_path(work), headers=a).status_code == 404


def test_new316_intent_references_must_exist(ab_env):  # noqa: F811
    client, a = ab_env["client"], ab_env["a"]
    missing = client.put(
        "/api/v1/library/bookmarks/00000000-0000-4000-8000-000000000000/intent",
        json={"reason": "孤儿意图"},
        headers=a,
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["type"] == "bookmark_not_found"

    # 非 bookmars ref 形状也拿不到
    ref = _mk(client, a, "普通书签", "https://a.example/x")
    got = client.get(_intent_path(ref), headers=a)
    assert got.status_code == 404  # 书签在、意图无
    assert got.json()["error"]["type"] == "intent_not_found"


def test_new316_per_user_isolation_between_accounts(ab_env):  # noqa: F811
    client, a, b = ab_env["client"], ab_env["a"], ab_env["b"]
    a_book = _mk(client, a, "A 的书签", "https://a.example/private")
    assert (
        client.put(
            _intent_path(a_book),
            json={"reason": "A 的私人理由", "whenToUse": "深夜"},
            headers=a,
        ).status_code
        == 200
    )

    # B 看不到 A 的意图（读 = bookmark_not_found；筛选结果不含）
    assert client.get(_intent_path(a_book), headers=b).status_code == 404
    b_all = client.get("/api/v1/library/bookmark-intents", headers=b).json()
    assert b_all["items"] == []

    # B 写自己的意图，互不影响
    b_book = _mk(client, b, "B 的书签", "https://b.example/mine")
    assert (
        client.put(
            _intent_path(b_book),
            json={"whenToUse": "通勤"},
            headers=b,
        ).status_code
        == 200
    )
    a_all = client.get("/api/v1/library/bookmark-intents", headers=a).json()
    assert [i["ref"] for i in a_all["items"]] == [a_book]
