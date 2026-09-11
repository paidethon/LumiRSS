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
    _run(store.mark_success(record.uuid, '"etag-1"'))
    updated = _run(
        store.update(record.uuid, name="改名", items_expr="reverse([*])")
    )
    assert updated is not None
    assert updated.name == "改名"
    assert updated.etag is None  # config change invalidates cache identity
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
