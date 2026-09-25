"""E1: N036 刷新队列可视化 + N037 断更恢复补读（服务端）。

- N036：source_refresh_log 只由两条路径写入——F050 手动探测
  （POST /subscriptions/health-check）与投影同步的 store 调用；**没有
  新调度器**（负向契约：不调任何端点、不跑任何同步时，日志零变化）；
  GET /sources/refresh-status 给 lastChecked/lastResult/pending + 最近 5；
  「立即检查」= 复用既有探测端点（不另设端点）；
- N037：error/stale → ok 跳变自动建恢复窗口（refs ≤50，窗口事实）；
  to-queue 一次性消费（重复 → 409）；逐条 add 幂等去重（同日同 ref
  绝不重复入队）。
"""

import asyncio

from lumirss.entryref import encode_entry_ref


def run(coroutine):
    return asyncio.run(coroutine)


def _seed(
    app,
    item_id: str,
    *,
    feed_url: str = "https://f.example/rss",
    url: str = "https://ex.com/a",
    published_at: str,
    fetched_at: int,
    read: int = 0,
) -> str:
    entry_ref = encode_entry_ref(item_id)
    run(
        app.state.db.execute(
            "INSERT OR IGNORE INTO search_entries (item_id, entry_ref, feed_url,"
            " feed_title, title, author, url, content_text, published_at, read,"
            " starred, fetched_at) VALUES (?, ?, ?, '源', 't', '', ?, 'c', ?, ?, 0, ?)",
            (item_id, entry_ref, feed_url, url, published_at, read, fetched_at),
        )
    )
    return entry_ref


# ---- N036 --------------------------------------------------------------------


def test_n036_no_scheduler_log_only_changes_on_probe(client):
    """负向契约：没有调度器——不触发探测/同步时刷新日志零变化；
    「立即检查」（既有 F050 端点）后才产生记录。"""
    from types import SimpleNamespace

    from lumirss.main import app

    run(app.state.db.migrate())

    async def rows():
        return await app.state.db.fetch_all("SELECT * FROM source_refresh_log", ())

    # 静置：无人触发 → 零记录（无调度器）。
    assert run(rows()) == []

    # 安装订阅 + 注入探测（绝不打真实网络）。
    from lumirss.subscriptionref import encode_subscription_ref

    sub = SimpleNamespace(
        stream_id="feed/1",
        subscription_ref=encode_subscription_ref("feed/1"),
        title="源",
        feed_url="https://f.example/rss",
        category_id=None,
        category_label=None,
    )

    async def _list():
        return [sub]

    app.state.freshrss_control_adapter = SimpleNamespace(list_subscriptions=_list)

    async def fake_probe(feed_url, timeout_s):
        return {"status": "ok", "httpStatus": 200}

    app.state.health_probe = fake_probe
    try:
        response = client.post(
            "/api/v1/subscriptions/health-check",
            json={"refs": [sub.subscription_ref], "timeoutS": 3},
        )
        assert response.status_code == 200, response.text
    finally:
        app.state.health_probe = None
        app.state.freshrss_control_adapter = None

    logged = run(rows())
    assert len(logged) == 1
    assert logged[0]["result"] == "ok"
    assert int(logged[0]["entry_count"]) == 0  # 探测不数条目（诚实）


def test_n036_refresh_status_view_and_probe_stale_classification(client):
    """status 视图：lastChecked/lastResult/pending + 最近 5 条；探测 ok
    但投影最新条目早于阈值 → stale（断更中）。"""
    from types import SimpleNamespace

    from lumirss.main import app
    from lumirss.subscriptionref import encode_subscription_ref

    run(app.state.db.migrate())
    _seed(
        app,
        "old1",
        published_at="2026-08-01T00:00:00Z",
        fetched_at=0,
    )  # 远早于默认 7×24h 阈值

    sub = SimpleNamespace(
        stream_id="feed/1",
        subscription_ref=encode_subscription_ref("feed/1"),
        title="源",
        feed_url="https://f.example/rss",
        category_id=None,
        category_label=None,
    )

    async def _list():
        return [sub]

    app.state.freshrss_control_adapter = SimpleNamespace(list_subscriptions=_list)

    async def fake_probe(feed_url, timeout_s):
        return {"status": "ok", "httpStatus": 200}

    app.state.health_probe = fake_probe
    try:
        response = client.post(
            "/api/v1/subscriptions/health-check",
            json={"refs": [sub.subscription_ref], "timeoutS": 3},
        )
        assert response.status_code == 200
    finally:
        app.state.health_probe = None
        app.state.freshrss_control_adapter = None

    status = client.get("/api/v1/sources/refresh-status")
    assert status.status_code == 200, status.text
    feeds = status.json()["feeds"]
    assert len(feeds) == 1
    feed = feeds[0]
    assert feed["feedUrl"] == "https://f.example/rss"
    assert feed["lastResult"] == "stale"  # 可达但断更
    assert feed["pending"] is True
    assert len(feed["recent"]) == 1
    assert feed["recoveryAvailable"] is False  # 尚未恢复


def test_n036_sync_path_records_ok_with_entry_count(client):
    """投影同步路径：store.record(ok, entry_count) —— 有交付的来源才
    记录（诚实于全量扫描，不为无变化来源编造行）。"""
    app = client.app
    run(app.state.db.migrate())
    from lumirss.refresh_log import SourceRefreshLogStore

    store = SourceRefreshLogStore(app.state.db)
    run(store.record("https://a.example/rss", "ok", entry_count=3))
    run(store.record("https://a.example/rss", "error"))
    run(store.record("https://b.example/rss", "ok", entry_count=1))
    view = run(store.status_snapshot())
    by_feed = {feed["feedUrl"]: feed for feed in view["feeds"]}
    assert by_feed["https://a.example/rss"]["lastResult"] == "error"
    assert by_feed["https://a.example/rss"]["pending"] is True
    assert by_feed["https://b.example/rss"]["lastResult"] == "ok"
    assert by_feed["https://b.example/rss"]["pending"] is False
    # 每源保留 20 条（有界）
    for _ in range(25):
        run(store.record("https://a.example/rss", "ok", entry_count=0))
    count = run(
        app.state.db.fetch_one(
            "SELECT COUNT(*) AS n FROM source_refresh_log WHERE feed_url = 'https://a.example/rss'",
            (),
        )
    )
    assert int(count["n"]) <= 20


# ---- N037 --------------------------------------------------------------------


def test_n037_transition_creates_recovery_and_to_queue_dedups(client):
    """跳变建窗（error→ok）；to-queue 加入（source=recovery）；
    一次性消费（重复 → 409）；同日同 ref 绝不重复入队。"""
    from lumirss.main import app

    run(app.state.db.migrate())
    import time

    from lumirss.refresh_log import SourceRefreshLogStore

    store = SourceRefreshLogStore(app.state.db)
    # 真实时序：先断更报错 → 断更期间条目堆积（fetched_at 在窗口内）
    # → 恢复（ok）。窗口事实 = [error.checked_at, ok.checked_at]。
    run(store.record("https://f.example/rss", "error"))
    now_epoch = int(time.time())
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now_epoch))
    # fetched_at ≥ error.checked_at（断更期间/恢复时才被投影接收）。
    _seed(app, "r1", published_at="2026-09-01T00:00:00Z", fetched_at=now_epoch)
    _seed(app, "r2", published_at="2026-09-02T00:00:00Z", fetched_at=now_epoch)
    _seed(app, "r3", published_at=now_iso, fetched_at=now_epoch)
    created = run(store.record("https://f.example/rss", "ok", entry_count=2))
    assert created is not None
    assert created["refCount"] == 3  # published 命中 r3 + fetched_at 补齐 r1/r2
    assert created["consumed"] is False

    # 未恢复前：ok→ok 不建窗。
    again = run(store.record("https://f.example/rss", "ok"))
    assert again is None

    recoveries = client.get("/api/v1/sources/recoveries")
    assert recoveries.status_code == 200
    items = recoveries.json()["items"]
    assert len(items) == 1
    recovery_id = items[0]["id"]

    # to-queue：加入（source=recovery）。
    response = client.post(
        f"/api/v1/sources/recoveries/{recovery_id}/to-queue", json={}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["added"] == 3
    assert body["duplicates"] == 0
    queue = client.get("/api/v1/queue/today")
    rows = queue.json()["items"]
    assert len(rows) == 3
    assert all(row["source"] == "recovery" for row in rows)

    # 一次性消费：重复 to-queue → 409 recovery_already_consumed。
    repeat = client.post(f"/api/v1/sources/recoveries/{recovery_id}/to-queue", json={})
    assert repeat.status_code == 409
    assert repeat.json()["error"]["type"] == "recovery_already_consumed"

    # 队列 dedup：直接重复 add 同 ref（source=recovery）→ 幂等 duplicate，
    # 队列行数不变。
    from lumirss.reading_queue import ReadingQueueStore

    q = ReadingQueueStore(app.state.db)
    _row, outcome = run(
        q.add_item(f"rss:{encode_entry_ref('r1')}", source="recovery")
    )
    assert outcome == "duplicate"
    queue_again = client.get("/api/v1/queue/today")
    assert len(queue_again.json()["items"]) == 3


def test_n037_unknown_recovery_404(client):
    response = client.post("/api/v1/sources/recoveries/rec-nope/to-queue", json={})
    assert response.status_code == 404
    assert response.json()["error"]["type"] == "recovery_not_found"
