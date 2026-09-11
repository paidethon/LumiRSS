"""Federated favorites (phase2 G6).

RSS star stays in FreshRSS (read from the derived search projection's
starred flag — same projection global search uses); library favorites
are Lumi rows keyed by ItemRef. The favorites VIEW merges both domains
for display; neither state is ever copied into the other domain.
"""

from typing import Any

from lumirss.search_library import LibrarySearchWriter
from lumirss.storage import Database
from lumirss.util import utc_now


class FavoritesStore:
    """Lumi-side favorite markers over ItemRefs."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def add(self, ref: str) -> bool:
        from lumirss.itemref import parse_item_ref

        parsed = parse_item_ref(ref)
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT ref FROM library_favorites WHERE ref = ?",
            (parsed.format(),),
        )
        if row is not None:
            return False
        await self._db.execute(
            "INSERT INTO library_favorites (ref, created_at) VALUES (?, ?)",
            (parsed.format(), utc_now()),
        )
        return True

    async def remove(self, ref: str) -> bool:
        from lumirss.itemref import parse_item_ref

        parsed = parse_item_ref(ref)
        row = await self._db.fetch_one(
            "SELECT ref FROM library_favorites WHERE ref = ?",
            (parsed.format(),),
        )
        if row is None:
            return False
        await self._db.execute(
            "DELETE FROM library_favorites WHERE ref = ?",
            (parsed.format(),),
        )
        return True

    async def list_refs(self) -> list[str]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT ref FROM library_favorites ORDER BY created_at DESC LIMIT 500"
        )
        return [str(row["ref"]) for row in rows]


class FavoritesService:
    """Merged favorites view across the two ownership domains."""

    def __init__(self, db: Database, search_writer: LibrarySearchWriter) -> None:
        self._store = FavoritesStore(db)
        self._search = search_writer

    async def add_favorite(self, ref: str) -> bool:
        return await self._store.add(ref)

    async def remove_favorite(self, ref: str) -> bool:
        return await self._store.remove(ref)

    async def federated_favorites(self) -> dict[str, Any]:
        from lumirss.models import LibrarySearchItem, SearchItem

        rss_rows = await self._search.starred_entries(limit=50)
        rss_items = [SearchItem(**row) for row in rss_rows]
        library_items: list[LibrarySearchItem] = []
        library_error: str | None = None
        try:
            refs = await self._store.list_refs()
            for ref in refs[:50]:
                meta = await self._search.get_by_ref(ref)
                if meta is None:
                    continue
                library_items.append(
                    LibrarySearchItem(
                        ref=meta["ref"],
                        kind=meta["kind"],
                        title=meta["title"],
                        url=meta["url"],
                        snippet=(meta["body"] or "")[:160],
                        updatedAt=meta["updated_at"],
                    )
                )
        except Exception:  # noqa: BLE001 — library leg fails independently
            library_error = "库收藏暂不可用。"
        return {
            "rss": rss_items,
            "library": library_items,
            "libraryError": library_error,
        }
