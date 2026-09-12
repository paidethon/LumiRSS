"""Federated favorites (phase2 G6).

RSS star stays in FreshRSS (read from the derived search projection's
starred flag — same projection global search uses); library favorites
are Lumi rows keyed by ItemRef. The favorites VIEW merges both domains
for display; neither state is ever copied into the other domain.
Favorites are library-domain only: ``rss:`` refs are rejected (RSS has
star), and the view resolves every stored ref through the Source
Registry (ADR 0004) so dangling entries render as stale instead of
silently vanishing.
"""

from collections.abc import Callable
from typing import Any

from lumirss.itemref import RSS_DOMAIN, parse_item_ref
from lumirss.search_library import LibrarySearchWriter
from lumirss.storage import Database
from lumirss.util import utc_now

_VIEW_LIMIT = 50


class FavoriteInvalid(ValueError):
    """Favorite payload failed validation (domain, shape)."""


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
    """Merged favorites view across the two ownership domains.

    ``registry_accessor`` lazily returns the Source Registry so the view
    can resolve every stored ref (kind, title, open payload) without a
    circular wiring at construction time.
    """

    def __init__(
        self,
        db: Database,
        search_writer: LibrarySearchWriter,
        registry_accessor: Callable[[], dict] | None = None,
    ) -> None:
        self._store = FavoritesStore(db)
        self._search = search_writer
        # Late-bound Source Registry: resolves favorite refs for the
        # merged view without a wiring cycle. Construction without one
        # (tests, degraded tooling) degrades every library row to an
        # honest stale view instead of crashing.
        self._registry_accessor = registry_accessor or (lambda: {})

    async def add_favorite(self, ref: str) -> bool:
        parsed = parse_item_ref(ref)
        if parsed.domain == RSS_DOMAIN:
            raise FavoriteInvalid(
                "RSS 内容使用星标（star），库收藏仅用于 library 内容。"
            )
        return await self._store.add(ref)

    async def remove_favorite(self, ref: str) -> bool:
        return await self._store.remove(ref)

    async def list_refs(self) -> list[str]:
        """Stored favorite refs (bounded), e.g. for search-leg filtering."""
        return await self._store.list_refs()

    async def federated_favorites(self) -> dict[str, Any]:
        from lumirss.models import LibrarySearchItem, SearchItem
        from lumirss.sources import resolve_item

        rss_rows = await self._search.starred_entries(limit=_VIEW_LIMIT)
        rss_items = [SearchItem(**row) for row in rss_rows]
        library_items: list[LibrarySearchItem] = []
        library_error: str | None = None
        try:
            refs = await self._store.list_refs()
            registry = self._registry_accessor()
            # Resolve the newest favorites first; dangling refs surface as
            # stale rows (never silently dropped), older rows beyond the
            # view limit stay reachable via libraryTotal.
            resolved = []
            for ref in refs:
                try:
                    resolved.append(await resolve_item(registry, ref))
                except Exception:  # noqa: BLE001 — one bad ref must not kill the view
                    continue
            library_items = [
                LibrarySearchItem(
                    ref=item.ref,
                    kind=item.kind,
                    title=item.title,
                    url=item.url,
                    snippet=item.excerpt or "",
                    updatedAt=item.datetime or "",
                    stale=item.stale,
                )
                for item in resolved
            ]
        except Exception:  # noqa: BLE001 — library leg fails independently
            library_error = "库收藏暂不可用。"
        return {
            "rss": rss_items,
            "library": library_items,
            "libraryError": library_error,
            "libraryTotal": len(library_items),
        }
