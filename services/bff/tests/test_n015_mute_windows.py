"""N015 来源分时静音 —— 窗口校验、存储、时间线消费点与负向契约。

- 校验：days ⊆ 0-6、HH:MM 严格格式、≤7 窗口/来源、start≠end；
  非法定义 → 422 稳定错误码，零写入；
- 窗口语义：end<start 跨午夜（含「昨天在 days 里」的后半段归属）；
- 消费点：与 hiddenUntil/showFrom 完全一致——只过滤通用时间线
  （all/unread 无 scope）；窗口未命中自动恢复；
- 负向契约：静音窗口命中期间，搜索（/api/v1/search）照常返回该来源
  条目——抓取/索引/搜索/阅读不受影响。
"""

import asyncio
from datetime import datetime
from types import SimpleNamespace

from lumirss.main import app
from lumirss.mute_windows import MuteWindowsInvalid, validate_windows, window_hit

FEED_URL = "https://feed.example.com/rss"
OTHER_URL = "https://other.example.com/rss"


def run(coroutine):
    return asyncio.run(coroutine)


def _entry(entry_ref: str):
    from lumirss.adapters.freshrss import EntryListItem

    return EntryListItem(
        entryRef=entry_ref,
        title=f"T {entry_ref}",
        feedTitle="源",
        author=None,
        url=None,
        publishedAt="2026-09-20T00:00:00Z",
        read=False,
        starred=False,
    )


def _install_adapter(entries):
    async def _list_entries(*, view="all", feed_url=None, category_id=None, source_type=None, continuation=None):
        return SimpleNamespace(items=list(entries), upstreamContinuation=None)

    app.state.freshrss_adapter = SimpleNamespace(list_entries=_list_entries)


async def _seed_projection(pairs: list[tuple[str, str]]):
    await app.state.db.migrate()
    for ref, url in pairs:
        await app.state.db.execute(
            "INSERT INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (ref, ref, url, "源", ref, "", "", "正文", "2026-09-20T00:00:00Z", 0, 0, 1789660000),
        )


# ---- 纯函数：校验与窗口命中 ---------------------------------------------------


def test_n015_validation():
    ok = validate_windows([{"days": [1, 3, 5], "start": "22:00", "end": "06:00"}])
    assert ok == [{"days": [1, 3, 5], "start": "22:00", "end": "06:00"}]
    assert validate_windows([]) is None
    assert validate_windows(None) is None

    def bad(raw):
        try:
            validate_windows(raw)
        except MuteWindowsInvalid:
            return True
        raise AssertionError(f"必须拒绝：{raw}")

    assert bad([{"days": [7], "start": "08:00", "end": "09:00"}])  # day 越界
    assert bad([{"days": ["1"], "start": "08:00", "end": "09:00"}])  # 非整数
    assert bad([{"days": [1], "start": "8:00", "end": "09:00"}])  # HH:MM 格式
    assert bad([{"days": [1], "start": "24:00", "end": "09:00"}])  # 时刻越界
    assert bad([{"days": [1], "start": "08:00", "end": "08:00"}])  # 空窗口
    assert bad([{"days": [1], "start": "08:00"}])  # 缺 end
    assert bad([{"days": [1], "start": "08:00", "end": "09:00", "x": 1}])  # 未知键
    assert bad([{"days": [i for i in range(7)]} for _ in range(8)])  # >7 窗口


def test_n015_window_hit_wraps_midnight():
    # 周三（js_day=3）22:00-06:00：周三 23:30 命中
    window = {"days": [3], "start": "22:00", "end": "06:00"}
    assert window_hit(window, datetime(2026, 9, 23, 23, 30))  # 周三
    assert not window_hit(window, datetime(2026, 9, 23, 12, 0))  # 周三中午
    # 跨午夜后半段：周四 01:30——「昨天（周三）在 days 里」才命中
    assert window_hit(window, datetime(2026, 9, 24, 1, 30))  # 周四凌晨
    assert not window_hit(window, datetime(2026, 9, 25, 1, 30))  # 周五凌晨（昨天周四不在 days）
    # 0=周日 对齐（js getDay）：2026-09-20 是周日
    sunday = {"days": [0], "start": "08:00", "end": "09:00"}
    assert window_hit(sunday, datetime(2026, 9, 20, 8, 30))
    assert not window_hit(sunday, datetime(2026, 9, 21, 8, 30))  # 周一


# ---- 存储与路由 ---------------------------------------------------------------


def test_n015_store_roundtrip_and_sentinel(client):
    async def _scenario():
        from lumirss.mute_windows import set_mute_windows
        from lumirss.source_overrides import SourceOverrideStore

        db = app.state.db
        windows = await set_mute_windows(
            db, FEED_URL, [{"days": [1, 2], "start": "09:00", "end": "18:00"}]
        )
        assert windows == [{"days": [1, 2], "start": "09:00", "end": "18:00"}]
        stored = await SourceOverrideStore(db).get_override(FEED_URL)
        assert stored is not None
        assert stored["muteWindows"] == [{"days": [1, 2], "start": "09:00", "end": "18:00"}]
        # 其它维度共存：设置 hidden 后窗口仍在；清空 hidden 后行不丢
        await SourceOverrideStore(db).set_fields(FEED_URL, hidden_until="2099-01-01T00:00:00Z")
        await SourceOverrideStore(db).set_fields(FEED_URL, hidden_until=None)
        stored = await SourceOverrideStore(db).get_override(FEED_URL)
        assert stored is not None and stored["muteWindows"] is not None
        # 清除（None = 清空维度）
        await set_mute_windows(db, FEED_URL, None)
        stored = await SourceOverrideStore(db).get_override(FEED_URL)
        assert stored is None  # 所有维度皆空 → 行清理

    run(_scenario())


def test_n015_route_validation_and_listing(client):
    ok = client.put(
        "/api/v1/sources/overrides",
        json={"feedUrl": FEED_URL, "muteWindows": [{"days": [0, 6], "start": "23:00", "end": "01:00"}]},
    )
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["muteWindows"] == [{"days": [0, 6], "start": "23:00", "end": "01:00"}]

    listing = client.get("/api/v1/sources/overrides").json()
    assert any(item["feedUrl"] == FEED_URL for item in listing["items"])

    invalid = client.put(
        "/api/v1/sources/overrides",
        json={"feedUrl": FEED_URL, "muteWindows": [{"days": [9], "start": "x", "end": "01:00"}]},
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["type"] == "invalid_mute_windows"

    cleared = client.put(
        "/api/v1/sources/overrides", json={"feedUrl": FEED_URL, "muteWindows": None}
    )
    assert cleared.status_code == 200
    assert cleared.json()["muteWindows"] is None


def test_n015_timeline_consumption_and_search_unaffected(client):
    _install_adapter([_entry("e1.n015"), _entry("e2.other")])
    run(_seed_projection([("e1.n015", FEED_URL), ("e2.other", OTHER_URL)]))
    # 全天全周静音（两个窗口并集覆盖全部 1440 分钟）→ 此刻必然命中
    response = client.put(
        "/api/v1/sources/overrides",
        json={
            "feedUrl": FEED_URL,
            "muteWindows": [
                {"days": list(range(7)), "start": "00:00", "end": "23:59"},
                {"days": list(range(7)), "start": "23:59", "end": "00:01"},
            ],
        },
    )
    assert response.status_code == 200, response.text

    # 通用时间线：静音中的来源条目被过滤；其它来源不受影响
    timeline = client.get("/api/v1/entries?view=all").json()
    refs = [item["entryRef"] for item in timeline["items"]]
    assert "e1.n015" not in refs, "静音窗口命中期内不出现在通用时间线"
    assert "e2.other" in refs

    # 来源显式 scope 不受影响（与 hiddenUntil 同款豁免）
    scoped = client.get(f"/api/v1/entries?feedUrl={FEED_URL}").json()
    assert "e1.n015" in [item["entryRef"] for item in scoped["items"]]

    # 负向契约：搜索照常返回静音中的来源条目（服务端照常索引）
    searched = client.get("/api/v1/search?q=e1").json()
    hit_refs = [item["entryRef"] for item in searched["items"]]
    assert "e1.n015" in hit_refs, "搜索不受分时静音影响"

    # 窗口未命中（收窄窗口 + 注入窗外时刻）→ 时间线自动恢复
    narrow = client.put(
        "/api/v1/sources/overrides",
        json={"feedUrl": FEED_URL, "muteWindows": [{"days": list(range(7)), "start": "01:00", "end": "02:00"}]},
    )
    assert narrow.status_code == 200

    async def _filtered_at(moment: datetime):
        from lumirss.adapters.freshrss import EntryListItem
        from lumirss.source_overrides import filter_timeline_items

        items = [
            EntryListItem(
                entryRef="e1.n015",
                title="T",
                feedTitle="源",
                author=None,
                url=None,
                publishedAt="2026-09-20T00:00:00Z",
                read=False,
                starred=False,
            )
        ]
        kept = await filter_timeline_items(app.state.db, items, now_local=moment)
        return [item.entryRef for item in kept]

    import datetime as _dt

    outside = _dt.datetime(2099, 1, 1, 12, 0)  # 12:00 在 01:00-02:00 窗口外
    refs_at = run(_filtered_at(outside))
    assert refs_at == ["e1.n015"], "窗口未命中时时间线自动恢复"
    inside = _dt.datetime(2099, 1, 1, 1, 30)  # 01:30 在窗口内
    assert run(_filtered_at(inside)) == []
