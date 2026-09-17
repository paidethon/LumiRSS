"""F11 暂时隐藏来源 / F13 阅读起点 — 覆盖存储、路由与时间线过滤。

- 覆盖 CRUD：set/clear/keep sentinel 语义、非法时间 400、归一化 UTC Z；
- 时间线过滤：只作用于 all/unread 通用时间线；hidden_until 到期自动
  恢复；show_from 隐藏更早历史；投影未覆盖的条目不误删；
- feedUrl/categoryId 显式 scope 不受覆盖影响。
"""

import asyncio
from types import SimpleNamespace

from lumirss.main import app
from lumirss.source_overrides import SourceOverrideStore


def run(coroutine):
    return asyncio.run(coroutine)


def _store():
    return SourceOverrideStore(app.state.db)


def _install_adapter(feeds: list[str], entries: list[SimpleNamespace]):
    subs = [SimpleNamespace(stream_id=f"feed/{i}", feed_url=u, title=f"源 {i}") for i, u in enumerate(feeds)]

    async def _list_subs():
        return subs

    async def _list_entries(*, view="all", feed_url=None, category_id=None, source_type=None, continuation=None):
        return SimpleNamespace(items=list(entries), upstreamContinuation=None)

    app.state.freshrss_adapter = SimpleNamespace(
        list_subscriptions=_list_subs, list_entries=_list_entries
    )


def _entry(entry_ref: str, published: str = "2026-09-18T00:00:00Z"):
    from lumirss.adapters.freshrss import EntryListItem

    return EntryListItem(
        entryRef=entry_ref,
        title=f"T {entry_ref}",
        feedTitle="源",
        author=None,
        url=None,
        publishedAt=published,
        read=False,
        starred=False,
    )


def test_f11_override_crud_sentinels_and_expiry(client):
    store = _store()
    url = "https://feed.example.com/rss"
    # 隐式 keep：只设 show_from，hidden_until 保持 NULL
    result = run(store.set_fields(url, show_from="2026-09-18T00:00:00+08:00"))
    assert result["showFrom"] == "2026-09-17T16:00:00Z"  # 归一化 UTC Z
    assert result["hiddenUntil"] is None
    # 只设 hidden_until；非法串 → 视为清除
    result = run(store.set_fields(url, hidden_until="not-a-time"))
    assert result["hiddenUntil"] is None
    result = run(store.set_fields(url, hidden_until="2099-01-01T00:00:00Z"))
    assert result["hiddenUntil"] == "2099-01-01T00:00:00Z"
    # 到期后不再处于隐藏集
    assert url in run(store.active_hidden_feed_urls("2026-01-01T00:00:00Z"))
    assert url not in run(store.active_hidden_feed_urls("2099-06-01T00:00:00Z"))
    # 清空 show_from → 行清理（无有效覆盖）
    result = run(store.set_fields(url, hidden_until=None, show_from=None))
    assert result["hiddenUntil"] is None and result["showFrom"] is None
    assert run(store.get_override(url)) is None


def test_f11_f13_timeline_filter_and_scope_exemption(client):
    hidden_url = "https://hidden.example.com/rss"
    started_url = "https://started.example.com/rss"
    plain_url = "https://plain.example.com/rss"
    _install_adapter(
        [hidden_url, started_url, plain_url],
        [
            _entry("e1.hidden", "2026-09-18T00:00:00Z"),
            _entry("e2.started-old", "2026-01-01T00:00:00Z"),
            _entry("e3.started-new", "2026-09-18T00:00:00Z"),
            _entry("e4.plain"),
        ],
    )
    store = _store()
    run(store.set_fields(hidden_url, hidden_until="2099-01-01T00:00:00Z"))
    run(store.set_fields(started_url, show_from="2026-09-01T00:00:00Z"))

    # 投影种 feed 归属（模拟 search_entries 已同步）
    async def _seed():
        await app.state.db.migrate()
        seeds = [
            ("e1.hidden", hidden_url, "2026-09-18T00:00:00Z"),
            ("e2.started-old", started_url, "2026-01-01T00:00:00Z"),
            ("e3.started-new", started_url, "2026-09-18T00:00:00Z"),
            ("e4.plain", plain_url, "2026-09-18T00:00:00Z"),
        ]
        for ref, url, published in seeds:
            await app.state.db.execute(
                "INSERT INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (ref, ref, url, "源", ref, "", "", "", published, 0, 0, 1789660000),
            )

    run(_seed())

    body = client.get("/api/v1/entries?view=all").json()
    refs = [item["entryRef"] for item in body["items"]]
    assert "e4.plain" in refs
    assert "e3.started-new" in refs
    assert "e1.hidden" not in refs, "隐藏期内不得出现在通用时间线"
    assert "e2.started-old" not in refs, "早于阅读起点的历史不出现"
    # 来源页（feedUrl scope）不受覆盖影响：显式打开 = 明确要看
    scoped = client.get(f"/api/v1/entries?feedUrl={hidden_url}").json()
    scoped_refs = [item["entryRef"] for item in scoped["items"]]
    assert "e1.hidden" in scoped_refs


def test_f11_overrides_api_routes(client):
    url = "https://api.example.com/rss"
    response = client.put(
        "/api/v1/sources/overrides",
        json={"feedUrl": url, "hiddenUntil": "2099-01-01T00:00:00Z"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["hiddenUntil"] == "2099-01-01T00:00:00Z"

    listing = client.get("/api/v1/sources/overrides").json()
    assert any(item["feedUrl"] == url for item in listing["items"])

    bad = client.put(
        "/api/v1/sources/overrides",
        json={"feedUrl": url, "hiddenUntil": "garbage"},
    )
    assert bad.status_code == 400

    cleared = client.put(
        "/api/v1/sources/overrides",
        json={"feedUrl": url, "hiddenUntil": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["hiddenUntil"] is None
