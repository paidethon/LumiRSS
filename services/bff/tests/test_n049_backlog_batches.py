"""E1: N049 阅读积压分批处理（服务端）。

- 分组：groupBy=source（key=feed_url）| age（固定账龄桶）；count =
  服务端真实全量计数；entryRefs ≤100；候选口径与 F024 一致（未读 +
  未加星 + 不在稍后读 + 早于截止）；
- 每批确认走两段式 token（条件漂移 → 409）；执行走既有 set-read
  管线（适配器 + 投影镜像）；
- 每批撤销：台账（cap 5）记录实际置读成功的 refs；undo 恢复 read=0；
  重复撤销 → 409。
"""

import asyncio

from lumirss.entryref import encode_entry_ref


def run(coroutine):
    return asyncio.run(coroutine)


class FakeStateAdapter:
    """记录 set_entry_state 调用（FreshRSS 侧断言用）。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, bool | None, bool | None]] = []

    async def set_entry_state(self, item_id, read=None, starred=None):
        self.calls.append((str(item_id), read, starred))


def _seed(app, item_id, *, feed_url, published_at, read=0, starred=0, title="t"):
    entry_ref = encode_entry_ref(item_id)
    run(
        app.state.db.execute(
            "INSERT OR IGNORE INTO search_entries (item_id, entry_ref, feed_url,"
            " feed_title, title, author, url, content_text, published_at, read,"
            " starred, fetched_at) VALUES (?, ?, ?, '源', ?, '', 'u', 'c', ?, ?, ?, 0)",
            (item_id, entry_ref, feed_url, title, published_at, read, starred),
        )
    )
    return entry_ref


def _seed_batch(app):
    """feed A：2 条旧（30-90 天桶）；feed B：1 条旧 + 1 条加星（保护）。"""
    _seed(app, "g1", feed_url="https://a.example/rss", published_at="2026-07-01T00:00:00Z")
    _seed(app, "g2", feed_url="https://a.example/rss", published_at="2026-08-01T00:00:00Z")
    _seed(app, "g3", feed_url="https://b.example/rss", published_at="2026-07-15T00:00:00Z")
    _seed(app, "g4", feed_url="https://b.example/rss", published_at="2026-07-20T00:00:00Z", starred=1)
    _seed(app, "g5", feed_url="https://a.example/rss", published_at="2026-09-24T00:00:00Z")  # 太新


def test_n049_grouping_by_source_and_age(client):
    app = client.app
    run(app.state.db.migrate())
    _seed_batch(app)

    by_source = client.get(
        "/api/v1/entries/backlog/batches",
        params={"groupBy": "source", "olderThanDays": 7},
    )
    assert by_source.status_code == 200, by_source.text
    batches = by_source.json()["batches"]
    keys = {batch["key"]: batch["count"] for batch in batches}
    assert keys == {
        "https://a.example/rss": 2,  # g1/g2（g5 太新、排除）
        "https://b.example/rss": 1,  # g3（g4 加星保护）
    }
    for batch in batches:
        assert len(batch["entryRefs"]) == batch["count"]
        assert batch["count"] <= 100  # refs 有界（count 是真实全量计数）

    by_age = client.get(
        "/api/v1/entries/backlog/batches",
        params={"groupBy": "age", "olderThanDays": 7},
    )
    assert by_age.status_code == 200
    age_keys = {batch["key"]: batch["count"] for batch in by_age.json()["batches"]}
    # g1(2026-07-01)≈86 天、g2≈56 天、g3≈72 天 → 30-90天 桶 3 条；
    # 没有 90-365 / 365+ 的条目（空桶不出现）。
    assert age_keys == {"30-90天": 3}

    # 非法 groupBy → 422。
    bad = client.get(
        "/api/v1/entries/backlog/batches",
        params={"groupBy": "color", "olderThanDays": 7},
    )
    assert bad.status_code == 422


def test_n049_batch_two_phase_confirm_and_undo_restores(client):
    app = client.app
    run(app.state.db.migrate())
    _seed_batch(app)

    # 两段式第一步：单批预览（feed A 批）。
    preview = client.post(
        "/api/v1/entries/backlog/batch-preview",
        json={
            "groupBy": "source",
            "key": "https://a.example/rss",
            "olderThanDays": 7,
        },
    )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["count"] == 2
    assert body["effectiveExclusions"] == ["starred", "read-later"]

    fake = FakeStateAdapter()
    app.state.freshrss_adapter = fake
    try:
        # 篡改条件 → 409（防条件漂移）。
        drifted = client.post(
            "/api/v1/entries/backlog/batch-apply",
            json={
                "groupBy": "source",
                "key": "https://a.example/rss",
                "olderThanDays": 30,  # 与预览不同
                "confirmPreviewToken": body["confirmPreviewToken"],
            },
        )
        assert drifted.status_code == 409

        applied = client.post(
            "/api/v1/entries/backlog/batch-apply",
            json={
                "groupBy": "source",
                "key": "https://a.example/rss",
                "olderThanDays": 7,
                "confirmPreviewToken": body["confirmPreviewToken"],
            },
        )
        assert applied.status_code == 200, applied.text
        result = applied.json()
        assert result["applied"] == 2
        assert result["failed"] == []
        assert result["undoAvailable"] is True
        log_id = result["batchLogId"]
    finally:
        app.state.freshrss_adapter = None

    # 投影镜像：feed A 两条已置读；feed B 未触碰。
    rows = run(
        app.state.db.fetch_all(
            "SELECT item_id, read FROM search_entries WHERE feed_url = 'https://a.example/rss'",
            ()
        )
    )
    read_map = {row["item_id"]: int(row["read"]) for row in rows}
    assert read_map == {"g1": 1, "g2": 1, "g5": 0}

    # 撤销台账：一批可撤销。
    logs = client.get("/api/v1/entries/backlog/batches/log").json()["items"]
    assert len(logs) == 1
    assert logs[0]["id"] == log_id
    assert logs[0]["undone"] is False

    # 撤销：恢复 read=0（适配器 + 投影镜像）。
    fake = FakeStateAdapter()
    app.state.freshrss_adapter = fake
    try:
        undone = client.post(f"/api/v1/entries/backlog/batches/{log_id}/undo")
        assert undone.status_code == 200, undone.text
        assert undone.json()["undone"] is True
    finally:
        app.state.freshrss_adapter = None
    assert {item_id for item_id, read, _ in fake.calls if read is False} == {"g1", "g2"}
    rows = run(
        app.state.db.fetch_all(
            "SELECT item_id, read FROM search_entries WHERE item_id IN ('g1','g2')", ()
        )
    )
    assert all(int(row["read"]) == 0 for row in rows)

    # 重复撤销 → 409 backlog_batch_already_undone。
    fake = FakeStateAdapter()
    app.state.freshrss_adapter = fake
    try:
        again = client.post(f"/api/v1/entries/backlog/batches/{log_id}/undo")
        assert again.status_code == 409
        assert again.json()["error"]["type"] == "backlog_batch_already_undone"
    finally:
        app.state.freshrss_adapter = None


def test_n049_batch_log_capped_at_five(client):
    app = client.app
    run(app.state.db.migrate())
    _seed_batch(app)
    for _i in range(7):
        preview = client.post(
            "/api/v1/entries/backlog/batch-preview",
            json={
                "groupBy": "source",
                "key": "https://b.example/rss",
                "olderThanDays": 7,
            },
        )
        assert preview.status_code == 200
        app.state.freshrss_adapter = FakeStateAdapter()
        try:
            response = client.post(
                "/api/v1/entries/backlog/batch-apply",
                json={
                    "groupBy": "source",
                    "key": "https://b.example/rss",
                    "olderThanDays": 7,
                    "confirmPreviewToken": preview.json()["confirmPreviewToken"],
                },
            )
            assert response.status_code == 200
            assert response.json()["applied"] == 1
        finally:
            app.state.freshrss_adapter = None
        # 复位投影已读，让下一批仍有可执行候选（台账每次都新增一行）。
        run(
            app.state.db.execute(
                "UPDATE search_entries SET read = 0 WHERE item_id = 'g3'", ()
            )
        )
    logs = client.get("/api/v1/entries/backlog/batches/log").json()["items"]
    assert len(logs) == 5  # cap 5（插入时裁最旧）


def test_n049_undo_unknown_log_404(client):
    run(client.app.state.db.migrate())
    response = client.post("/api/v1/entries/backlog/batches/bbl-nope/undo")
    assert response.status_code == 404
    assert response.json()["error"]["type"] == "backlog_batch_log_not_found"
