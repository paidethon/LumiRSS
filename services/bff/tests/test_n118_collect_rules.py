"""N118 工作区自动收集规则测试 —— preview / apply / cap / 暂停。

- 规则 CRUD：恰好一种条件（feedUrl | tag | keyword）；上限 ≤100；
- preview：投影实时匹配（dry-run 有界 50，不写库）；
- apply：命中条目幂等收进工作区（重复 apply = 零新增、计入
  skippedExisting）；added_count 累计；上限 enforced；
- enabled=false（暂停）→ apply 零新增；disabled 规则诚实回显。
"""

import asyncio

import pytest

from lumirss.entryref import encode_entry_ref
from lumirss.main import app


def run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def rss_corpus(client):
    """3 条同源投影条目（search_entries）+ 1 条异源条目。"""
    db = app.state.db

    async def _seed():
        await db.migrate()
        rows = [
            ("9001", "https://feed.example/a", "检索增强进展", "关于检索增强的正文。"),
            ("9002", "https://feed.example/a", "检索评测方法", "关于评测的正文。"),
            ("9003", "https://feed.example/a", "无关杂谈", "完全无关的正文。"),
            ("9004", "https://other.example/b", "检索的另一面", "其他来源的检索正文。"),
        ]
        for item_id, feed_url, title, content in rows:
            await db.execute(
                "INSERT OR REPLACE INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at) VALUES (?, ?, ?, ?, ?, '', '', ?, ?, 0, 0, 0)",
                (
                    item_id,
                    encode_entry_ref(item_id),
                    feed_url,
                    "测试源" if "feed.example" in feed_url else "另一源",
                    title,
                    content,
                    "2026-09-01T00:00:00+00:00",
                ),
            )

    run(_seed())
    return [encode_entry_ref(item_id) for item_id in ("9001", "9002", "9003", "9004")]


def _ref(item_id: str) -> str:
    return "rss:" + encode_entry_ref(item_id)


def _mk_ws(client, name):
    return client.post("/api/v1/workspaces", json={"name": name}).json()["id"]


def test_create_rule_requires_exactly_one_source(client):
    ws = _mk_ws(client, "规则工作区")
    empty = client.post(
        f"/api/v1/workspaces/{ws}/collect-rules", json={}
    )
    assert empty.status_code == 422
    assert empty.json()["error"]["type"] == "invalid_collect_rule"
    both = client.post(
        f"/api/v1/workspaces/{ws}/collect-rules",
        json={"keyword": "x", "tag": "y"},
    )
    assert both.status_code == 422
    cap = client.post(
        f"/api/v1/workspaces/{ws}/collect-rules",
        json={"keyword": "x", "maxItems": 101},
    )
    assert cap.status_code == 422
    ok = client.post(
        f"/api/v1/workspaces/{ws}/collect-rules",
        json={"keyword": "检索", "maxItems": 100},
    )
    assert ok.status_code == 201
    assert ok.json()["addedCount"] == 0
    assert ok.json()["maxItems"] == 100


def test_preview_matches_from_projection_without_writes(client, rss_corpus):
    ws = _mk_ws(client, "预演工作区")
    rule = client.post(
        f"/api/v1/workspaces/{ws}/collect-rules",
        json={"keyword": "检索"},
    ).json()
    preview = client.post(
        f"/api/v1/workspaces/{ws}/collect-rules/{rule['id']}/preview"
    )
    assert preview.status_code == 200
    body = preview.json()
    matched = {m["itemRef"] for m in body["matches"]}
    assert matched == {_ref("9001"), _ref("9002"), _ref("9004")}
    assert body["matchCount"] == 3
    assert body["alreadyMemberCount"] == 0
    # dry-run：预演后工作区仍为空。
    members = client.get(f"/api/v1/workspaces/{ws}/items").json()["items"]
    assert members == []


def test_apply_is_idempotent_and_counts(client, rss_corpus):
    ws = _mk_ws(client, "应用工作区")
    rule = client.post(
        f"/api/v1/workspaces/{ws}/collect-rules",
        json={"feedUrl": "https://feed.example/a"},
    ).json()
    first = client.post(
        f"/api/v1/workspaces/{ws}/collect-rules/{rule['id']}/apply"
    ).json()
    assert sorted(first["added"]) == [_ref("9001"), _ref("9002"), _ref("9003")]
    assert first["addedCount"] == 3
    assert first["ruleAddedCount"] == 3
    second = client.post(
        f"/api/v1/workspaces/{ws}/collect-rules/{rule['id']}/apply"
    ).json()
    assert second["added"] == []
    assert second["skippedExisting"] == 3
    members = client.get(f"/api/v1/workspaces/{ws}/items").json()["items"]
    assert len(members) == 3


def test_cap_enforced(client, rss_corpus):
    ws = _mk_ws(client, "上限工作区")
    rule = client.post(
        f"/api/v1/workspaces/{ws}/collect-rules",
        json={"keyword": "检索", "maxItems": 2},
    ).json()
    result = client.post(
        f"/api/v1/workspaces/{ws}/collect-rules/{rule['id']}/apply"
    ).json()
    assert result["addedCount"] == 2
    assert result["capReached"] is True
    listed = client.get(f"/api/v1/workspaces/{ws}/collect-rules").json()["items"]
    assert listed[0]["addedCount"] == 2


def test_disabled_rule_skips_apply(client, rss_corpus):
    ws = _mk_ws(client, "暂停工作区")
    rule = client.post(
        f"/api/v1/workspaces/{ws}/collect-rules",
        json={"keyword": "检索"},
    ).json()
    paused = client.patch(
        f"/api/v1/workspaces/{ws}/collect-rules/{rule['id']}",
        json={"enabled": False},
    )
    assert paused.status_code == 200
    assert paused.json()["enabled"] is False
    result = client.post(
        f"/api/v1/workspaces/{ws}/collect-rules/{rule['id']}/apply"
    ).json()
    assert result["added"] == []
    assert result["enabled"] is False
    members = client.get(f"/api/v1/workspaces/{ws}/items").json()["items"]
    assert members == []
    # 未知规则 → 404。
    assert (
        client.post(f"/api/v1/workspaces/{ws}/collect-rules/rule-none/apply").status_code
        == 404
    )
    assert (
        client.delete(f"/api/v1/workspaces/{ws}/collect-rules/rule-none").status_code
        == 404
    )


def test_tag_rule_matches_via_item_tags(client, rss_corpus):
    ws = _mk_ws(client, "标签工作区")
    db = app.state.db

    async def _tag():
        await db.migrate()
        await db.execute(
            "INSERT INTO tags (name) VALUES ('检索')"
        )
        row = await db.fetch_one("SELECT id FROM tags WHERE name = '检索'")
        await db.execute(
            "INSERT INTO item_tags (tag_id, item_ref, origin, status, created_at) VALUES (?, ?, 'manual', 'active', '2026-09-01T00:00:00+00:00')",
            (row["id"], _ref("9001")),
        )

    run(_tag())
    rule = client.post(
        f"/api/v1/workspaces/{ws}/collect-rules", json={"tag": "检索"}
    ).json()
    preview = client.post(
        f"/api/v1/workspaces/{ws}/collect-rules/{rule['id']}/preview"
    ).json()
    assert {m["itemRef"] for m in preview["matches"]} == {_ref("9001")}
