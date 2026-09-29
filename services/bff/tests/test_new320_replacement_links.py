"""NEW-320 书签失效替代关联 — 旧链接保留、理由可追溯、引用者可见、A/B 隔离。"""

from new2xx_ab import ab_env  # noqa: F401 — pytest 夹具注册


def _mk(client, headers, title: str, url: str) -> str:
    made = client.post(
        "/api/v1/library/bookmarks", json={"title": title, "url": url}, headers=headers
    )
    assert made.status_code == 201, made.text
    return str(made.json()["ref"])


def _path(ref: str, suffix: str = "") -> str:
    return f"/api/v1/library/bookmarks/{ref.split(':', 1)[1]}/{suffix.strip('/')}".rstrip("/")


def test_new320_replacement_keeps_old_link_and_records_reason(ab_env):  # noqa: F811
    client, a = ab_env["client"], ab_env["a"]
    dead = _mk(client, a, "失效的博客", "https://dead.example/post/1")

    # 空理由拒绝（变更必须可追溯）
    no_reason = client.post(
        _path(dead, "replacement"), json={"newUrl": "https://alive.example/post/1", "reason": ""},
        headers=a,
    )
    assert no_reason.status_code == 422

    # 非 http(s) 新来源拒绝
    bad_scheme = client.post(
        _path(dead, "replacement"), json={"newUrl": "ftp://alive.example/x", "reason": "换源"},
        headers=a,
    )
    assert bad_scheme.status_code == 422

    first = client.post(
        _path(dead, "replacement"),
        json={"newUrl": "https://mirror.example/post/1", "reason": "原站下线，镜像站可访问"},
        headers=a,
    )
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["oldUrl"] == "https://dead.example/post/1"
    assert body["newUrl"] == "https://mirror.example/post/1"
    assert body["reason"] == "原站下线，镜像站可访问"
    assert body["current"] is True

    # 旧书签与旧 URL 原样保留（硬要求）
    items = client.get("/api/v1/library/bookmarks", headers=a).json()["items"]
    target = next(b for b in items if b["ref"] == dead)
    assert target["url"] == "https://dead.example/post/1"
    assert target["title"] == "失效的博客"

    # 第二次替代：历史保留，最新为 current
    second = client.post(
        _path(dead, "replacement"),
        json={"newUrl": "https://official.example/post/1", "reason": "找到官方恢复源"},
        headers=a,
    )
    assert second.status_code == 201

    history = client.get(_path(dead, "replacement"), headers=a)
    assert history.status_code == 200
    view = history.json()
    assert view["oldLinkPreserved"] is True
    assert view["oldUrl"] == "https://dead.example/post/1"
    assert len(view["history"]) == 2
    assert view["current"]["newUrl"] == "https://official.example/post/1"
    assert view["history"][-1]["current"] is False
    assert view["history"][-1]["reason"] == "原站下线，镜像站可访问"

    # 没有替代的书签 → 404；不存在书签 → 404
    other = _mk(client, a, "普通书签", "https://fine.example/x")
    assert (
        client.get(_path(other, "replacement"), headers=a).status_code == 404
    )
    assert (
        client.get(
            "/api/v1/library/bookmarks/00000000-0000-4000-8000-000000000000/replacement",
            headers=a,
        ).status_code
        == 404
    )


def test_new320_per_user_isolation_between_accounts(ab_env):  # noqa: F811
    client, a, b = ab_env["client"], ab_env["a"], ab_env["b"]
    a_book = _mk(client, a, "A 的失效书签", "https://dead-a.example/x")
    b_book = _mk(client, b, "B 的书签", "https://b.example/y")

    created = client.post(
        _path(a_book, "replacement"),
        json={"newUrl": "https://new-a.example/x", "reason": "A 的换源理由"},
        headers=a,
    )
    assert created.status_code == 201

    # B 查不到 A 的替代关联，也不能给 A 的书签加替代
    assert (
        client.get(_path(a_book, "replacement"), headers=b).status_code == 404
    )
    cross = client.post(
        _path(a_book, "replacement"),
        json={"newUrl": "https://evil.example/x", "reason": "越权写入"},
        headers=b,
    )
    assert cross.status_code == 404

    # B 的书签不受影响，写自己的替代正常
    assert (
        client.get(_path(b_book, "replacement"), headers=b).status_code == 404
    )
    own = client.post(
        _path(b_book, "replacement"),
        json={"newUrl": "https://b2.example/y", "reason": "B 自己的换源"},
        headers=b,
    )
    assert own.status_code == 201
