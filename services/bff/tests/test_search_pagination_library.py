"""Unified-search library-leg regressions (pool #10/#11).

The library leg used to return a fixed newest-50 slice with no cursor —
so every RSS page re-listed the same rows (duplicates in infinite
scroll) and hits beyond the newest 50 were unreachable — and the
favorite filter ran in Python after the fetch, silently dropping
favorited hits outside the newest 50. These tests pin: keyset
pagination, filter-before-limit, and scope-bound cursors for both legs.
"""

import asyncio

import pytest

from lumirss.storage import Database


def _run(coroutine):
    return asyncio.run(coroutine)


def _seed_library(db: Database, n: int, *, term: str = "alpha") -> list[str]:
    """Insert n projection rows with distinct, deterministic updated_at."""

    async def seed() -> None:
        await db.migrate()
        for i in range(n):
            await db.execute(
                "INSERT INTO search_library (ref, kind, title, body, url, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    f"clip:{i:04d}",
                    "clip",
                    f"{term} item {i:04d}",
                    f"body {term} {i:04d}",
                    f"https://example.com/{i:04d}",
                    f"2026-01-{(i % 28) + 1:02d}T00:00:00.{i:06d}Z",
                ),
            )

    _run(seed())
    return [f"clip:{i:04d}" for i in range(n)]


def _favorite(db: Database, refs: list[str]) -> None:
    async def fav() -> None:
        await db.migrate()
        for ref in refs:
            await db.execute(
                "INSERT INTO library_favorites (ref, created_at) VALUES (?, ?)",
                (ref, "2026-01-01T00:00:00Z"),
            )

    _run(fav())


def test_library_leg_paginates_without_duplicates_or_losses(client):
    from lumirss.main import app

    refs = _seed_library(app.state.db, 120)
    seen: list[str] = []
    cursor: str | None = None
    for _page in range(20):
        params = {"q": "alpha", "limit": 20}
        if cursor is not None:
            params["libraryCursor"] = cursor
        response = client.get("/api/v1/search", params=params)
        assert response.status_code == 200
        body = response.json()
        seen.extend(hit["ref"] for hit in body["library"] or [])
        if not body.get("libraryHasMore"):
            break
        cursor = body.get("libraryNextCursor")
        assert cursor, "libraryHasMore=true must carry libraryNextCursor"
    else:
        pytest.fail("library leg never reported exhaustion")
    assert len(seen) == 120, f"expected all 120 hits, got {len(seen)}"
    assert len(set(seen)) == 120, "library pages must not repeat refs"
    assert set(seen) == set(refs)


def test_favorite_library_hits_survive_beyond_newest_50(client):
    """#11: the favorite filter must run before LIMIT, not after."""
    from lumirss.main import app

    db = app.state.db
    refs = _seed_library(db, 60)
    # Favorite only the five OLDEST rows — outside the newest-50 slice
    # the old implementation fetched before filtering.
    _favorite(db, refs[:5])
    response = client.get(
        "/api/v1/search",
        params={"q": "alpha", "favorite": "true", "limit": 20},
    )
    assert response.status_code == 200
    body = response.json()
    got = {hit["ref"] for hit in body["library"] or []}
    assert got == set(refs[:5])
    assert body["libraryHasMore"] is False


def test_library_cursor_is_bound_to_its_query_scope(client):
    from lumirss.main import app

    _seed_library(app.state.db, 30, term="alpha")
    first = client.get(
        "/api/v1/search", params={"q": "alpha", "limit": 10}
    ).json()
    assert first["libraryNextCursor"]
    replay = client.get(
        "/api/v1/search",
        params={"q": "completely", "libraryCursor": first["libraryNextCursor"]},
    )
    assert replay.status_code == 400
    assert replay.json()["error"]["type"] == "invalid_cursor"


def test_malformed_library_cursor_is_a_client_error(client):
    response = client.get(
        "/api/v1/search",
        params={"q": "alpha", "libraryCursor": "not-a-cursor!!"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_cursor"


def test_rss_cursor_scope_binding_unit():
    from lumirss.cursor import InvalidCursor
    from lumirss.search_index import (
        decode_search_cursor,
        encode_search_cursor,
    )

    scoped = encode_search_cursor(
        "2026-01-01T00:00:00Z", "i1", scope={"q": "alpha", "f": False}
    )
    assert decode_search_cursor(
        scoped, scope={"q": "alpha", "f": False}
    ) == ("2026-01-01T00:00:00Z", "i1")
    with pytest.raises(InvalidCursor):
        decode_search_cursor(scoped, scope={"q": "beta", "f": False})
    # Legacy q1 cursors (pre-scope) still decode when no scope is given.
    legacy = encode_search_cursor("2026-01-01T00:00:00Z", "i1")
    assert decode_search_cursor(legacy) == ("2026-01-01T00:00:00Z", "i1")


def test_rss_cursor_scope_mismatch_rejected_on_route(client, monkeypatch):
    """Replaying an RSS cursor under different filters must 400, not
    silently continue keyset paging under the new scope."""
    from lumirss.search_index import SearchIndexService, encode_search_cursor

    async def fake_search(**kwargs):
        return {
            "rows": [],
            "hasMore": False,
            "nextKeyset": None,
            "elapsedSplit": {},
        }

    cursor = encode_search_cursor(
        "2026-01-01T00:00:00Z", "i1", scope={"q": "alpha", "feedUrl": None}
    )
    monkeypatch.setattr(
        SearchIndexService, "search", fake_search, raising=True
    )
    response = client.get(
        "/api/v1/search", params={"q": "beta", "cursor": cursor}
    )
    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_cursor"
