"""NEW-242 来源时间轴 — 四类时间 + 出处说明 + 个人备注 + 隔离。

- 派生读：发表 / 接收来自 search_entries 投影（时间用相对现在播种，
  不用固定日历日期）；更新来自 entry_revisions；个人保存来自
  library_bookmarks；缺失项 available=false 并说明原因；
- 备注：每类时间至多一条（重复 PUT 是改写不是新建）；kind 非法 422；
- 隔离：A 的时间备注对 B 不可见（真实 RoutingDatabase）。
"""

from datetime import UTC, datetime, timedelta

from lumirss.entryref import encode_entry_ref
from new231_helpers import ab_session


def _seed_entry(client, item_id: str, *, with_revision: bool, days_ago: int) -> str:
    entry_ref = encode_entry_ref(item_id)
    app = client.app

    import asyncio

    from lumirss.user_scope import user_context

    fetched_epoch = int((datetime.now(UTC) - timedelta(days=days_ago)).timestamp())

    async def _seed():
        with user_context("owner"):
            await app.state.db.migrate()
            await app.state.db.execute(
                "INSERT OR IGNORE INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at) "
                "VALUES (?, ?, 'https://f.example/rss', '源', '时间轴文章', '', 'https://u.example/a', '正文', ?, 0, 0, ?)",
                (
                    item_id,
                    entry_ref,
                    (datetime.now(UTC) - timedelta(days=days_ago + 1)).isoformat(timespec="seconds"),
                    fetched_epoch,
                ),
            )
            if with_revision:
                await app.state.db.execute(
                    "INSERT INTO entry_revisions (entry_ref, captured_at, title_changed, prev_title, new_title, content_diff_summary, prev_hash, new_hash) "
                    "VALUES (?, ?, 0, '', '', ?, 'aa', 'bb')",
                    (
                        entry_ref,
                        (datetime.now(UTC) - timedelta(days=days_ago - 1)).isoformat(timespec="seconds"),
                        "content_changed",
                    ),
                )

    asyncio.run(_seed())
    return entry_ref


def _bookmark_rss(client, entry_ref: str) -> None:
    created = client.post(
        "/api/v1/library/bookmarks", json={"rssItemRef": f"rss:{entry_ref}", "title": "时间轴文章"}
    )
    assert created.status_code in (200, 201), created.text


def test_new242_timeline_sources_and_annotations(client):
    """四类时间齐全 → 每项带出处说明；备注写入/改写不翻倍；kind 非法 422。"""
    entry_ref = _seed_entry(client, "tl-1", with_revision=True, days_ago=3)
    _bookmark_rss(client, entry_ref)

    timeline = client.get(f"/api/v1/entries/{entry_ref}/source-timeline")
    assert timeline.status_code == 200
    body = timeline.json()
    assert body["projectionKnown"] is True
    by_kind = {item["kind"]: item for item in body["items"]}
    assert set(by_kind) == {"published", "received", "updated", "saved"}
    for item in by_kind.values():
        assert item["available"] is True
        assert item["source"]  # 每个时间都说明它从哪来
    assert by_kind["published"]["label"] == "发表"
    assert by_kind["updated"]["time"]  # entry_revisions captured_at

    # 缺失项诚实：没有修订记录的文章 → updated available=false + 说明
    plain_ref = _seed_entry(client, "tl-plain", with_revision=False, days_ago=2)
    plain = client.get(f"/api/v1/entries/{plain_ref}/source-timeline").json()
    updated = next(i for i in plain["items"] if i["kind"] == "updated")
    assert updated["available"] is False
    assert "修订记录" in updated["source"]

    # 备注：写入 → 列表 1 条；再 PUT → 仍是 1 条（改写）
    put = client.put(
        f"/api/v1/entries/{entry_ref}/source-timeline/annotations/published",
        json={"note": "feed 里这个时间可疑"},
    )
    assert put.status_code == 200, put.text
    put2 = client.put(
        f"/api/v1/entries/{entry_ref}/source-timeline/annotations/published",
        json={"note": "改口：其实是正确的"},
    )
    assert put2.status_code == 200
    listed = client.get(f"/api/v1/entries/{entry_ref}/source-timeline/annotations")
    items = listed.json()["items"]
    assert len(items) == 1
    assert items[0]["note"] == "改口：其实是正确的"

    bad_kind = client.put(
        f"/api/v1/entries/{entry_ref}/source-timeline/annotations/nonsense",
        json={"note": "备注"},
    )
    assert bad_kind.status_code == 422
    assert bad_kind.json()["error"]["type"] == "timeline_invalid"


def test_new242_unknown_entry_honest_empty(client):
    """投影中没有该文 → available 全 false，不编造时间。"""
    timeline = client.get("/api/v1/entries/e1.nope/source-timeline")
    assert timeline.status_code == 200
    body = timeline.json()
    assert body["projectionKnown"] is False
    assert all(item["available"] is False for item in body["items"])
    assert all(item["time"] is None for item in body["items"])


def test_new242_isolation_between_users(monkeypatch, tmp_path):
    """A 的时间备注对 B 不可见（真实 RoutingDatabase per-user 库）。"""
    with ab_session(monkeypatch, tmp_path) as session:
        member = session.activate_member("n24x-b")
        entry_ref = encode_entry_ref("tl-iso")
        put = session.client.put(
            f"/api/v1/entries/{entry_ref}/source-timeline/annotations/received",
            json={"note": "A 的抓取时间备注"},
            headers=session.owner,
        )
        assert put.status_code == 200, put.text

        b_list = session.client.get(
            f"/api/v1/entries/{entry_ref}/source-timeline/annotations", headers=member
        )
        assert b_list.status_code == 200
        assert b_list.json()["items"] == []

        a_list = session.client.get(
            f"/api/v1/entries/{entry_ref}/source-timeline/annotations", headers=session.owner
        )
        assert len(a_list.json()["items"]) == 1
