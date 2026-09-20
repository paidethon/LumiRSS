"""F049 导入批次追踪 — 批次计数如实、重试幂等、部分成功、截断标记。"""

import asyncio

from lumirss.import_batch_store import ImportBatchStore
from lumirss.main import app
from lumirss.subscriptionref import encode_subscription_ref


def _run(coroutine):
    return asyncio.run(coroutine)


def test_f049_record_counts_and_error_truncation(client):
    """批次计数如实；超 50 条错误截断并标记 truncated；retry_payload ≤50。"""
    store = ImportBatchStore(app.state.db)
    errors = [{"url": f"https://e.com/{i}", "reason": "bad"} for i in range(70)]
    batch_id = _run(
        store.record(
            kind="opml",
            counts={"imported": 10, "skipped": 3, "failed": 70},
            errors=errors,
            retry_payload=[{"url": f"https://e.com/{i}"} for i in range(60)],
        )
    )
    batch = _run(store.get(batch_id))
    assert batch is not None
    assert batch["counts"] == {"imported": 10, "skipped": 3, "failed": 70}
    assert batch["errors"]["truncated"] is True
    assert len(batch["errors"]["items"]) == 50
    assert len(batch["retryPayload"]) == 50


def test_f049_retry_idempotent_and_partial_success(client):
    """仅重试失败项：已存在 → skipped（幂等），新目标 → imported，部分成功。"""
    from types import SimpleNamespace

    class FakeControl:
        def __init__(self):
            self.subs = [
                SimpleNamespace(
                    stream_id="feed/1",
                    subscription_ref=encode_subscription_ref("feed/1"),
                    title="已有",
                    feed_url="https://already.example/feed",
                    category_id=None,
                    category_label=None,
                )
            ]

        async def list_subscriptions(self):
            return list(self.subs)

        async def subscribe(self, feed_url, *, category_id=None, title=None):
            if "still-bad" in feed_url:
                from lumirss.adapters.freshrss_control import FeedRejectedError

                raise FeedRejectedError("Feed was rejected by the server.")
            stream_id = f"feed/{len(self.subs) + 1}"
            self.subs.append(
                SimpleNamespace(
                    stream_id=stream_id,
                    subscription_ref=encode_subscription_ref(stream_id),
                    title=title or feed_url,
                    feed_url=feed_url,
                    category_id=None,
                    category_label=None,
                )
            )

    control = FakeControl()
    app.state.freshrss_control_adapter = control
    store = ImportBatchStore(app.state.db)
    batch_id = _run(
        store.record(
            kind="opml",
            counts={"imported": 0, "skipped": 0, "failed": 3},
            errors=[
                {"url": "https://already.example/feed", "reason": "x"},
                {"url": "https://new.example/feed", "reason": "x"},
                {"url": "https://still-bad.example/feed", "reason": "x"},
            ],
            retry_payload=[
                {"url": "https://already.example/feed", "title": "已有"},
                {"url": "https://new.example/feed", "title": "新源"},
                {"url": "https://still-bad.example/feed", "title": "坏源"},
            ],
        )
    )
    response = client.post(f"/api/v1/library/import-batches/{batch_id}/retry")
    assert response.status_code == 200
    body = response.json()
    assert body["imported"] == 1  # new.example 订阅成功
    assert body["skipped"] == 1  # already.example 已存在 → 幂等跳过
    assert body["failed"] == 1  # still-bad 由假件拒绝 → 仍失败
    assert body["errors"][0]["url"] == "https://still-bad.example/feed"

    # 再跑一次重试（对新批次）：已存在均跳过，不再新建
    second = client.post(f"/api/v1/library/import-batches/{body['batchId']}/retry")
    body2 = second.json()
    assert body2["skipped"] == 2  # already + new 都已存在
    assert body2["imported"] == 0

    # 无批次旧数据：列表接口对未知批次 404；批次列表不含未知 id
    missing = client.get("/api/v1/library/import-batches/no-such-id")
    assert missing.status_code == 404
    listed = client.get("/api/v1/library/import-batches").json()["items"]
    assert all(item["id"] in (batch_id, body["batchId"], body2["batchId"]) for item in listed)


def test_f049_no_batches_for_legacy_data(client):
    """无批次旧数据不显示：空库时批次列表为空。"""
    import tempfile

    # 用全新空库验证（不依赖其它测试写入）
    from lumirss.storage import Database

    db = Database(tempfile.mkdtemp() + "/lumi.sqlite")
    _run(db.migrate())
    fresh = ImportBatchStore(db)
    assert _run(fresh.list_batches()) == []


