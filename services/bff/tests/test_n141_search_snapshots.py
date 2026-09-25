"""N141 搜索快照比较 — 冻结 → 变更 → 差分回归。

- 冻结返回引用计数 + 过滤作用域；列表有界（不带引用清单）；
- compare 对存储作用域原样复跑：added/removed/rankChanges(>5)/
  permissionLost（本账户投影不再解析）诚实差分；
- cap 20 自动淘汰最老；快照缺失 → 404；非法参数 → 400。
"""

import asyncio

import pytest

from lumirss.entryref import encode_entry_ref

FEED_A = "https://a.example/rss"


def _row(item_id, title, published_at):
    return (
        item_id,
        encode_entry_ref(item_id),
        FEED_A,
        "源A",
        title,
        "作者甲",
        "https://example.com/x",
        f"{title} 的正文内容。",
        published_at,
        0,
        0,
        0,
    )


def _seed(app, rows):
    async def run():
        from lumirss.user_scope import user_context

        db = app.state.db
        with user_context(app.state.owner_id):
            await db.migrate()
            existing = {
                str(r["entry_ref"])
                for r in await db.fetch_all(
                    "SELECT entry_ref FROM search_entries", ()
                )
            }
            for row in rows:
                if row[1] in existing:
                    continue
                await db.execute(
                    "INSERT INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    row,
                )

    asyncio.run(run())


def _delete_refs(app, item_ids):
    async def run():
        from lumirss.user_scope import user_context

        db = app.state.db
        with user_context(app.state.owner_id):
            await db.migrate()
            for item_id in item_ids:
                await db.execute(
                    "DELETE FROM search_entries WHERE item_id = ?", (item_id,)
                )

    asyncio.run(run())


@pytest.fixture()
def snap_client(monkeypatch, tmp_path):
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    from fastapi.testclient import TestClient

    from lumirss.main import app

    with TestClient(app) as test_client:
        _seed(
            app,
            [
                _row("a1", "Rust 发布", "2026-09-23T09:00:00Z"),
                _row("a2", "Rust 教程", "2026-09-23T08:00:00Z"),
                _row("a3", "Rust 深谈", "2026-09-20T08:00:00Z"),
            ],
        )
        yield test_client


def _freeze(client, **overrides):
    body = {"q": "rust"}
    body.update(overrides)
    return client.post("/api/v1/search/snapshots", json=body)


def test_freeze_stores_refs_and_lists_bounded(snap_client):
    created = _freeze(snap_client)
    assert created.status_code == 201
    body = created.json()
    assert body["query"] == "rust"
    assert body["refCount"] == 3
    assert body["truncated"] is False
    assert "refs" not in body  # 引用清单不出站

    listing = snap_client.get("/api/v1/search/snapshots").json()
    assert listing["items"][0]["refCount"] == 3
    assert all("refs" not in item for item in listing["items"])


def test_freeze_rejects_bad_params(snap_client):
    assert _freeze(snap_client, q="").status_code == 422  # 契约层非空
    assert _freeze(snap_client, state="draft").status_code == 400
    response = _freeze(
        snap_client, feedUrl=FEED_A, categoryId="cat-a"
    )
    assert response.status_code == 400


def test_freeze_then_diff_added(snap_client):
    from lumirss.main import app as lumi_app

    _freeze(snap_client)
    _seed(lumi_app, [_row("a4", "Rust 新动态", "2026-09-24T09:00:00Z")])
    compare = snap_client.post(
        f"/api/v1/search/snapshots/{snap_client.get('/api/v1/search/snapshots').json()['items'][0]['id']}/compare"
    )
    assert compare.status_code == 200
    body = compare.json()
    assert body["added"] == [encode_entry_ref("a4")]
    assert body["removed"] == []
    assert body["rankChanges"] == []
    assert body["permissionLost"] == []
    assert body["counts"]["snapshot"] == 3
    assert body["counts"]["current"] == 4
    assert body["complete"] is True


def test_rank_changes_reported_over_threshold(snap_client):
    from lumirss.main import app as lumi_app

    snapshot_id = _freeze(snap_client).json()["id"]
    # 插入 7 条更新条目 → 原引用全部后移 7 位（> 5 阈值）。
    rows = [
        _row(f"n{i}", f"Rust 动态 {i}", f"2026-09-24T1{i:02d}:00:00Z")
        for i in range(7)
    ]
    _seed(lumi_app, rows)
    body = snap_client.post(
        f"/api/v1/search/snapshots/{snapshot_id}/compare"
    ).json()
    moved = {r["entryRef"]: (r["oldRank"], r["newRank"]) for r in body["rankChanges"]}
    assert moved[encode_entry_ref("a1")] == (1, 8)
    assert moved[encode_entry_ref("a2")] == (2, 9)
    assert len(body["rankChanges"]) == 3


def test_permission_lost_when_row_no_longer_resolves(snap_client):
    from lumirss.main import app as lumi_app

    snapshot_id = _freeze(snap_client).json()["id"]
    # a2 直接从本账户投影消失（不再解析）→ removed 且 permissionLost。
    _delete_refs(lumi_app, ["a2"])
    body = snap_client.post(
        f"/api/v1/search/snapshots/{snapshot_id}/compare"
    ).json()
    assert body["removed"] == [encode_entry_ref("a2")]
    assert body["permissionLost"] == [encode_entry_ref("a2")]
    assert encode_entry_ref("a1") not in body["removed"]
    assert body["counts"]["permissionLost"] == 1


def test_compare_and_list_missing_snapshot_404(snap_client):
    missing = snap_client.post("/api/v1/search/snapshots/nope/compare")
    assert missing.status_code == 404
    assert missing.json()["error"]["type"] == "search_snapshot_not_found"


def test_snapshot_cap_prunes_oldest(snap_client):
    ids = [_freeze(snap_client).json()["id"] for _ in range(21)]
    listing = snap_client.get("/api/v1/search/snapshots").json()["items"]
    assert len(listing) == 20
    remaining = {item["id"] for item in listing}
    assert ids[0] not in remaining  # 最老被淘汰
    assert ids[-1] in remaining
