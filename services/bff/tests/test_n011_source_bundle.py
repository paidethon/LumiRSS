"""N011 来源组合包 — credential-free export / preview-default import.

Proves: export sanitizes Lumi-generated feed URLs (api/mail → urn, the
per-source secret never leaves the server; unknown URLs reported
missing); import is preview-by-default with per-item
new/exists/needs_credentials + category_action; apply subscribes RSS
rows once and stores credential-needing types as DISABLED drafts; a
re-import of the same bundle is idempotent (all exists); and secrets
are never copied anywhere in the flow.
"""

import asyncio

import pytest

from lumirss.adapters.freshrss_control import Category, Subscription


def _run(coroutine):
    return asyncio.run(coroutine)


class FakeControlAdapter:
    """Minimal control fake: subscriptions / categories / subscribe / move."""

    def __init__(self) -> None:
        self.subscriptions: list[Subscription] = []
        self.categories: list[Category] = []
        self.subscribe_calls: list[str] = []
        self.move_calls: list[tuple[str, str]] = []
        self.next_id = 100

    async def list_subscriptions(self):
        return list(self.subscriptions)

    async def list_categories(self):
        return list(self.categories)

    async def subscribe(self, feed_url, *, category_id=None, title=None):
        self.subscribe_calls.append(feed_url)
        self.next_id += 1
        subscription = Subscription(
            stream_id=f"feed/{self.next_id}", title=title or feed_url, feed_url=feed_url
        )
        self.subscriptions.append(subscription)
        return subscription

    async def move_category(self, stream_id, category_id):
        self.move_calls.append((stream_id, category_id))

    async def move_to_new_category(self, stream_id, label):
        self.categories.append(Category(f"user/-/label/{label}", label))
        self.move_calls.append((stream_id, label))


def _with_fake(client, fake):
    client.app.state.freshrss_control_adapter = fake
    return client


@pytest.fixture()
def fake(client):
    adapter = FakeControlAdapter()
    client.app.state.freshrss_control_adapter = adapter
    yield adapter
    client.app.state.freshrss_control_adapter = None


def _seed_api_source(client) -> dict:
    created = client.post(
        "/api/v1/api-sources",
        json={
            "name": "GH Releases",
            "endpoint": "https://api.example.com/releases",
            "itemsExpr": "[*]",
            "fieldMap": {"id": "id", "title": "name"},
            "subscribe": False,
        },
    )
    assert created.status_code == 201
    return created.json()


def test_export_sanitizes_lumi_feed_urls(client, fake):
    source = _seed_api_source(client)
    secret = source["secret"]
    atom_url = f"https://bff.internal{source['atomPath']}"
    fake.subscriptions.append(
        Subscription(stream_id="feed/1", title="GH Releases", feed_url=atom_url)
    )
    fake.subscriptions.append(
        Subscription(stream_id="feed/2", title="博客", feed_url="https://blog.example/feed.xml")
    )
    response = client.post(
        "/api/v1/sources/bundle/export",
        json={"feedUrls": [atom_url, "https://blog.example/feed.xml"]},
    )
    assert response.status_code == 200
    assert secret not in response.text, "组合包绝不能携带任何凭据"
    body = response.json()
    assert body["version"] == 1
    assert len(body["sources"]) == 2
    api_entry = next(s for s in body["sources"] if s["type"] == "api")
    assert api_entry["feed_url"] == f"urn:lumirss:api-source:{source['uuid']}"
    rss_entry = next(s for s in body["sources"] if s["type"] == "rss")
    assert rss_entry["feed_url"] == "https://blog.example/feed.xml"


def test_export_reports_missing_urls(client, fake):
    response = client.post(
        "/api/v1/sources/bundle/export",
        json={"feedUrls": ["https://not-subscribed.example/rss"]},
    )
    assert response.status_code == 200
    assert response.json()["missing"] == ["https://not-subscribed.example/rss"]
    assert response.json()["sources"] == []


def test_import_preview_default_is_read_only(client, fake):
    fake.subscriptions.append(
        Subscription(stream_id="feed/7", title="已有", feed_url="https://existing.example/rss")
    )
    bundle = {
        "version": 1,
        "sources": [
            {"feed_url": "https://existing.example/rss", "title": "已有", "type": "rss"},
            {
                "feed_url": "https://new.example/rss",
                "title": "新源",
                "category": " tech ",
                "type": "rss",
            },
            {"feed_url": "urn:lumirss:api-source:abc", "title": "草稿", "type": "api"},
        ],
    }
    response = client.post("/api/v1/sources/bundle/import", json=bundle)
    assert response.status_code == 200
    body = response.json()
    assert body["applied"] is False
    assert fake.subscribe_calls == [], "预览默认零写入"
    items = {item["feedUrl"]: item for item in body["items"]}
    assert items["https://existing.example/rss"]["status"] == "exists"
    assert items["https://new.example/rss"]["status"] == "new"
    assert items["https://new.example/rss"]["categoryAction"] == "create"
    assert items["urn:lumirss:api-source:abc"]["status"] == "needs_credentials"
    assert items["urn:lumirss:api-source:abc"]["type"] == "api"
    assert body["counts"] == {"new": 1, "exists": 1, "needs_credentials": 1, "invalid": 0, "failed": 0}


def test_import_apply_subscribes_and_creates_disabled_drafts(client, fake):
    bundle = {
        "version": 1,
        "sources": [
            {
                "feed_url": "https://new.example/rss",
                "title": "新源",
                "category": "Tech",
                "type": "rss",
            },
            {"feed_url": "urn:lumirss:mail:xyz", "title": "邮件桥", "type": "mail"},
        ],
    }
    applied = client.post("/api/v1/sources/bundle/import?apply=true", json=bundle)
    assert applied.status_code == 200
    body = applied.json()
    assert body["applied"] is True
    assert fake.subscribe_calls == ["https://new.example/rss"], "RSS 新源被订阅一次"
    assert body["counts"]["new"] == 1
    assert body["counts"]["needs_credentials"] == 1
    # 凭据型来源 → 停用草稿（enabled=0，origin=bundle_draft），绝不复制凭据
    staged = client.get("/api/v1/sources/staging").json()["items"]
    drafts = [row for row in staged if row["origin"] == "bundle_draft"]
    assert len(drafts) == 1
    assert drafts[0]["url"] == "urn:lumirss:mail:xyz"
    assert drafts[0]["enabled"] is False
    assert drafts[0]["sourceType"] == "mail"
    # 草稿不能直接订阅
    blocked = client.post(f"/api/v1/sources/staging/{drafts[0]['id']}/subscribe")
    assert blocked.status_code == 409


def test_reimport_is_idempotent_all_exists(client, fake):
    bundle = {
        "version": 1,
        "sources": [
            {"feed_url": "https://new.example/rss", "title": "新源", "type": "rss"},
            {"feed_url": "urn:lumirss:api-source:abc", "title": "草稿", "type": "api"},
        ],
    }
    first = client.post("/api/v1/sources/bundle/import?apply=true", json=bundle)
    assert first.status_code == 200
    subscribe_calls_after_first = list(fake.subscribe_calls)
    second = client.post("/api/v1/sources/bundle/import?apply=true", json=bundle)
    assert second.status_code == 200
    body = second.json()
    assert body["counts"]["exists"] == 2, "幂等重导入：全部 exists"
    assert fake.subscribe_calls == subscribe_calls_after_first, "不重复订阅"
    drafts = [
        row
        for row in client.get("/api/v1/sources/staging").json()["items"]
        if row["origin"] == "bundle_draft"
    ]
    assert len(drafts) == 1, "不重复建草稿"


def test_import_rejects_malformed_bundle(client, fake):
    response = client.post(
        "/api/v1/sources/bundle/import",
        json={"version": 2, "sources": []},
    )
    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_bundle"
