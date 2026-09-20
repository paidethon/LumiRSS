"""F044 RSS 地址迁移向导 — 校验/执行/元数据随迁/负向（不产生部分变更）。

FreshRSS greader 无"原位改 URL"端点：迁移 = 新建订阅 + Lumi 元数据
随迁 + replaced_by 标记（旧订阅保留）。全部上游交互走假件。
"""

import asyncio
from types import SimpleNamespace

from lumirss.main import app
from lumirss.source_notes import SourceNotesStore
from lumirss.subscriptionref import encode_subscription_ref


def _run(coroutine):
    return asyncio.run(coroutine)


OLD_URL = "https://old.example.com/feed.xml"
NEW_URL = "https://new.example.com/rss.xml"
OLD_REF = encode_subscription_ref("feed/1")


class FakeControl:
    def __init__(self, subs):
        self.subs = list(subs)
        self.subscribe_calls: list[str] = []
        self.unsubscribe_calls: list[str] = []

    async def list_subscriptions(self):
        return list(self.subs)

    async def subscribe(self, feed_url, *, category_id=None, title=None):
        if any(sub.feed_url == feed_url for sub in self.subs):
            from lumirss.adapters.freshrss_control import SubscriptionConflict

            raise SubscriptionConflict("Already subscribed to this feed URL.")
        stream_id = f"feed/{len(self.subs) + 1}"
        sub = SimpleNamespace(
            stream_id=stream_id,
            subscription_ref=encode_subscription_ref(stream_id),
            title=title or "新源",
            feed_url=feed_url,
            category_id=None,
            category_label=None,
        )
        self.subs.append(sub)
        self.subscribe_calls.append(feed_url)
        return sub

    async def unsubscribe(self, stream_id):
        self.unsubscribe_calls.append(stream_id)


class FakePreviewService:
    def __init__(self, ok_urls: set[str]):
        self.ok_urls = ok_urls

    async def preview(self, feed_url):
        if feed_url not in self.ok_urls:
            raise RuntimeError("unreachable or not a feed")
        return SimpleNamespace(
            title="新源标题",
            feed_url=feed_url,
            site_url=None,
            description=None,
            format="rss",
            already_subscribed=False,
        )


def _install(control, preview_ok):
    app.state.freshrss_control_adapter = control
    app.state.feed_preview_service = FakePreviewService(preview_ok)


def _setup_notes(db_client):
    _run(
        SourceNotesStore(app.state.db).update_notes(
            OLD_REF, note="迁移前备注", reason="订阅理由", maintenance_log=None
        )
    )
    _ = db_client


def test_f044_migrate_happy_path_copies_and_marks(client):
    """成功迁移：新订阅建立、备注/覆盖随迁（旧备注保留）、replaced_by 标记、旧源未动。"""
    control = FakeControl(
        [
            SimpleNamespace(
                stream_id="feed/1",
                subscription_ref=OLD_REF,
                title="旧源",
                feed_url=OLD_URL,
                category_id=None,
                category_label=None,
            )
        ]
    )
    _install(control, {NEW_URL})
    _setup_notes(client)
    _run(
        __import__("lumirss.source_overrides", fromlist=["SourceOverrideStore"])
        .SourceOverrideStore(app.state.db)
        .set_fields(OLD_URL, hidden_until="2026-10-01T00:00:00Z")
    )

    response = client.post(
        f"/api/v1/subscriptions/{OLD_REF}/migrate",
        json={"newUrl": NEW_URL},
    )
    assert response.status_code == 200
    body = response.json()
    new_ref = body["newSubscriptionRef"]
    assert body["newFeedUrl"] == NEW_URL
    assert body["copiedNotes"] is True
    assert body["copiedOverrides"] is True
    assert control.subscribe_calls == [NEW_URL]
    assert control.unsubscribe_calls == []  # 旧源未动（FreshRSS 侧负向）

    # 新旧备注均存在
    old_notes = _run(SourceNotesStore(app.state.db).get_notes(OLD_REF))
    new_notes = _run(SourceNotesStore(app.state.db).get_notes(new_ref))
    assert old_notes["note"] == "迁移前备注"
    assert new_notes["note"] == "迁移前备注"

    # replaced_by 标记入库
    row = _run(
        app.state.db.fetch_one(
            "SELECT old_feed_url, new_feed_url, old_subscription_ref, new_subscription_ref FROM source_migrations WHERE old_feed_url = ?",
            (OLD_URL,),
        )
    )
    assert row is not None
    assert row["new_feed_url"] == NEW_URL
    assert row["old_subscription_ref"] == OLD_REF

    # 覆盖随迁到新 feed_url
    override = _run(
        __import__("lumirss.source_overrides", fromlist=["SourceOverrideStore"])
        .SourceOverrideStore(app.state.db)
        .get_override(NEW_URL)
    )
    assert override is not None and override["hiddenUntil"] == "2026-10-01T00:00:00Z"


def test_f044_same_url_409_and_invalid_url_422_no_changes(client):
    """同 URL 409；新 URL 校验失败 422 —— 两者均不产生任何变更。"""
    control = FakeControl(
        [
            SimpleNamespace(
                stream_id="feed/1",
                subscription_ref=OLD_REF,
                title="旧源",
                feed_url=OLD_URL,
                category_id=None,
                category_label=None,
            )
        ]
    )
    _install(control, {NEW_URL})
    _run(app.state.db.migrate())

    same = client.post(f"/api/v1/subscriptions/{OLD_REF}/migrate", json={"newUrl": OLD_URL})
    assert same.status_code == 409
    assert same.json()["error"]["type"] == "migration_same_url"

    bad = client.post(f"/api/v1/subscriptions/{OLD_REF}/migrate", json={"newUrl": "https://broken.example/f"})
    assert bad.status_code == 422
    assert bad.json()["error"]["type"] == "migration_invalid_url"

    # 负向：零变更
    assert control.subscribe_calls == []
    assert len(control.subs) == 1
    rows = _run(
        app.state.db.fetch_all("SELECT * FROM source_migrations")
    )
    assert rows == []


def test_f044_migrate_to_already_subscribed_url_conflicts(client):
    """迁移到另一个已订阅地址 → 409（FreshRSS 冲突如实透出）。"""
    other_url = "https://another.example/feed"
    control = FakeControl(
        [
            SimpleNamespace(
                stream_id="feed/1",
                subscription_ref=OLD_REF,
                title="旧源",
                feed_url=OLD_URL,
                category_id=None,
                category_label=None,
            ),
            SimpleNamespace(
                stream_id="feed/2",
                subscription_ref=encode_subscription_ref("feed/2"),
                title="别家",
                feed_url=other_url,
                category_id=None,
                category_label=None,
            ),
        ]
    )
    _install(control, {other_url})
    response = client.post(f"/api/v1/subscriptions/{OLD_REF}/migrate", json={"newUrl": other_url})
    assert response.status_code == 409
    assert response.json()["error"]["type"] == "migration_subscribe_failed"
    assert control.unsubscribe_calls == []
