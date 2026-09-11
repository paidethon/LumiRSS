"""Derived library search projection (phase2 M2).

Same contract as the RSS ``search_entries`` projection: a plain table
queried with LIKE + ESCAPE (no FTS5 — the RSS leg does not use it and
introducing one would create a second search reality). Rows are written
synchronously on every library write path (clip create/delete, bookmark
create/delete/update) and the whole table is rebuildable from the owned
library tables at any time — it is never a source of truth.
"""

from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now


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
    ) -> list[dict[str, Any]]:
        """Bounded LIKE search across the library projection."""
        await self._db.migrate()
        needle = f"%{_escape_like(query.strip())}%"
        rows = await self._db.fetch_all(
            "SELECT ref, kind, title, body, url, updated_at FROM search_library"
            " WHERE (title LIKE ? ESCAPE '\\' OR body LIKE ? ESCAPE '\\' OR url LIKE ? ESCAPE '\\')"
            " AND (? IS NULL OR kind = ?)"
            " ORDER BY updated_at DESC, ref DESC LIMIT ?",
            (needle, needle, needle, kind, kind, max(1, min(limit, 50))),
        )
        return [dict(row) for row in rows]

    async def count(self) -> int:
        await self._db.migrate()
        row = await self._db.fetch_one("SELECT COUNT(*) AS n FROM search_library")
        return int(row["n"]) if row is not None else 0


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
