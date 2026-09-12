"""Gate 1 foundation regressions (P0-01/02/10 backend).

Covers: kind-aware ItemRef resolution, write-time existence validation,
tag idempotency/cap ordering, case-insensitive tag dedupe (migration
0017), favorites domain rules + stale display, the server-driven
read-later timeline and graph scope/total honesty.
"""

import asyncio
from pathlib import Path

import pytest

from lumirss.graph import build_graph
from lumirss.library_clips import ClipStore


@pytest.fixture()
def db(client):
    return client.app.state.db


def _run(coro):
    return asyncio.run(coro)


def _rss_ref(item_id: str) -> str:
    from lumirss.entryref import encode_entry_ref

    return f"rss:{encode_entry_ref(item_id)}"


def _resolve_api(client, refs):
    return client.post("/api/v1/resolve", json={"refs": refs})


def _bookmark(client, n: int) -> str:
    resp = client.post(
        "/api/v1/library/bookmarks",
        json={"url": f"https://example.com/{n}", "title": f"B{n}"},
    )
    assert resp.status_code in (200, 201), resp.text
    body = resp.json()
    return body["ref"] if "ref" in body else body["item"]["ref"]


# -- ItemRef resolution covers every library kind (P0-02) -------------------


def test_resolve_covers_clip_kind(client, db):
    _run(db.migrate())
    view, _created = _run(
        ClipStore(db).create_clip(
            url="https://example.com/a",
            title="Clip A",
            content_html="<p>hello</p>",
            content_text="hello",
        )
    )
    resp = _resolve_api(client, [view.ref])
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["kind"] == "clip"
    assert item["title"] == "Clip A"
    assert item["stale"] is False
    assert item["payload"]["clipUuid"] == view.ref.split(":", 1)[1]


def test_resolve_covers_snapshot_kind(client, db, tmp_path):
    from lumirss.library_assets import AssetStore

    _run(db.migrate())
    store = AssetStore(db, tmp_path / "assets")
    record, _created = _run(store.save_snapshot(data=b"<html>ok</html>"))
    ref = f"library:{record.item_uuid}"
    resp = _resolve_api(client, [ref])
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["kind"] == "snapshot"
    assert item["stale"] is False
    assert item["payload"]["pageUrl"].endswith(
        f"/api/v1/library/assets/{record.uuid}/page.html"
    )


def test_resolve_batch_reports_unknown_refs_as_stale(client):
    resp = _resolve_api(
        client,
        [
            "library:00000000-0000-4000-8000-000000000001",
            "library:00000000-0000-4000-8000-000000000002",
        ],
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 2
    assert all(item["stale"] and item["kind"] == "unknown" for item in items)


# -- Write-time existence validation (ADR 0004) ------------------------------


def test_workspace_add_rejects_unresolvable_ref(client):
    client.post("/api/v1/workspaces", json={"name": "WS"})
    listing = client.get("/api/v1/workspaces").json()["items"]
    ws_id = next(w["id"] for w in listing if w["name"] == "WS")
    resp = client.post(
        f"/api/v1/workspaces/{ws_id}/items",
        json={"itemRef": "library:00000000-0000-4000-8000-000000000009"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["type"] == "invalid_workspace"


def test_tag_assign_rejects_unresolvable_ref(client):
    resp = client.post(
        "/api/v1/tags/assign",
        json={
            "itemRef": "library:00000000-0000-4000-8000-000000000009",
            "name": "ghost",
        },
    )
    assert resp.status_code == 400


# -- Tags: idempotency before cap + case-insensitive dedupe (P0-10f/g) -------


def test_tag_attach_idempotent_at_cap(client):
    ref = _bookmark(client, 1)
    names = [f"tag-{i:02d}" for i in range(30)]
    for name in names:
        resp = client.post(
            "/api/v1/tags/assign", json={"itemRef": ref, "name": name}
        )
        assert resp.status_code == 201, resp.text
    # Re-attaching an existing tag at the cap succeeds (idempotent).
    resp = client.post(
        "/api/v1/tags/assign", json={"itemRef": ref, "name": names[0]}
    )
    assert resp.status_code == 201
    # A 31st distinct tag hits the cap.
    resp = client.post(
        "/api/v1/tags/assign", json={"itemRef": ref, "name": "tag-30"}
    )
    assert resp.status_code == 400


def test_tag_names_dedupe_case_insensitively(client):
    ref = _bookmark(client, 2)
    first = client.post(
        "/api/v1/tags/assign", json={"itemRef": ref, "name": "AI"}
    )
    assert first.status_code == 201
    second = client.post(
        "/api/v1/tags/assign", json={"itemRef": ref, "name": "ai"}
    )
    assert second.status_code == 201
    listing = client.get("/api/v1/tags").json()["items"]
    matching = [t for t in listing if t["name"].lower() == "ai"]
    assert len(matching) == 1
    assert matching[0]["count"] == 1


def test_tag_detach_is_case_insensitive(client):
    ref = _bookmark(client, 3)
    client.post("/api/v1/tags/assign", json={"itemRef": ref, "name": "RAG"})
    resp = client.request(
        "DELETE", "/api/v1/tags/assign", json={"itemRef": ref, "name": "rag"}
    )
    assert resp.status_code == 204
    remaining = client.get(f"/api/v1/tags/item/{ref}").json()["items"]
    assert remaining == []


def test_migration_0017_merges_case_variants(client, db):
    """Replaying 0017 on a db carrying pre-0017 case variants merges them."""
    migration_sql = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "lumirss"
        / "migrations"
        / "0017_tag_name_nocase.sql"
    ).read_text(encoding="utf-8")
    ref = _bookmark(client, 4)
    client.post("/api/v1/tags/assign", json={"itemRef": ref, "name": "LLM"})
    connection = db._connect()  # noqa: SLF001 — test-side seeding
    try:
        connection.execute("DROP INDEX ix_tags_name_nocase")
        cursor = connection.execute("INSERT INTO tags (name) VALUES ('llm')")
        variant_id = int(cursor.lastrowid)
        created_at = "2026-01-01T00:00:00+00:00"
        connection.execute("INSERT INTO item_tags (item_ref, tag_id, origin, status, created_at) VALUES (?, ?, 'manual', 'active', ?)", (ref, variant_id, created_at))
        connection.commit()
    finally:
        connection.close()
    connection = db._connect()  # noqa: SLF001
    try:
        connection.executescript(migration_sql)  # replay the real migration
        rows = connection.execute("SELECT id FROM tags WHERE name = 'LLM' COLLATE NOCASE").fetchall()
        assert len(rows) == 1
        canonical = int(rows[0][0])
        bound = connection.execute("SELECT tag_id FROM item_tags WHERE item_ref = ?", (ref,)).fetchall()
        assert [int(r[0]) for r in bound] == [canonical]
    finally:
        connection.close()


# -- Favorites: domain rules + honest stale display (P0-10b) -----------------


def test_favorite_rejects_rss_ref(client):
    resp = client.post(
        "/api/v1/favorites/library",
        json={
            "ref": _rss_ref("tag:google.com,2005:reader/item/0000000000000001")
        },
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["type"] == "invalid_favorite"


def test_favorite_rejects_dangling_ref(client):
    resp = client.post(
        "/api/v1/favorites/library",
        json={"ref": "library:00000000-0000-4000-8000-000000000009"},
    )
    assert resp.status_code == 400


def test_favorites_view_marks_deleted_content_stale(client, db):
    bookmark_ref = _bookmark(client, 5)
    uuid = bookmark_ref.split(":", 1)[1]
    resp = client.post("/api/v1/favorites/library", json={"ref": bookmark_ref})
    assert resp.status_code == 204
    view = client.get("/api/v1/favorites").json()
    assert any(item["ref"] == bookmark_ref for item in view["library"])
    # Delete the content: the favorite degrades to a stale row, never a
    # silent drop (ADR 0004).
    client.delete(f"/api/v1/library/bookmarks/{uuid}")
    view = client.get("/api/v1/favorites").json()
    entry = next(
        item for item in view["library"] if item["ref"] == bookmark_ref
    )
    assert entry["stale"] is True
    _ = db


# -- Read-later timeline (P0-01) ----------------------------------------------


def _seed_rss_member(client, db, entry_id: int, added_at: str, title: str):
    entry_ref = _rss_ref(f"feed-{entry_id}/item-{entry_id:08d}")
    _run(db.execute("INSERT INTO search_entries (id, item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 0)", (entry_id, f"i{entry_id}/{entry_id}", entry_ref, "https://f.example.com", "Feed", title, "", "https://f.example.com/a", "text", "2026-01-01T00:00:00+00:00")))
    _run(db.execute("INSERT INTO workspace_items (workspace_id, item_ref, position, added_at) VALUES ('read-later', ?, 0, ?)", (entry_ref, added_at)))
    return entry_ref


def test_read_later_timeline_is_server_side_and_ordered(client, db):
    _run(db.migrate())
    _seed_rss_member(client, db, 101, "2026-01-01T00:00:01+00:00", "old")
    _seed_rss_member(client, db, 102, "2026-01-02T00:00:00+00:00", "new")
    resp = client.get("/api/v1/workspaces/read-later/timeline?limit=1")
    assert resp.status_code == 200
    body = resp.json()
    assert [i["entry"]["title"] for i in body["items"]] == ["new"]
    assert body["nextCursor"] is not None
    page2 = client.get(
        f"/api/v1/workspaces/read-later/timeline?limit=1&cursor={body['nextCursor']}"
    ).json()
    assert [i["entry"]["title"] for i in page2["items"]] == ["old"]
    assert page2["nextCursor"] is None
    _ = db


def test_read_later_timeline_keeps_dangling_members_visible(client, db):
    fixed_at = "2026-01-01T00:00:00+00:00"
    _run(db.migrate())
    _run(db.execute("INSERT INTO workspace_items (workspace_id, item_ref, position, added_at) VALUES ('read-later', 'rss:e1.999999', 0, ?)", (fixed_at,)))
    body = client.get("/api/v1/workspaces/read-later/timeline").json()
    assert len(body["items"]) == 1
    assert body["items"][0]["stale"] is True
    assert body["items"][0]["entry"] is None


def test_read_later_timeline_cursor_rejects_garbage(client):
    resp = client.get(
        "/api/v1/workspaces/read-later/timeline?cursor=not-a-cursor"
    )
    assert resp.status_code == 400


# -- Graph: scope isolation, honest totals, wikilink truth (P0-10c/d/e) ------


def test_graph_totals_report_truncation_honestly(client, db):
    for n in range(12):
        ref = _bookmark(client, 100 + n)
        client.post(
            "/api/v1/tags/assign", json={"itemRef": ref, "name": f"g{n}"}
        )
    result = _run(build_graph(db, scope="all", max_nodes=10))
    assert result["truncated"] is True
    assert result["totalNodes"] > result["returnedNodes"]
    assert result["returnedNodes"] <= 10


def test_graph_workspace_scope_excludes_foreign_edges(client, db):
    member_ref = _bookmark(client, 200)
    foreign_ref = _bookmark(client, 201)
    client.post("/api/v1/workspaces", json={"name": "Scoped"})
    listing = client.get("/api/v1/workspaces").json()["items"]
    ws_id = next(w["id"] for w in listing if w["name"] == "Scoped")
    client.post(
        f"/api/v1/workspaces/{ws_id}/items", json={"itemRef": member_ref}
    )
    client.post(
        "/api/v1/tags/assign", json={"itemRef": member_ref, "name": "in-scope"}
    )
    client.post(
        "/api/v1/tags/assign",
        json={"itemRef": foreign_ref, "name": "out-scope"},
    )
    scoped = _run(build_graph(db, scope=f"workspace:{ws_id}", max_nodes=2000))
    names = {n["label"] for n in scoped["nodes"]}
    assert "#in-scope" in names
    assert "#out-scope" not in names
    assert scoped["totalNodes"] == scoped["returnedNodes"]


def test_graph_wikilinks_resolve_to_real_notes(client, db, tmp_path):
    note_a = "---\ntitle: 注意力机制\n---\n参见 [[transformer]]。"
    note_b = "---\ntitle: transformer\n---\ntransformer 笔记。"
    vault = tmp_path / "vault"
    (vault / "AI").mkdir(parents=True)
    (vault / "AI" / "a.md").write_text(note_a, encoding="utf-8")
    (vault / "AI" / "b.md").write_text(note_b, encoding="utf-8")
    from lumirss.obsidian import ObsidianService

    service = ObsidianService(db)

    async def _seed():
        await service.set_vault_path(str(vault))
        await service.rescan()

    _run(_seed())
    result = _run(build_graph(db, scope="all", max_nodes=2000))
    edge_kinds = {e["kind"] for e in result["edges"]}
    assert "wikilink" in edge_kinds
    unresolved = [n for n in result["nodes"] if n["kind"] == "unresolved"]
    assert unresolved == []


def test_graph_wikilink_to_missing_note_is_explicitly_unresolved(
    client, db, tmp_path
):
    note = "---\ntitle: 孤立笔记\n---\n参见 [[ghost-note]]。"
    vault = tmp_path / "vault"
    vault.mkdir(parents=True)
    (vault / "c.md").write_text(note, encoding="utf-8")
    from lumirss.obsidian import ObsidianService

    service = ObsidianService(db)

    async def _seed():
        await service.set_vault_path(str(vault))
        await service.rescan()

    _run(_seed())
    result = _run(build_graph(db, scope="all", max_nodes=2000))
    unresolved = [n for n in result["nodes"] if n["kind"] == "unresolved"]
    assert len(unresolved) == 1
    assert unresolved[0]["label"] == "ghost-note"


def test_tag_items_endpoint_returns_resolved_cards(client):
    ref = _bookmark(client, 300)
    client.post("/api/v1/tags/assign", json={"itemRef": ref, "name": "items"})
    listing = client.get("/api/v1/tags").json()["items"]
    tag_id = next(t["id"] for t in listing if t["name"] == "items")
    resp = client.get(f"/api/v1/tags/{tag_id}/items")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["ref"] == ref
    assert items[0]["kind"] == "bookmark"
