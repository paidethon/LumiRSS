"""Inbox push source regressions (0021).

Covers: connector lifecycle (secret shown once, never echoed), bearer
ingest auth (constant-time, no existence leak), payload validation
bounds, idempotency on (source, guid), the server-side sanitize boundary
for untrusted HTML, the search projection, kind-aware ItemRef resolution
(api_item), and the v20→v21 migration upgrade rehearsal.
"""

import asyncio
import shutil
import sqlite3

import pytest

from lumirss.migrations import list_migrations, schema_version
from lumirss.storage import Database, DatabaseError


@pytest.fixture()
def db(client):
    return client.app.state.db


def run(coroutine):
    return asyncio.run(coroutine)


def _create_source(client, name="scripts"):
    resp = client.post("/api/v1/inbox/sources", json={"name": name})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _ingest(client, source, guid="g1", **overrides):
    payload = {
        "guid": guid,
        "title": "Pushed item",
        "url": "https://example.com/a",
        "content": "hello world",
        "publishedAt": "2026-09-13T10:00:00+00:00",
        "categories": ["research", "ai"],
        **overrides,
    }
    return client.post(
        f"/api/v1/inbox/ingest/{source['uuid']}",
        json=payload,
        headers={"Authorization": f"Bearer {source['secret']}"},
    )


# ---------------------------------------------------------------------------
# Connector lifecycle
# ---------------------------------------------------------------------------


def test_create_source_returns_secret_exactly_once(client):
    created = _create_source(client)
    assert created["secret"]
    assert created["ingestPath"] == f"/api/v1/inbox/ingest/{created['uuid']}"

    listed = client.get("/api/v1/inbox/sources").json()
    assert len(listed) == 1
    assert "secret" not in listed[0]
    assert listed[0]["name"] == "scripts"


def test_create_source_rejects_blank_and_oversized_names(client):
    assert client.post("/api/v1/inbox/sources", json={"name": "  "}).status_code == 422
    assert (
        client.post("/api/v1/inbox/sources", json={"name": "x" * 121}).status_code
        == 422
    )


def test_delete_unknown_source_is_stable_404(client):
    resp = client.delete("/api/v1/inbox/sources/does-not-exist")
    assert resp.status_code == 404
    assert resp.json()["error"]["type"] == "inbox_source_not_found"


def test_registry_lists_inbox_connector(client):
    _create_source(client, name="my-bot")
    rows = client.get("/api/v1/sources").json()["sources"]
    inbox_rows = [r for r in rows if r["type"] == "inbox"]
    assert len(inbox_rows) == 1
    assert inbox_rows[0]["label"] == "my-bot"
    # the registry is read-only synthesis: no secrets, ever
    assert all("secret" not in r for r in rows)


# ---------------------------------------------------------------------------
# Ingest auth + validation
# ---------------------------------------------------------------------------


def test_ingest_without_or_with_wrong_bearer_is_404(client):
    source = _create_source(client)
    no_auth = client.post(
        f"/api/v1/inbox/ingest/{source['uuid']}",
        json={"guid": "g1", "title": "t"},
    )
    assert no_auth.status_code == 404
    wrong = client.post(
        f"/api/v1/inbox/ingest/{source['uuid']}",
        json={"guid": "g1", "title": "t"},
        headers={"Authorization": "Bearer wrong-secret"},
    )
    assert wrong.status_code == 404
    assert wrong.json()["error"]["type"] == "inbox_source_not_found"


def test_ingest_unknown_source_is_indistinguishable_404(client):
    resp = client.post(
        "/api/v1/inbox/ingest/missing-uuid",
        json={"guid": "g1"},
        headers={"Authorization": "Bearer whatever"},
    )
    assert resp.status_code == 404


def test_ingest_rejects_unknown_fields(client):
    source = _create_source(client)
    resp = _ingest(client, source, attachments=[{"url": "https://x"}])
    assert resp.status_code == 422


def test_ingest_rejects_non_http_url_and_bad_timestamp(client):
    source = _create_source(client)
    bad_url = _ingest(client, source, guid="a", url="javascript:alert(1)")
    assert bad_url.status_code == 400
    assert bad_url.json()["error"]["type"] == "invalid_inbox_payload"
    bad_ts = _ingest(client, source, guid="b", publishedAt="not-a-date")
    assert bad_ts.status_code == 400


# ---------------------------------------------------------------------------
# Ingest semantics: idempotency, sanitize boundary, projections
# ---------------------------------------------------------------------------


def test_ingest_is_idempotent_on_source_guid(client, db):
    source = _create_source(client)
    first = _ingest(client, source, guid="same")
    assert first.status_code == 200
    assert first.json()["status"] == "created"
    replay = _ingest(client, source, guid="same")
    assert replay.status_code == 200
    assert replay.json()["status"] == "exists"
    assert replay.json()["ref"] == first.json()["ref"]

    row = run(
        db.fetch_one(
            "SELECT COUNT(*) AS n FROM library_inbox WHERE guid = 'same'", ()
        )
    )
    assert row["n"] == 1


def test_ingest_sanitizes_untrusted_html_and_derives_text(client, db):
    source = _create_source(client)
    resp = _ingest(
        client,
        source,
        guid="html1",
        content=None,
        contentHtml=(
            '<p>safe paragraph</p><script>alert(1)</script>'
            '<img src="x" onerror="alert(2)"><a href="javascript:bad()">l</a>'
        ),
    )
    assert resp.status_code == 200
    ref = resp.json()["ref"]

    row = run(
        db.fetch_one(
            "SELECT content_html, content_text FROM library_inbox WHERE item_uuid = ?",
            (ref.removeprefix("library:"),),
        )
    )
    assert "<script" not in row["content_html"]
    assert "onerror" not in row["content_html"]
    assert "javascript:" not in row["content_html"]
    assert "safe paragraph" in row["content_html"]
    assert "safe paragraph" in row["content_text"]

    projection = run(
        db.fetch_one(
            "SELECT kind, title, body FROM search_library WHERE ref = ?", (ref,)
        )
    )
    assert projection is not None
    assert projection["kind"] == "api_item"
    assert "safe paragraph" in projection["body"]


def test_ingest_updates_connector_health(client, db):
    source = _create_source(client)
    _ingest(client, source, guid="h1")
    listed = client.get("/api/v1/inbox/sources").json()
    assert listed[0]["lastSuccessAt"] is not None
    assert listed[0]["lastError"] is None


# ---------------------------------------------------------------------------
# Listing, resolution, deletion
# ---------------------------------------------------------------------------


def test_list_items_is_newest_first_with_cursor(client, monkeypatch):
    source = _create_source(client)
    # Q-P2-28：同秒 ingest 的平局由 uuid 决定（随机）——注入递增时钟，
    # 让"最新摄取在前"成为可断言的真实排序，而不是碰运气。
    import lumirss.inbox_store as inbox_store

    counter = {"n": 0}

    def increasing_now():
        counter["n"] += 1
        return f"2026-09-13T10:00:{counter['n']:02d}+00:00"

    monkeypatch.setattr(inbox_store, "utc_now", increasing_now)

    pushed_refs: list[str] = []
    for i in range(3):
        resp = _ingest(client, source, guid=f"g{i}")
        assert resp.status_code == 200
        pushed_refs.append(resp.json()["ref"])

    page = client.get("/api/v1/inbox/items?limit=2").json()
    assert len(page["items"]) == 2
    assert page["hasMore"] is True
    assert page["nextCursor"]
    # 最新摄取在前（newest-first 的真实断言，旧断言只验证并集为 3）。
    assert page["items"][0]["ref"] == pushed_refs[2]
    assert page["items"][1]["ref"] == pushed_refs[1]

    seen = {item["ref"] for item in page["items"]}
    page2 = client.get(
        f"/api/v1/inbox/items?limit=2&cursor={page['nextCursor']}"
    ).json()
    seen |= {item["ref"] for item in page2["items"]}
    assert len(seen) == 3
    assert page2["hasMore"] is False


def test_resolve_returns_unified_api_item_card(client):
    source = _create_source(client, name="agent-feed")
    ref = _ingest(client, source, guid="r1").json()["ref"]
    resp = client.post("/api/v1/resolve", json={"refs": [ref]})
    assert resp.status_code == 200
    card = resp.json()["items"][0]
    assert card["kind"] == "api_item"
    assert card["ref"] == ref
    assert card["source"] == "Inbox · agent-feed"
    assert card["url"] == "https://example.com/a"
    assert card["payload"]["url"] == "https://example.com/a"
    assert card["stale"] is False


def test_resolve_dangling_inbox_ref_degrades_to_stale(client):
    fake = "library:00000000-0000-0000-0000-000000000000"
    resp = client.post("/api/v1/resolve", json={"refs": [fake]})
    card = resp.json()["items"][0]
    assert card["stale"] is True
    assert card["kind"] == "unknown"


def test_delete_item_removes_identity_and_projection(client, db):
    source = _create_source(client)
    ref = _ingest(client, source, guid="d1").json()["ref"]
    item_uuid = ref.removeprefix("library:")

    resp = client.delete(f"/api/v1/inbox/items/{item_uuid}")
    assert resp.status_code == 200
    identity = run(
        db.fetch_one(
            "SELECT kind FROM library_items WHERE uuid = ?", (item_uuid,)
        )
    )
    projection = run(
        db.fetch_one("SELECT ref FROM search_library WHERE ref = ?", (ref,))
    )
    assert identity is None
    assert projection is None

    again = client.delete(f"/api/v1/inbox/items/{item_uuid}")
    assert again.status_code == 404


def test_delete_source_cascades_items_and_projections(client, db):
    source = _create_source(client)
    ref1 = _ingest(client, source, guid="s1").json()["ref"]
    ref2 = _ingest(client, source, guid="s2").json()["ref"]

    resp = client.delete(f"/api/v1/inbox/sources/{source['uuid']}")
    assert resp.status_code == 200
    assert resp.json()["items"] == 2

    leftovers = run(
        db.fetch_all(
            "SELECT ref FROM search_library WHERE ref IN (?, ?)", (ref1, ref2)
        )
    )
    assert leftovers == []
    identities = run(
        db.fetch_one("SELECT COUNT(*) AS n FROM library_inbox", ())
    )
    assert identities["n"] == 0


def test_delete_source_is_atomic_when_projection_delete_fails(client, db):
    """Q-P1-04: identity rows and the search projection commit together —
    a failure mid-delete must roll back the WHOLE operation (the historic
    two-transaction shape left orphaned projections forever)."""
    source = _create_source(client)
    ref = _ingest(client, source, guid="atomic1").json()["ref"]

    run(
        db.execute(
            "CREATE TRIGGER fail_projection_delete BEFORE DELETE ON search_library BEGIN SELECT RAISE(ABORT, 'injected'); END",
            (),
        )
    )
    try:
        # The abort propagates (TestClient re-raises server exceptions);
        # the contract under test is the all-or-nothing DB state below.
        with pytest.raises(sqlite3.IntegrityError):
            client.delete(f"/api/v1/inbox/sources/{source['uuid']}")
        still_there = run(
            db.fetch_one(
                "SELECT COUNT(*) AS n FROM library_inbox WHERE source_uuid = ?",
                (source["uuid"],),
            )
        )
        projection = run(
            db.fetch_one("SELECT ref FROM search_library WHERE ref = ?", (ref,))
        )
        assert still_there["n"] == 1, "aborted delete must not lose items"
        assert projection is not None
    finally:
        run(db.execute("DROP TRIGGER fail_projection_delete", ()))

    resp = client.delete(f"/api/v1/inbox/sources/{source['uuid']}")
    assert resp.status_code == 200
    assert resp.json()["items"] == 1


def test_read_later_timeline_renders_inbox_item_as_resolved_card(client, db):
    """Q-P1-05: an inbox push added to read-later is a first-class
    member — the timeline must return the resolved registry view, not a
    fake-stale row showing the raw ref."""
    source = _create_source(client, name="reader-queue")
    pushed = _ingest(client, source, guid="rl1", title="稍后读的收件").json()["ref"]

    saved = client.post(
        "/api/v1/workspaces/read-later/items", json={"itemRef": pushed}
    )
    assert saved.status_code == 201, saved.text

    body = client.get("/api/v1/workspaces/read-later/timeline").json()
    assert len(body["items"]) == 1
    row = body["items"][0]
    assert row["stale"] is False
    assert row["resolved"] is not None
    assert row["resolved"]["ref"] == pushed
    assert row["resolved"]["title"] == "稍后读的收件"
    assert row["entry"] is None


def test_ingest_validation_failure_records_connector_error(client):
    """Q-P2-03: a rejected push must surface as the connector's lastError
    (the registry health face used to be permanently green)."""
    source = _create_source(client)
    resp = _ingest(client, source, guid="bad", url="javascript:alert(1)")
    assert resp.status_code == 400

    listed = client.get("/api/v1/inbox/sources").json()
    assert listed[0]["lastError"], "connector must record the rejection"


def test_ingest_non_ascii_bearer_is_404_not_500(client):
    """Q-P1-11: constant-time comparison must tolerate non-ASCII input
    (ASGI decodes headers as latin-1) — fail the match, never
    TypeError→500. HTTP-level non-ASCII is unsendable through test
    clients, so the comparator contract is proven directly."""
    from lumirss.util import constant_time_equals

    assert constant_time_equals("éé", "éé") is True
    assert constant_time_equals("é", "e") is False
    assert constant_time_equals("", "é") is False

    source = _create_source(client)
    resp = client.post(
        f"/api/v1/inbox/ingest/{source['uuid']}",
        json={"guid": "x", "content": "hi"},
        headers={"Authorization": "Bearer aa"},
    )
    assert resp.status_code == 404  # wrong secret → indistinguishable 404


# ---------------------------------------------------------------------------
# Migration rehearsal: v20 (production state) → v21
# ---------------------------------------------------------------------------


def test_upgrade_v20_to_v21_preserves_library_data(tmp_path, monkeypatch):
    import lumirss.migrations as migrations

    real_dir = migrations.MIGRATIONS_DIR
    staged = tmp_path / "v20"
    staged.mkdir()
    for path in sorted(real_dir.glob("*.sql")):
        if path.name < "0021":
            shutil.copy(path, staged / path.name)
    monkeypatch.setattr(migrations, "MIGRATIONS_DIR", staged)

    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    assert schema_version(db) == 20

    run(
        db.execute(
            "INSERT INTO library_items (uuid, kind, created_at) VALUES ('u-clip', 'clip', '2026-09-12T00:00:00+00:00')",
            (),
        )
    )
    run(
        db.execute(
            "INSERT INTO library_clips (item_uuid, url, title, byline, content_html, content_text, fetched_at, created_at) VALUES ('u-clip', 'https://x', 'T', NULL, '<p>b</p>', 'b', '2026-09-12T00:00:00+00:00', '2026-09-12T00:00:00+00:00')",
            (),
        )
    )

    monkeypatch.setattr(migrations, "MIGRATIONS_DIR", real_dir)
    db.invalidate_migration_cache()
    run(db.migrate())

    assert schema_version(db) == list_migrations()[-1][0]
    clip = run(
        db.fetch_one("SELECT title FROM library_clips WHERE item_uuid = 'u-clip'", ())
    )
    assert clip is not None, "v21 must not touch existing library rows"
    columns = run(
        db.fetch_all(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ('inbox_sources', 'library_inbox')",
            (),
        )
    )
    assert {c["name"] for c in columns} == {"inbox_sources", "library_inbox"}


def test_v21_enforces_connector_idempotency_at_schema_level(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    run(
        db.execute(
            "INSERT INTO inbox_sources (uuid, name, enabled, secret, created_at) VALUES ('s1', 'n', 1, 'sec', '2026-09-13T00:00:00+00:00')",
            (),
        )
    )
    run(
        db.execute(
            "INSERT INTO library_items (uuid, kind, created_at) VALUES ('i1', 'api_item', '2026-09-13T00:00:00+00:00')",
            (),
        )
    )
    run(
        db.execute(
            "INSERT INTO library_inbox (item_uuid, source_uuid, guid, title, created_at) VALUES ('i1', 's1', 'dup', 't', '2026-09-13T00:00:00+00:00')",
            (),
        )
    )
    run(
        db.execute(
            "INSERT INTO library_items (uuid, kind, created_at) VALUES ('i2', 'api_item', '2026-09-13T00:00:00+00:00')",
            (),
        )
    )
    with pytest.raises(DatabaseError):
        run(
            db.execute(
                "INSERT INTO library_inbox (item_uuid, source_uuid, guid, title, created_at) VALUES ('i2', 's1', 'dup', 't', '2026-09-13T00:00:00+00:00')",
                (),
            )
        )
