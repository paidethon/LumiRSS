"""F023 跨来源作者聚合 —— 聚合计数、别名展开与撤销、空 author、分页。"""

import asyncio


def run(coroutine):
    return asyncio.run(coroutine)


def _seed(app, item_id, author, title="t"):
    from lumirss.entryref import encode_entry_ref

    run(app.state.db.migrate())
    entry_ref = encode_entry_ref(item_id)
    run(
        app.state.db.execute(
            "INSERT OR IGNORE INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, fetched_at) VALUES (?, ?, 'https://f.example/rss', '源', ?, ?, 'https://f.example/a', ?, ?, 0)",
            (item_id, entry_ref, title, author, f"{title} 正文", "2026-09-01T00:00:00Z"),
        )
    )
    return f"rss:{entry_ref}"


def _seed_all(app):
    _seed(app, "a1", "张三", "张三文章一")
    _seed(app, "a2", "张三", "张三文章二")
    _seed(app, "a3", "Zhang San", "Zhang 文章")
    _seed(app, "a4", "李四", "李四文章")
    _seed(app, "a5", "zhang san", "小写同形文章")  # 大小写不同 = 不同 key
    _seed(app, "a6", "", "无作者文章")


def test_f023_aggregation_counts_and_empty_author_excluded(client):
    app = client.app
    _seed_all(app)
    body = client.get("/api/v1/authors").json()
    counts = {item["author"]: item["count"] for item in body["items"]}
    # 同名字符串天然同组；空 author 排除；大小写不同不自动归并
    assert counts["张三"] == 2
    assert counts["Zhang San"] == 1
    assert counts["zhang san"] == 1
    assert counts["李四"] == 1
    assert "" not in counts


def test_f023_alias_folds_counts_and_items_with_pagination(client):
    app = client.app
    _seed_all(app)
    # 别名必须显式建立：Zhang San / zhang san 都并入 张三
    created = client.post(
        "/api/v1/authors/aliases",
        json={"alias": "Zhang San", "canonical": "张三"},
    )
    assert created.status_code == 201, created.text
    client.post(
        "/api/v1/authors/aliases",
        json={"alias": "zhang san", "canonical": "张三"},
    )
    counts = {
        item["author"]: item["count"]
        for item in client.get("/api/v1/authors").json()["items"]
    }
    assert counts["张三"] == 4
    assert "Zhang San" not in counts and "zhang san" not in counts

    # 别名展开的条目查询（含分页）
    page1 = client.get("/api/v1/authors/items", params={"author": "张三", "limit": 3}).json()
    assert page1["author"] == "张三"
    assert len(page1["items"]) == 3
    assert page1["hasMore"] is True
    page2 = client.get(
        "/api/v1/authors/items", params={"author": "张三", "limit": 3, "offset": 3}
    ).json()
    assert len(page2["items"]) == 1 and page2["hasMore"] is False
    refs = {item["entryRef"] for item in page1["items"]} | {
        item["entryRef"] for item in page2["items"]
    }
    assert len(refs) == 4

    # 撤销别名（删除一行）→ 计数按剩余别名还原
    alias_route = "/api/v1/authors/aliases/Zhang%20San"
    assert client.delete(alias_route).status_code == 204
    counts2 = {
        item["author"]: item["count"]
        for item in client.get("/api/v1/authors").json()["items"]
    }
    assert counts2["张三"] == 3 and counts2["Zhang San"] == 1
    assert "zhang san" not in counts2  # 该别名仍生效
    # 删除第二个别名后完全还原
    assert client.delete("/api/v1/authors/aliases/zhang%20san").status_code == 204
    counts3 = {
        item["author"]: item["count"]
        for item in client.get("/api/v1/authors").json()["items"]
    }
    assert counts3["张三"] == 2 and counts3["Zhang San"] == 1
    # 再删同一别名 → 404
    assert client.delete(alias_route).status_code == 404


def test_f023_alias_validation_and_listing(client):
    app = client.app
    _seed_all(app)
    # alias == canonical → 422
    same = client.post(
        "/api/v1/authors/aliases", json={"alias": "张三", "canonical": "张三"}
    )
    assert same.status_code == 422
    # 空 alias → 422
    blank = client.post(
        "/api/v1/authors/aliases", json={"alias": "  ", "canonical": "张三"}
    )
    assert blank.status_code == 422
    # 列表形状
    client.post(
        "/api/v1/authors/aliases", json={"alias": "Zhang San", "canonical": "张三"}
    )
    aliases = client.get("/api/v1/authors/aliases").json()["items"]
    assert any(
        a["alias"] == "Zhang San" and a["canonical"] == "张三" for a in aliases
    )
