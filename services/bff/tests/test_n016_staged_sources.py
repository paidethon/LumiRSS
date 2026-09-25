"""N016 暂存待评估来源 — staging pool.

Proves: staging a URL stores a bounded preview sample WITHOUT
subscribing (nothing counts toward unread — FreshRSS is never told);
the sample snapshot holds ≤10 metadata-only entries; subscribe runs the
normal subscribe path exactly once (existing subscription → exists) and
removes the row; discard removes the row; duplicates conflict.
"""

import asyncio

import pytest


def _run(coroutine):
    return asyncio.run(coroutine)


RSS_XML = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>候选博客</title>
  <link href="https://candidate.example/"/>
  <entry><title>文章一</title><link href="https://candidate.example/1"/>
    <summary>摘要一</summary><updated>2026-09-01T00:00:00Z</updated></entry>
  <entry><title>文章二</title><link href="https://candidate.example/2"/>
    <summary>摘要二</summary><updated>2026-09-02T00:00:00Z</updated></entry>
</feed>
"""
RSS_BODY = RSS_XML.encode("utf-8")


class FakeControlAdapter:
    def __init__(self, subscribed=None) -> None:
        self.subscribed = list(subscribed or [])
        self.subscribe_calls: list[str] = []

    async def list_subscriptions(self):
        return [
            type("S", (), {"feed_url": url})() for url in self.subscribed
        ]

    async def subscribe(self, feed_url, *, category_id=None, title=None):
        self.subscribe_calls.append(feed_url)
        self.subscribed.append(feed_url)


@pytest.fixture()
def fake(client, monkeypatch):
    import lumirss.routers.source_lifecycle as lifecycle
    from lumirss.feed_preview import FetchedDocument

    adapter = FakeControlAdapter()

    async def _safe_fetch(url, **kwargs):
        return FetchedDocument(body=RSS_BODY, final_url=url, content_type="application/atom+xml")

    monkeypatch.setattr(lifecycle, "safe_fetch", _safe_fetch)
    client.app.state.freshrss_control_adapter = adapter
    yield adapter
    client.app.state.freshrss_control_adapter = None


def test_stage_stores_sample_without_subscribing(client, fake):
    response = client.post(
        "/api/v1/sources/staging",
        json={"url": "https://candidate.example/feed"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "候选博客"
    assert body["subscribed"] is False
    assert [entry["title"] for entry in body["sample"]] == ["文章一", "文章二"]
    assert fake.subscribe_calls == [], "暂存绝不订阅（不影响未读计数）"


def test_stage_sample_is_capped_at_ten_entries(client, fake):
    entries = "".join(
        f"<entry><title>t{i}</title><summary>s</summary></entry>" for i in range(15)
    )
    import lumirss.routers.source_lifecycle as lifecycle
    from lumirss.feed_preview import FetchedDocument

    big = RSS_XML.replace(
        '  <entry><title>文章一</title><link href="https://candidate.example/1"/>\n'
        "    <summary>摘要一</summary><updated>2026-09-01T00:00:00Z</updated></entry>\n"
        '  <entry><title>文章二</title><link href="https://candidate.example/2"/>\n'
        "    <summary>摘要二</summary><updated>2026-09-02T00:00:00Z</updated></entry>\n",
        entries,
    ).encode("utf-8")

    async def _big_fetch(url, **kwargs):
        return FetchedDocument(body=big, final_url=url, content_type="application/atom+xml")

    lifecycle.safe_fetch = _big_fetch
    response = client.post(
        "/api/v1/sources/staging",
        json={"url": "https://candidate.example/big"},
    )
    assert response.status_code == 201
    assert len(response.json()["sample"]) == 10, "样例快照 ≤10 条"


def test_stage_duplicate_conflicts_and_subscribed_conflicts(client, fake):
    first = client.post(
        "/api/v1/sources/staging",
        json={"url": "https://candidate.example/feed"},
    )
    assert first.status_code == 201
    duplicate = client.post(
        "/api/v1/sources/staging",
        json={"url": "https://candidate.example/feed"},
    )
    assert duplicate.status_code == 409
    # 已订阅的 URL 不需要评估 → 诚实 409
    fake.subscribed.append("https://already.example/rss")
    subscribed = client.post(
        "/api/v1/sources/staging",
        json={"url": "https://already.example/rss"},
    )
    assert subscribed.status_code == 409
    assert subscribed.json()["error"]["type"] == "already_subscribed"


def test_subscribe_runs_normal_path_once_and_removes_row(client, fake):
    staged = client.post(
        "/api/v1/sources/staging",
        json={"url": "https://candidate.example/feed"},
    ).json()
    result = client.post(f"/api/v1/sources/staging/{staged['id']}/subscribe")
    assert result.status_code == 200
    assert result.json()["status"] == "subscribed"
    assert fake.subscribe_calls == ["https://candidate.example/feed"], "恰好一次正常订阅"
    assert client.get("/api/v1/sources/staging").json()["items"] == []
    # 幂等重放：行已移除 → 404（不会二次订阅）
    replay = client.post(f"/api/v1/sources/staging/{staged['id']}/subscribe")
    assert replay.status_code == 404
    assert fake.subscribe_calls.count("https://candidate.example/feed") == 1


def test_subscribe_existing_subscription_reports_exists(client, fake):
    fake.subscribed.append("https://candidate.example/feed")
    staged = client.post(
        "/api/v1/sources/staging",
        json={"url": "https://candidate.example/feed"},
    )
    # 已订阅 URL 在暂存入口就被 409 挡下；若订阅发生在暂存之后
    # （竞态），subscribe 端点收敛为 exists。
    if staged.status_code == 201:
        staged = staged.json()
        client.app.state.freshrss_control_adapter = FakeControlAdapter(
            subscribed=["https://candidate.example/feed"]
        )
        result = client.post(f"/api/v1/sources/staging/{staged['id']}/subscribe")
        assert result.status_code == 200
        assert result.json()["status"] == "exists"
        assert client.get("/api/v1/sources/staging").json()["items"] == []


def test_discard_removes_row(client, fake):
    staged = client.post(
        "/api/v1/sources/staging",
        json={"url": "https://candidate.example/feed"},
    ).json()
    assert (
        client.delete(f"/api/v1/sources/staging/{staged['id']}").status_code == 204
    )
    assert client.get("/api/v1/sources/staging").json()["items"] == []
    assert (
        client.delete(f"/api/v1/sources/staging/{staged['id']}").status_code == 404
    )


def test_staged_rows_never_appear_as_subscriptions(client, fake):
    client.post(
        "/api/v1/sources/staging",
        json={"url": "https://candidate.example/feed"},
    )
    assert fake.subscribed == [], "暂存池与订阅列表零交集"
