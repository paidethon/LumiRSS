"""API Sources v1 tests (phase2 M3).

Hermetic: the endpoint fetch is exercised through a stubbed fetch
(this dev environment resolves public names to non-public fake-IP
addresses — a real-world fail-closed case covered separately). Proves:
CRUD, expression validation errors, stable Atom ids, correct XML
escaping, ETag/304, status marking (ok / fetch_failed), secret auth,
and the fail-closed SSRF refusal of private endpoints.
"""

import pytest
from defusedxml import ElementTree as SafeET

from lumirss.api_source_store import ApiSourceStore
from lumirss.api_sources import (
    ApiSourceExpressionError,
    ApiSourceInvalid,
    map_items,
    validate_field_map,
    validate_items_expr,
)

JSON_BODY = [
    {"id": 7, "name": "v1.0 <稳定版>", "html_url": "https://example.com/r/7", "published_at": "2026-09-01T00:00:00Z", "body": "<script>alert(1)</script><p>发布说明 &amp; 更多</p>"},
    {"id": 6, "name": "v0.9", "html_url": "https://example.com/r/6", "published_at": "2026-08-01T00:00:00Z", "body": "旧版本"},
]


def _run(coroutine):
    import asyncio

    return asyncio.run(coroutine)


@pytest.fixture()
def source_db(tmp_path):
    from lumirss.storage import Database

    db = Database(tmp_path / "lumi.sqlite")
    _run(db.migrate())
    return db


def test_expression_validation(source_db):
    with pytest.raises(ApiSourceInvalid):
        validate_items_expr("")
    with pytest.raises(ApiSourceExpressionError):
        validate_items_expr("this is ][ not valid")
    with pytest.raises(ApiSourceInvalid):
        validate_field_map({"unknown_key": "a"})
    with pytest.raises(ApiSourceInvalid):
        validate_field_map({"title": "name"})  # id missing
    assert validate_items_expr("[*].name") == "[*].name"


def test_map_items_caps_and_truncation(source_db):
    field_map = '{"id": "id", "title": "name", "body": "body"}'
    items = map_items(JSON_BODY, "[*]", field_map)
    assert len(items) == 2
    assert items[0]["title"] == "v1.0 <稳定版>"
    long_item = {"id": 1, "name": "x" * 9000}
    items = map_items([long_item], "[*]", '{"id": "id", "title": "name"}')
    assert len(items[0]["title"]) == 8000


def test_store_roundtrip_and_update_invalidates(source_db):
    store = ApiSourceStore(source_db)
    record = _run(
        store.create(
            name="Releases",
            endpoint="https://api.example.com/releases",
            items_expr="[*]",
            field_map={"id": "id", "title": "name"},
        )
    )
    assert record.enabled is True
    _run(store.mark_success(record.uuid, '"etag-1"', "<feed/>", "2026-09-01T00:00:00+00:00"))
    updated = _run(
        store.update(record.uuid, name="改名", items_expr="reverse([*])")
    )
    assert updated is not None
    assert updated.name == "改名"
    assert updated.etag is None  # config change invalidates cache identity
    assert updated.atom_body is None  # last-known-good reset with it
    assert updated.feed_updated is None
    assert updated.last_status is None


def test_atom_endpoint_flow(client, monkeypatch):
    """Full FreshRSS-facing flow with a stubbed upstream + no real DNS."""
    import lumirss.routers.api_sources as routes

    async def no_network(url: str) -> None:
        return None

    monkeypatch.setattr(routes, "fetch_json", _fake_fetch_json)

    created = client.post(
        "/api/v1/api-sources",
        json={
            "name": "GitHub releases",
            "endpoint": "https://api.example.com/repos/x/y/releases",
            "itemsExpr": "[*]",
            "fieldMap": {
                "id": "id",
                "title": "name",
                "url": "html_url",
                "published": "published_at",
                "body": "body",
            },
            "subscribe": False,
        },
    )
    assert created.status_code == 201
    body = created.json()
    assert body["secret"] and body["atomPath"].startswith("/feeds/")

    atom = client.get(body["atomPath"])
    assert atom.status_code == 200
    assert "atom+xml" in atom.headers["content-type"]
    root = SafeET.fromstring(atom.text)
    ns = "{http://www.w3.org/2005/Atom}"
    entries = root.findall(f"{ns}entry")
    assert len(entries) == 2
    # Stable ids + correct escaping (title contains angle brackets).
    first_id = entries[0].find(f"{ns}id").text
    assert first_id.startswith("urn:lumirss:apisource:")
    title = entries[0].find(f"{ns}title").text
    assert title == "v1.0 <稳定版>"
    # Body delivered as escaped HTML content (script tag survives as text;
    # RSS-domain sanitization happens at the FreshRSS render side).
    content = entries[0].find(f"{ns}content").text
    assert "<script>" in content  # escaped, not executable markup

    # ETag / 304
    etag = atom.headers["etag"]
    cached = client.get(body["atomPath"], headers={"if-none-match": etag})
    assert cached.status_code == 304

    # Status marked ok with last_success_at.
    listing = client.get("/api/v1/api-sources").json()["items"]
    assert listing[0]["lastStatus"] == "ok"
    assert listing[0]["lastSuccessAt"] is not None

    # Wrong secret is a hard 404 (never leaks whether the uuid exists).
    wrong = client.get(body["atomPath"].replace(body["secret"], "0" * 32))
    assert wrong.status_code == 404

    # Disabled → feed 404s.
    client.patch(f"/api/v1/api-sources/{body['uuid']}", json={"enabled": False})
    assert client.get(body["atomPath"]).status_code == 404

    # Delete removes config.
    assert client.delete(f"/api/v1/api-sources/{body['uuid']}").status_code == 204


async def _fake_fetch_json(client_arg, endpoint: str):
    _ = client_arg
    if "api.example.com" in endpoint:
        return JSON_BODY
    raise Exception("unexpected endpoint")


def test_atom_endpoint_marks_fetch_failed(client, monkeypatch):
    import lumirss.routers.api_sources as routes

    async def failing_fetch(client_arg, endpoint: str):
        from lumirss.api_sources import ApiSourceFetchFailed

        raise ApiSourceFetchFailed("API 端点连接失败。")

    monkeypatch.setattr(routes, "fetch_json", failing_fetch)
    created = client.post(
        "/api/v1/api-sources",
        json={
            "name": "Downstream",
            "endpoint": "https://api.example.com/x",
            "itemsExpr": "[*]",
            "fieldMap": {"id": "id", "title": "name"},
            "subscribe": False,
        },
    )
    atom_path_value = created.json()["atomPath"]
    response = client.get(atom_path_value)
    assert response.status_code == 502
    listing = client.get("/api/v1/api-sources").json()["items"]
    assert listing[0]["lastStatus"] == "fetch_failed"
    assert "连接失败" in listing[0]["lastError"]


def test_ssrf_fail_closed_on_private_endpoint(client, monkeypatch):
    """Private/loopback endpoints are refused with the honest error, even
    though the structural https check passed."""
    import lumirss.api_sources as api_sources_mod
    from lumirss.clip_fetch import ClipForbidden

    created = client.post(
        "/api/v1/api-sources",
        json={
            "name": "Internal",
            "endpoint": "https://internal.example.com/api",
            "itemsExpr": "[*]",
            "fieldMap": {"id": "id", "title": "name"},
            "subscribe": False,
        },
    )
    assert created.status_code == 201
    body = created.json()

    async def refuses(url: str) -> None:
        raise ClipForbidden("页面地址解析到非公网地址，已拒绝。", "unsafe_address")

    monkeypatch.setattr(api_sources_mod, "validate_hop", refuses)
    response = client.get(body["atomPath"])
    # SSRF refusal is a 4xx (the configured target is unsafe), not a 5xx
    # upstream failure — fail closed with the honest error type.
    assert response.status_code == 400
    assert response.json()["error"]["type"] == "clip_fetch_forbidden"

    # Creation-time https enforcement.
    insecure = client.post(
        "/api/v1/api-sources",
        json={
            "name": "Insecure",
            "endpoint": "http://api.example.com/x",
            "itemsExpr": "[*]",
            "fieldMap": {"id": "id", "title": "name"},
        },
    )
    assert insecure.status_code == 400


# -- Recovery P0-05 ----------------------------------------------------------


def _create_source(client, monkeypatch, name="GitHub releases", data=None):
    import lumirss.routers.api_sources as routes

    monkeypatch.setattr(routes, "fetch_json", _make_fake_fetch(data or JSON_BODY))
    created = client.post(
        "/api/v1/api-sources",
        json={
            "name": name,
            "endpoint": "https://api.example.com/repos/x/y/releases",
            "itemsExpr": "[*]",
            "fieldMap": {
                "id": "id",
                "title": "name",
                "url": "html_url",
                "published": "published_at",
                "body": "body",
            },
            "subscribe": False,
        },
    )
    assert created.status_code == 201
    return created.json()


def _make_fake_fetch(data):
    async def fake_fetch(client_arg, endpoint: str):
        _ = client_arg
        if "api.example.com" in endpoint:
            return data
        raise Exception("unexpected endpoint")

    return fake_fetch


def test_atom_rfc4287_structure_and_absolute_self(client, monkeypatch):
    """RFC 4287: feed id/title/updated/link-rel=self (absolute)/author;
    entries id/title/link/published/updated/author/content."""

    monkeypatch.setenv("LUMIRSS_ATOM_BASE_URL", "http://bff:8000")
    body = _create_source(client, monkeypatch, name="结构 <验证>")
    atom = client.get(body["atomPath"])
    assert atom.status_code == 200
    root = SafeET.fromstring(atom.text)
    ns = "{http://www.w3.org/2005/Atom}"
    assert root.tag == f"{ns}feed"
    assert root.find(f"{ns}title").text == "结构 <验证>"
    assert root.find(f"{ns}id").text.startswith("urn:lumirss:apisource:")
    updated = root.find(f"{ns}updated").text
    assert updated and updated.startswith("2026-09-01")  # newest entry ts
    self_link = [
        link
        for link in root.findall(f"{ns}link")
        if link.get("rel") == "self"
    ]
    assert self_link and self_link[0].get("href").startswith("http://bff:8000/feeds/")
    feed_author = root.find(f"{ns}author/{ns}name")
    assert feed_author is not None and feed_author.text == "结构 <验证>"
    entries = root.findall(f"{ns}entry")
    assert len(entries) == 2
    for entry in entries:
        assert entry.find(f"{ns}id") is not None
        assert entry.find(f"{ns}title") is not None
        assert entry.find(f"{ns}updated") is not None  # REQUIRED, non-empty
        assert entry.find(f"{ns}updated").text
        assert entry.find(f"{ns}content") is not None
        # Author requirement satisfied by the feed-level author
        # (RFC 4287 §4.2.1: entries without their own author inherit it).
    # Entry-level published normalized; newest entry drives feed updated.
    assert entries[0].find(f"{ns}published").text == "2026-09-01T00:00:00+00:00"


def test_atom_etag_stable_across_time_and_content_sensitive(client, monkeypatch):
    """ETag is content-derived: byte-identical across GETs (even with the
    wall clock moved), changes only when content changes; 304 reliable."""
    import lumirss.api_sources as api_mod
    import lumirss.routers.api_sources as routes

    body = _create_source(client, monkeypatch)
    first = client.get(body["atomPath"])
    etag = first.headers["etag"]

    # Move the clock far forward: same content MUST render the same feed.
    monkeypatch.setattr(api_mod, "utc_now", lambda: "2030-01-01T00:00:00+00:00")
    second = client.get(body["atomPath"])
    assert second.status_code == 200
    assert second.headers["etag"] == etag
    assert second.text == first.text
    cached = client.get(body["atomPath"], headers={"if-none-match": etag})
    assert cached.status_code == 304

    # Content change → new updated + new ETag.
    changed = [
        {"id": 8, "name": "v2.0", "html_url": "https://example.com/r/8",
         "published_at": "2026-09-10T12:00:00Z", "body": "新版本"},
    ]
    monkeypatch.setattr(routes, "fetch_json", _make_fake_fetch(changed))
    third = client.get(body["atomPath"])
    assert third.status_code == 200
    assert third.headers["etag"] != etag
    root = SafeET.fromstring(third.text)
    ns = "{http://www.w3.org/2005/Atom}"
    assert root.find(f"{ns}updated").text == "2026-09-10T12:00:00+00:00"
    # Old etag no longer matches.
    stale_304 = client.get(body["atomPath"], headers={"if-none-match": etag})
    assert stale_304.status_code == 200


def test_stale_last_known_good_on_upstream_failure(client, monkeypatch):
    """Upstream failure serves the persisted last-good body with
    X-Lumi-Stale: 1 (and honors its ETag); 502 only without last-good."""
    import lumirss.routers.api_sources as routes

    body = _create_source(client, monkeypatch)
    good = client.get(body["atomPath"])
    assert good.status_code == 200
    etag = good.headers["etag"]

    async def failing_fetch(client_arg, endpoint: str):
        from lumirss.api_sources import ApiSourceFetchFailed

        raise ApiSourceFetchFailed("API 端点连接失败。")

    monkeypatch.setattr(routes, "fetch_json", failing_fetch)
    stale = client.get(body["atomPath"])
    assert stale.status_code == 200
    assert stale.headers.get("x-lumi-stale") == "1"
    assert stale.text == good.text
    assert stale.headers["etag"] == etag
    # Stale body still honors conditional GET.
    cached = client.get(body["atomPath"], headers={"if-none-match": etag})
    assert cached.status_code == 304
    listing = client.get("/api/v1/api-sources").json()["items"]
    assert listing[0]["lastStatus"] == "fetch_failed"

    # A source whose FIRST fetch fails has no last-good → honest 502.
    fresh = _create_source(client, monkeypatch, name="Never worked")
    monkeypatch.setattr(routes, "fetch_json", failing_fetch)
    assert client.get(fresh["atomPath"]).status_code == 502


class _FakeSubscription:
    def __init__(self, stream_id: str, feed_url: str):
        self.stream_id = stream_id
        self.feed_url = feed_url


class _FakeControlAdapter:
    """Scriptable control adapter: records unsubscribe calls and can
    fail them (simulating FreshRSS downtime)."""

    def __init__(self, feed_url: str, fail: bool):
        self.feed_url = feed_url
        self.fail = fail
        self.unsubscribed: list[str] = []

    async def list_subscriptions(self):
        if self.fail:
            raise RuntimeError("FreshRSS unreachable")
        return [_FakeSubscription("stream/1", self.feed_url)]

    async def unsubscribe(self, stream_id: str):
        if self.fail:
            raise RuntimeError("FreshRSS unreachable")
        self.unsubscribed.append(stream_id)


def test_delete_blocked_on_unsubscribe_failure(client, monkeypatch):
    """Unsubscribe is part of delete: failure → 409 unsubscribe_failed,
    source kept (retryable); success → delete proceeds."""
    import lumirss.routers.api_sources as routes

    body = _create_source(client, monkeypatch, name="阻塞删除")
    adapter = _FakeControlAdapter(
        "http://bff:8000" + body["atomPath"], fail=True
    )
    monkeypatch.setattr(routes, "_get_control_adapter", lambda request: adapter)

    blocked = client.delete(f"/api/v1/api-sources/{body['uuid']}")
    assert blocked.status_code == 409
    assert blocked.json()["error"]["type"] == "unsubscribe_failed"
    listing = client.get("/api/v1/api-sources").json()["items"]
    assert [item["uuid"] for item in listing] == [body["uuid"]]

    # FreshRSS recovers → the retry deletes for real.
    adapter.fail = False
    ok = client.delete(f"/api/v1/api-sources/{body['uuid']}")
    assert ok.status_code == 204
    assert adapter.unsubscribed == ["stream/1"]
    listing = client.get("/api/v1/api-sources").json()["items"]
    assert listing == []


def test_delete_idempotent_when_feed_absent_or_freshrss_unconfigured(
    client, monkeypatch
):
    """Already-absent feeds delete cleanly (retry converges), and an
    unconfigured FreshRSS cannot hold a subscription — delete passes."""
    import lumirss.routers.api_sources as routes

    class _ExplodingAdapter:
        async def list_subscriptions(self):
            raise RuntimeError("no adapter")

    # Absent subscription → delete proceeds without any unsubscribe call.
    absent = _FakeControlAdapter("http://bff:8000/feeds/other.atom", fail=False)
    monkeypatch.setattr(
        routes, "_get_control_adapter", lambda request: absent
    )
    body = _create_source(client, monkeypatch, name="已缺席")
    assert client.delete(f"/api/v1/api-sources/{body['uuid']}").status_code == 204

    # Unconfigured FreshRSS (adapter construction fails) → delete passes.
    def raise_config(request):
        from lumirss.adapters.freshrss import ConfigError

        raise ConfigError("FreshRSS not configured")

    monkeypatch.setattr(routes, "_get_control_adapter", raise_config)
    other = _create_source(client, monkeypatch, name="未配置")
    assert client.delete(f"/api/v1/api-sources/{other['uuid']}").status_code == 204


def test_streaming_fetch_caps_oversized_response(monkeypatch):
    """fetch_json refuses bodies beyond 2MB while STREAMING (the old
    code buffered the whole response first — an OOM DoS)."""
    import asyncio

    import httpx

    from lumirss.api_sources import ApiSourceFetchFailed, fetch_json

    async def no_network(url: str) -> None:
        return None

    monkeypatch.setattr("lumirss.api_sources.validate_hop", no_network)
    oversized = b'{"data": "' + b"x" * (2 * 1024 * 1024 + 1024) + b'"}'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=oversized,
        )

    client_http = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), trust_env=False
    )
    monkeypatch.setattr(
        "lumirss.api_sources._pinned_client", lambda: client_http
    )

    async def scenario():
        with pytest.raises(ApiSourceFetchFailed, match="2MB"):
            await fetch_json(client_http, "https://api.example.com/big")

    asyncio.run(scenario())
