"""E1: N038 按来源保留策略预演（服务端）。

- 预览数学：投影口径 COUNT（older = published < now-N 天）；
  starred 恒排除且单独计数（绝不进 prunable）；
- apply：落库 source_overrides.retention_days；prune=true 时立即裁剪
  本地投影（starred 排除）；
- **FreshRSS 零调用**：适配器 mock 全程零调用（负向契约）。
"""

import asyncio

from lumirss.entryref import encode_entry_ref


def run(coroutine):
    return asyncio.run(coroutine)


class RecordingAdapter:
    """N038 负向契约：任何调用都记录——断言全程为空 = FreshRSS 未触碰。"""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def __getattr__(self, name):
        async def _record(*args, **kwargs):
            self.calls.append((name, args, kwargs))

        return _record


def _seed(app, item_id, *, published_at, starred=0, feed_url="https://f.example/rss"):
    entry_ref = encode_entry_ref(item_id)
    run(
        app.state.db.execute(
            "INSERT OR IGNORE INTO search_entries (item_id, entry_ref, feed_url,"
            " feed_title, title, author, url, content_text, published_at, read,"
            " starred, fetched_at) VALUES (?, ?, ?, '源', 't', '', 'u', 'c', ?, 0, ?, 0)",
            (item_id, entry_ref, feed_url, published_at, starred),
        )
    )
    return entry_ref


def test_n038_preview_math_and_starred_exclusion(client):
    app = client.app
    run(app.state.db.migrate())
    # 3 条早于 30 天（1 条加星）+ 1 条新 + 1 条其他来源的旧条目。
    _seed(app, "p1", published_at="2026-01-01T00:00:00Z")
    _seed(app, "p2", published_at="2026-02-01T00:00:00Z")
    _seed(app, "p3", published_at="2026-03-01T00:00:00Z", starred=1)
    _seed(app, "p4", published_at="2026-09-20T00:00:00Z")
    _seed(app, "p5", published_at="2026-01-15T00:00:00Z", feed_url="https://other.example/rss")

    response = client.get(
        "/api/v1/sources/retention-preview",
        params={"feedUrl": "https://f.example/rss", "days": 30},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["feedUrl"] == "https://f.example/rss"
    assert body["retentionDays"] == 30
    assert body["totalEntries"] == 4  # 只看该来源
    assert body["olderEntries"] == 3  # p1/p2/p3
    assert body["starredExcluded"] == 1  # p3 恒排除且单独计数
    assert body["prunableEntries"] == 2  # p1/p2
    # 诚实标注：预演基于投影 + 原生界面提示
    assert "投影" in body["note"]
    assert "FreshRSS 原生界面" in body["note"]


def test_n038_apply_stores_retention_days_and_prunes_projection(client):
    app = client.app
    run(app.state.db.migrate())
    _seed(app, "q1", published_at="2026-01-01T00:00:00Z")
    _seed(app, "q2", published_at="2026-01-01T00:00:00Z", starred=1)
    _seed(app, "q3", published_at="2026-09-20T00:00:00Z")

    fake = RecordingAdapter()
    app.state.freshrss_adapter = fake
    try:
        response = client.post(
            "/api/v1/sources/retention-apply",
            json={"feedUrl": "https://f.example/rss", "days": 30, "prune": True},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["retentionDays"] == 30
        assert body["prunedProjectionEntries"] == 1  # q1（q2 加星恒保留）
        assert body["freshrssTouched"] is False
        # 负向契约：适配器 mock 全程零调用（FreshRSS 未被触碰）。
        assert fake.calls == []
    finally:
        app.state.freshrss_adapter = None

    # 落库验证：retention_days 进 source_overrides（可再次读取）。
    reapply = client.post(
        "/api/v1/sources/retention-apply",
        json={"feedUrl": "https://f.example/rss", "days": None},
    )
    assert reapply.status_code == 200
    assert reapply.json()["retentionDays"] is None  # 清除策略
    # 越界拒绝
    bad = client.post(
        "/api/v1/sources/retention-apply",
        json={"feedUrl": "https://f.example/rss", "days": 3},
    )
    assert bad.status_code == 422


def test_n038_prune_projection_regenerable_rows_return_on_sync_note(client):
    """prune 只删本地投影——starred 排除；投影可再生成（诚实行为，
    文档化：下次同步可能回填）。这里验证 starred 行为与回显。"""
    app = client.app
    run(app.state.db.migrate())
    _seed(app, "z1", published_at="2026-01-01T00:00:00Z")
    _seed(app, "z2", published_at="2026-01-01T00:00:00Z", starred=1)
    from lumirss.source_retention import prune_projection

    pruned = run(prune_projection(app.state.db, "https://f.example/rss", days=30))
    assert pruned == 1
    left = run(
        app.state.db.fetch_all(
            "SELECT item_id FROM search_entries WHERE feed_url = 'https://f.example/rss'", ()
        )
    )
    assert [row["item_id"] for row in left] == ["z2"]
