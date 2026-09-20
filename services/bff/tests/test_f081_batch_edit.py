"""F081 批量元数据编辑 — 未勾选字段保持原值、部分失败可重试、后缀幂等、
rss 域不改（FreshRSS/Obsidian 负向）、并发编辑后者胜。"""

import asyncio

from lumirss.main import app

A = "library:00000000-0000-4000-8000-00000000f081"
B = "library:00000000-0000-4000-8000-00000000f082"
RSS_REF = "rss:ZmQx"


def run(coro):
    return asyncio.run(coro)


def _seed(client):
    r1 = client.post(
        "/api/v1/library/bookmarks",
        json={"url": "https://a.example/x", "title": "Alpha"},
    )
    r2 = client.post(
        "/api/v1/library/bookmarks",
        json={"url": "https://b.example/y", "title": "Beta"},
    )
    assert r1.status_code == 201 and r2.status_code == 201
    return r1.json()["ref"], r2.json()["ref"]


def test_f081_preview_zero_write_and_unchecked_fields_keep(client):
    a, _b = _seed(client)
    preview = client.post(
        "/api/v1/library/batch-edit/preview",
        json={"refs": [a], "patch": {"titleSuffix": "2026"}},
    )
    assert preview.status_code == 200, preview.text
    item = preview.json()["items"][0]
    assert item["before"]["title"] == "Alpha"
    assert item["after"]["title"] == "Alpha 2026"
    # 预览零写入
    assert (
        run(
            app.state.db.fetch_one(
                "SELECT title FROM library_bookmarks WHERE url = 'https://a.example/x'"
            )
        )["title"]
        == "Alpha"
    )


def test_f081_apply_suffix_tags_workspace_idempotent(client):
    client.post("/api/v1/workspaces", json={"name": "w5batch"})
    ws = client.get("/api/v1/workspaces").json()["items"][-1]["id"]
    a, _b = _seed(client)
    patch = {
        "titleSuffix": "精选",
        "tagsAdd": ["tech", "ai"],
        "workspaceId": ws,
    }
    first = client.post(
        "/api/v1/library/batch-edit", json={"refs": [a], "patch": patch}
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["applied"] == 1 and body["failed"] == 0
    # 重复应用：后缀不重复追加（幂等）
    second = client.post(
        "/api/v1/library/batch-edit", json={"refs": [a], "patch": patch}
    )
    assert second.json()["applied"] == 1
    row = run(
        app.state.db.fetch_one(
            "SELECT title FROM library_bookmarks WHERE url = 'https://a.example/x'"
        )
    )
    assert row["title"] == "Alpha 精选"
    tags = run(
        app.state.db.fetch_all(
            "SELECT t.name FROM item_tags it JOIN tags t ON t.id = it.tag_id WHERE it.item_ref = ?",
            (a,),
        )
    )
    assert {t["name"] for t in tags} == {"tech", "ai"}
    members = run(
        app.state.db.fetch_all(
            "SELECT workspace_id FROM workspace_items WHERE item_ref = ?", (a,)
        )
    )
    assert [m["workspace_id"] for m in members] == [ws]


def test_f081_partial_failure_retry_and_rss_domain_untouched(client):
    a, b = _seed(client)
    patch = {"titleSuffix": "v2"}
    # rss 引用逐项失败（FreshRSS 域绝不修改），library 引用成功
    result = client.post(
        "/api/v1/library/batch-edit",
        json={"refs": [a, RSS_REF, "library:not-exists"], "patch": patch},
    )
    assert result.status_code == 200, result.text
    items = {i["ref"]: i for i in result.json()["items"]}
    assert items[a]["ok"] is True
    assert items[RSS_REF]["ok"] is False
    assert items["library:not-exists"]["ok"] is False
    # 仅失败项重试语义：rss 引用重试仍失败但不影响他人
    retry = client.post(
        "/api/v1/library/batch-edit", json={"refs": [b], "patch": patch}
    )
    assert retry.json()["applied"] == 1


def test_f081_concurrent_edit_last_write_wins_no_crash(client):
    a, _b = _seed(client)
    first = client.post(
        "/api/v1/library/batch-edit",
        json={"refs": [a], "patch": {"titleSuffix": "one"}},
    )
    second = client.post(
        "/api/v1/library/batch-edit",
        json={"refs": [a], "patch": {"titleSuffix": "two"}},
    )
    assert first.status_code == 200 and second.status_code == 200
    row = run(
        app.state.db.fetch_one(
            "SELECT title FROM library_bookmarks WHERE url = 'https://a.example/x'"
        )
    )
    # 后者胜（顺序执行，无版本崩溃）
    assert row["title"] in ("Alpha one two", "Alpha two")
