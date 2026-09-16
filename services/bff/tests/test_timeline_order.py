"""Read-later timeline sort order（pool #14）：newest（默认，历史语义）
与 oldest 双向 keyset；cursor 绑定排序方向，换向重放被拒；切换排序
不存在重复或丢行。"""

from lumirss.workspaces import RESERVED_WORKSPACE_ID


def _add(client, count):
    """Create `count` bookmarks and add them to read-later sequentially;
    returns refs oldest-first."""
    refs = []
    for i in range(count):
        created = client.post(
            "/api/v1/library/bookmarks",
            json={"url": f"https://example.com/{i}", "title": f"条目{i}"},
        ).json()
        response = client.post(
            f"/api/v1/workspaces/{RESERVED_WORKSPACE_ID}/items",
            json={"itemRef": created["ref"]},
        )
        assert response.status_code in (200, 201), response.text
        refs.append(created["ref"])
    return refs


def test_timeline_oldest_order_pages_without_duplicates(client, monkeypatch):
    import lumirss.workspaces as ws

    counter = {"n": 0}

    def increasing_now():
        counter["n"] += 1
        return f"2026-09-17T10:00:{counter['n']:02d}+00:00"

    monkeypatch.setattr(ws, "utc_now", increasing_now)

    refs = _add(client, 4)

    # newest（默认，兼容）：第一页最新加入在前。
    newest = client.get(
        "/api/v1/workspaces/read-later/timeline?limit=2"
    ).json()
    assert newest["items"][0]["itemRef"] == refs[-1]

    # oldest：最早加入在前，keyset 翻到底无重复无丢失。
    seen: list[str] = []
    cursor = None
    for _ in range(5):
        params = {"limit": 2, "order": "oldest"}
        if cursor:
            params["cursor"] = cursor
        response = client.get(
            "/api/v1/workspaces/read-later/timeline", params=params
        )
        assert response.status_code == 200
        body = response.json()
        seen.extend(item["itemRef"] for item in body["items"])
        if not body.get("nextCursor"):
            break
        cursor = body["nextCursor"]
    assert seen == refs


def test_timeline_cursor_is_bound_to_its_order(client):
    _add(client, 3)
    first = client.get(
        "/api/v1/workspaces/read-later/timeline?limit=1&order=oldest"
    ).json()
    assert first["nextCursor"]
    # 用 oldest 游标按 newest 续页 → 400（cursor 与排序绑定）。
    replay = client.get(
        "/api/v1/workspaces/read-later/timeline",
        params={"limit": 1, "cursor": first["nextCursor"]},
    )
    assert replay.status_code == 400

    # 非法 order 参数 → 400。
    bad = client.get(
        "/api/v1/workspaces/read-later/timeline",
        params={"order": "sideways"},
    )
    assert bad.status_code == 400
