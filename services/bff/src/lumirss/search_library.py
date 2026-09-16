"""Derived library search projection (phase2 M2).

Same contract as the RSS ``search_entries`` projection: a plain table
queried with LIKE + ESCAPE (no FTS5 — the RSS leg does not use it and
introducing one would create a second search reality). Rows are written
synchronously on every library write path (clip create/delete, bookmark
create/delete/update) and the whole table is rebuildable from the owned
library tables at any time — it is never a source of truth.
"""

import json
import sqlite3
from typing import Any

from lumirss.cursor import InvalidCursor, decode_opaque_ref, encode_opaque_ref
from lumirss.storage import Database
from lumirss.util import utc_now

_LIBRARY_CURSOR_PREFIX = "ql1."
_LIBRARY_CURSOR_MAX = 512
# Internal hard row cap for probe-style reads. The ROUTE still caps its
# limit at 50 (routers/search.py); this cap only exists so search_page's
# limit+1 hasMore probe keeps working at page size 50 — with the old 50
# clamp the probe row was absorbed and hasMore lied at the boundary.
_HARD_ROW_CAP = 200


async def rss_keyword_search(db: Database, query: str, limit: int = 5) -> list[dict[str, Any]]:
    """Bounded keyword search over the RSS projection (agent tool path)."""
    await db.migrate()
    needle = f"%{_escape_like(query.strip())}%"
    rows = await db.fetch_all(
        "SELECT entry_ref, title, feed_title, content_text FROM search_entries WHERE (title LIKE ? ESCAPE '\\' OR content_text LIKE ? ESCAPE '\\') ORDER BY published_at DESC LIMIT ?",
        (needle, needle, max(1, min(limit, 20))),
    )
    return [dict(row) for row in rows]


class LibrarySearchWriter:
    """Projection writer for library-domain content."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def upsert(
        self,
        *,
        ref: str,
        kind: str,
        title: str,
        body: str,
        url: str | None,
    ) -> None:
        await self._db.migrate()
        now = utc_now()
        existing = await self._db.fetch_one(
            "SELECT ref FROM search_library WHERE ref = ?",
            (ref,),
        )
        if existing is None:
            await self._db.execute(
                "INSERT INTO search_library (ref, kind, title, body, url, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (ref, kind, title, body, url, now),
            )
        else:
            await self._db.execute(
                "UPDATE search_library SET kind = ?, title = ?, body = ?, url = ?, updated_at = ? WHERE ref = ?",
                (kind, title, body, url, now, ref),
            )

    async def delete(self, ref: str) -> None:
        await self._db.migrate()
        await self._db.execute(
            "DELETE FROM search_library WHERE ref = ?",
            (ref,),
        )

    async def search(
        self,
        query: str,
        *,
        kind: str | None = None,
        limit: int = 20,
        favorite_only: bool = False,
        keyset: tuple[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """Bounded LIKE search across the library projection.

        ``favorite_only`` and the keyset predicate run in SQL before
        LIMIT — a post-limit favorite filter silently dropped favorited
        hits outside the newest slice (pool #11)."""
        await self._db.migrate()
        needle = f"%{_escape_like(query.strip())}%"
        rows = await self._db.fetch_all(
            "SELECT ref, kind, title, body, url, updated_at FROM search_library"
            " WHERE (title LIKE ? ESCAPE '\\' OR body LIKE ? ESCAPE '\\' OR url LIKE ? ESCAPE '\\')"
            " AND (? IS NULL OR kind = ?)"
            " AND (? = 0 OR EXISTS (SELECT 1 FROM library_favorites fav"
            "      WHERE fav.ref = search_library.ref))"
            " AND (? IS NULL OR updated_at < ?"
            "      OR (updated_at = ? AND ref < ?))"
            " ORDER BY updated_at DESC, ref DESC LIMIT ?",
            (
                needle,
                needle,
                needle,
                kind,
                kind,
                int(favorite_only),
                None if keyset is None else keyset[0],
                None if keyset is None else keyset[0],
                None if keyset is None else keyset[0],
                None if keyset is None else keyset[1],
                max(1, min(limit, _HARD_ROW_CAP)),
            ),
        )
        return [dict(row) for row in rows]

    async def search_page(
        self,
        query: str,
        *,
        limit: int = 20,
        favorite_only: bool = False,
        keyset: tuple[str, str] | None = None,
    ) -> tuple[list[dict[str, Any]], bool]:
        """One keyset page plus an honest hasMore flag (limit+1 probe)."""
        rows = await self.search(
            query,
            limit=limit + 1,
            favorite_only=favorite_only,
            keyset=keyset,
        )
        has_more = len(rows) > limit
        return rows[:limit], has_more

    async def get_by_ref(self, ref: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT ref, kind, title, body, url, updated_at FROM search_library WHERE ref = ?",
            (ref,),
        )
        return dict(row) if row is not None else None

    async def starred_entries(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """RSS-domain starred entries from the RSS projection (FreshRSS
        star remains the truth; this reads its derived projection)."""
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT item_id, entry_ref, title, feed_title, feed_url, author, url, published_at, read, starred, content_text FROM search_entries WHERE starred = 1 ORDER BY published_at DESC LIMIT ?",
            (max(1, min(limit, 100)),),
        )
        return [
            {
                "entryRef": row["entry_ref"],
                "title": row["title"],
                "feedTitle": row["feed_title"],
                "feedUrl": row["feed_url"],
                "author": row["author"],
                "url": row["url"],
                "publishedAt": row["published_at"] or "",
                "read": bool(row["read"]),
                "starred": bool(row["starred"]),
                "snippet": (row["content_text"] or "")[:160],
                "matchedFields": [],
            }
            for row in rows
        ]

    async def count(self) -> int:
        await self._db.migrate()
        row = await self._db.fetch_one("SELECT COUNT(*) AS n FROM search_library")
        return int(row["n"]) if row is not None else 0


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def encode_library_search_cursor(
    updated_at: str, ref: str, *, scope: dict[str, Any]
) -> str:
    """Opaque library-leg cursor, bound to its query scope so a cursor
    replayed under a different query/filter is rejected instead of
    silently paging a different result set."""
    payload = json.dumps(
        {"u": updated_at, "r": ref, "s": scope}, ensure_ascii=False
    )
    return encode_opaque_ref(_LIBRARY_CURSOR_PREFIX, payload)


def decode_library_search_cursor(
    value: str, *, scope: dict[str, Any]
) -> tuple[str, str]:
    payload = decode_opaque_ref(
        value,
        prefix=_LIBRARY_CURSOR_PREFIX,
        max_length=_LIBRARY_CURSOR_MAX,
        error_type=InvalidCursor,
        description="Library search cursor",
    )
    try:
        parsed = json.loads(payload)
        updated_at, ref, cursor_scope = parsed["u"], parsed["r"], parsed["s"]
        if (
            not isinstance(updated_at, str)
            or not isinstance(ref, str)
            or cursor_scope != scope
        ):
            raise ValueError("cursor payload or scope mismatch")
    except ValueError as exc:
        raise InvalidCursor(
            "Library search cursor is invalid for this query."
        ) from exc
    return updated_at, ref


def upsert_search_row(
    conn: sqlite3.Connection,
    *,
    ref: str,
    kind: str,
    title: str,
    body: str,
    url: str | None,
    now: str,
) -> None:
    """Sync projection upsert for use inside a ``db_tx.transaction`` block.

    Same SELECT-then-INSERT/UPDATE shape as ``LibrarySearchWriter.upsert``
    (house rule: no UPSERT syntax) but on the caller's connection so the
    projection row commits atomically with the domain rows."""
    row = conn.execute("SELECT ref FROM search_library WHERE ref = ?", (ref,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO search_library (ref, kind, title, body, url, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (ref, kind, title, body, url, now),
        )
    else:
        conn.execute(
            "UPDATE search_library SET kind = ?, title = ?, body = ?, url = ?, updated_at = ? WHERE ref = ?",
            (kind, title, body, url, now, ref),
        )


def delete_search_row(conn: sqlite3.Connection, ref: str) -> None:
    """Sync projection delete for use inside a ``db_tx.transaction`` block."""
    conn.execute("DELETE FROM search_library WHERE ref = ?", (ref,))
