"""N109 工作区标签全文检索 — GET /api/v1/workspaces/{id}/search?q=.

- scoping：严格只搜本工作区自己的成员——其他工作区内容命中也绝不返回；
- 标题恒匹配 + ref 可解析条目的内容匹配（rss → search_entries；
  library → search_library.body）；
- excerpt ≤160 字符（±省略号）且含命中词；空命中诚实为空。
"""

import asyncio

from lumirss.entryref import encode_entry_ref


def run(coro):
    return asyncio.run(coro)


def _mk_ws(client, name: str) -> str:
    r = client.post("/api/v1/workspaces", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _bookmark(client, title: str, note: str, url: str) -> str:
    r = client.post(
        "/api/v1/library/bookmarks", json={"url": url, "title": title, "note": note}
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["ref"]


def _add_member(client, workspace_id: str, item_ref: str) -> None:
    r = client.post(f"/api/v1/workspaces/{workspace_id}/items", json={"itemRef": item_ref})
    assert r.status_code == 201, r.text


def _seed_rss_entry(client, entry_ref: str, title: str, content: str) -> None:
    async def _insert():
        await client.app.state.db.execute(
            "INSERT OR REPLACE INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0)",
            (
                f"seed::{entry_ref}",
                entry_ref,
                "https://feed.example/rss",
                "种子源",
                title,
                "",
                "https://example.test/entry",
                content,
                "2026-09-25T00:00:00+00:00",
            ),
        )

    run(_insert())


def test_workspace_search_scoping_title_content_excerpt(client):
    ws_a = _mk_ws(client, "检索A")
    ws_b = _mk_ws(client, "检索B")
    # A：标题命中（library，note 不含 needle）+ 内容命中（library note / rss 投影）
    _add_member(client, ws_a, _bookmark(client, "量子计算 needle 综述", "与关键词无关的笔记", "https://a.example/1"))
    _add_member(client, ws_a, _bookmark(client, "别的标题", "正文里出现needle一词", "https://a.example/2"))
    entry_ref = encode_entry_ref("tag:example.com,2005:reader/item/0000000000000001")
    _seed_rss_entry(client, entry_ref, "无关标题", "rss 正文提到 needle 关键词")
    _add_member(client, ws_a, f"rss:{entry_ref}")
    # B：同样含 needle 的标题——绝不允许出现在 A 的结果里
    _add_member(client, ws_b, _bookmark(client, "needle 在另一个工作区", "", "https://b.example/1"))
    # A 的成员里再放一个 B 的条目（同 ref 双工作区成员是合法状态）
    cross = _bookmark(client, "跨区成员标题 needle", "", "https://b.example/2")
    _add_member(client, ws_b, cross)

    resp = client.get(f"/api/v1/workspaces/{ws_a}/search", params={"q": "needle"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["workspaceId"] == ws_a
    assert body["truncated"] is False
    hits = {hit["itemRef"]: hit for hit in body["results"]}
    # scoping：B 工作区的条目 + 未加入 A 的 cross 条目都不在
    assert all("另一个工作区" not in hit["title"] for hit in body["results"])
    assert cross not in hits
    # 标题命中 + 内容命中都返回
    title_hits = [hit for hit in body["results"] if hit["title"] == "量子计算 needle 综述"]
    assert len(title_hits) == 1 and title_hits[0]["matchedIn"] == "title"
    lib_content = [hit for hit in body["results"] if hit["title"] == "别的标题"]
    assert len(lib_content) == 1
    assert lib_content[0]["matchedIn"] == "content"
    assert lib_content[0]["domain"] == "library"
    assert "needle" in lib_content[0]["excerpt"].lower()
    assert len(lib_content[0]["excerpt"]) <= 162  # 160 + 两侧省略号
    rss_content = [hit for hit in body["results"] if hit["domain"] == "rss"]
    assert len(rss_content) == 1
    assert rss_content[0]["matchedIn"] == "content"
    assert "needle" in rss_content[0]["excerpt"].lower()

    # 大小写不敏感（与投影 LIKE 语义一致）
    resp_upper = client.get(f"/api/v1/workspaces/{ws_a}/search", params={"q": "NEEDLE"})
    assert len(resp_upper.json()["results"]) == len(body["results"])

    # 深处命中的摘要：偏移截断两侧有 …
    long_note = "前" * 300 + "needle" + "后" * 300
    ws_c = _mk_ws(client, "检索C")
    _add_member(client, ws_c, _bookmark(client, "长文标题", long_note, "https://c.example/1"))
    deep = client.get(f"/api/v1/workspaces/{ws_c}/search", params={"q": "needle"}).json()
    assert len(deep["results"]) == 1
    excerpt = deep["results"][0]["excerpt"]
    assert excerpt.startswith("…") and excerpt.endswith("…")
    assert len(excerpt) <= 162


def test_workspace_search_empty_and_missing_cases(client):
    ws = _mk_ws(client, "空检索")
    # 无命中 → 诚实空
    empty = client.get(f"/api/v1/workspaces/{ws}/search", params={"q": "nothing-matches"})
    assert empty.status_code == 200
    assert empty.json()["results"] == [] and empty.json()["truncated"] is False
    # 纯空白 q → 诚实空（不做全表匹配）
    blank = client.get(f"/api/v1/workspaces/{ws}/search", params={"q": "   "})
    assert blank.status_code == 200
    assert blank.json()["results"] == []
    # 未知工作区 → 404
    missing = client.get("/api/v1/workspaces/ws-none/search", params={"q": "x"})
    assert missing.status_code == 404
    # 缺 q → 422
    assert client.get(f"/api/v1/workspaces/{ws}/search").status_code == 422
