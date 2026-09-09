"""Global search — derived, rebuildable projection (0022).

FreshRSS 1.29.1 does not expose search over the greader API (probe:
``search`` is ignored on both stream/contents and stream/items/ids), so
Lumi keeps a small SQLite projection built from the entries FreshRSS
already serves. This is a derived index, NOT a second RSS store:

- 100% rebuildable from FreshRSS at any time (``rebuild``);
- never a source of truth — deleting the tables loses no RSS state and
  search results still open through the normal FreshRSS-backed entry
  endpoints;
- the projection only feeds search (self-healing: the startup sync
  rebuilds an empty index, and entry-state writes made through the BFF
  are mirrored best-effort).

All SQL lives in the storage modules (search_store / search_writer /
search_meta_store). Query semantics: whitespace-split terms, all terms
required, case-insensitive substring match per term across title,
content text and author. Pagination is a (published_at, item_id) keyset
wrapped in the opaque ``q1.`` cursor envelope.
"""

import json
import time

from lumirss.cursor import InvalidCursor
from lumirss.opaque_ref import decode_opaque_ref, encode_opaque_ref

from .adapters.freshrss import ConfigError, FreshRSSAdapter
from .search_meta_store import SearchFeedStore
from .search_store import SearchStore
from .search_writer import SearchEntryWriter
from .storage import Database

_SEARCH_CURSOR_PREFIX = "q1."
_SEARCH_CURSOR_MAX = 512
_MAX_SEARCH_TERMS = 4
_SYNC_INTERVAL_SECONDS = 60.0
_REBUILD_MAX_PAGES = 200
_INCREMENTAL_MAX_PAGES = 10


class SearchQueryError(ValueError):
    """A search parameter is structurally invalid (mapped to 400)."""


def split_terms(query: str) -> list[str]:
    """Split on whitespace; quotes are treated as plain characters."""
    return [term for term in query.split() if term]


def encode_search_cursor(published_at: str, item_id: str) -> str:
    payload = json.dumps({"p": published_at, "i": item_id}, ensure_ascii=False)
    return encode_opaque_ref(_SEARCH_CURSOR_PREFIX, payload)


def decode_search_cursor(value: str) -> tuple[str, str]:
    payload = decode_opaque_ref(
        value,
        prefix=_SEARCH_CURSOR_PREFIX,
        max_length=_SEARCH_CURSOR_MAX,
        error_type=InvalidCursor,
        description="Search cursor",
    )
    try:
        parsed = json.loads(payload)
        published_at, item_id = parsed["p"], parsed["i"]
        if not isinstance(published_at, str) or not isinstance(item_id, str):
            raise ValueError("cursor payload has wrong types")
    except ValueError as exc:
        raise InvalidCursor("Search cursor payload is invalid.") from exc
    return published_at, item_id


class SearchIndexService:
    """Builds and queries the derived search projection."""

    def __init__(
        self, database: Database, adapter: FreshRSSAdapter | None
    ) -> None:
        self._db = database
        self._adapter = adapter
        self._store = SearchStore(database)
        self._writer = SearchEntryWriter(database)
        self._feeds = SearchFeedStore(database)

    # -- sync ---------------------------------------------------------------

    async def rebuild(self, *, max_pages: int = _REBUILD_MAX_PAGES) -> dict:
        """Replace the whole projection from FreshRSS (bounded).

        Returns honest stats: ``partial`` is True when the cap stopped
        the walk before the upstream continuation ran out.
        """
        self._require_adapter()
        await self._db.migrate()
        started = time.time()
        pages = 0
        total = 0
        continuation: str | None = None
        partial = False
        while pages < max_pages:
            page = await self._adapter.list_entry_documents(
                continuation=continuation
            )
            pages += 1
            if page.documents:
                await self._replace_documents(page.documents)
                total += len(page.documents)
            continuation = page.upstreamContinuation
            if continuation is None:
                break
        if continuation is not None:
            partial = True
        now = int(time.time())
        await self._refresh_feed_categories(now)
        await self._feeds.meta_set("last_synced_at", str(now * 1000))
        await self._feeds.meta_set("partial", "1" if partial else "0")
        return {
            "entryCount": total,
            "pages": pages,
            "partial": partial,
            "elapsedMs": int((time.time() - started) * 1000),
        }

    async def sync_incremental(
        self, *, max_pages: int = _INCREMENTAL_MAX_PAGES
    ) -> dict:
        """Newest-first walk; stop when a page adds nothing new.

        Pages arrive newest-first, so a fully-known page means everything
        behind it is already indexed.
        """
        self._require_adapter()
        await self._db.migrate()
        started = time.time()
        continuation: str | None = None
        scanned = 0
        updated = 0
        for _page in range(max_pages):
            page = await self._adapter.list_entry_documents(
                continuation=continuation
            )
            known = await self._known_states()
            changed: list = []
            for doc in page.documents:
                scanned += 1
                state = known.get(doc.item_id)
                if (
                    state is not None
                    and state["published_at"] == doc.publishedAt
                    and state["read"] == int(doc.read)
                    and state["starred"] == int(doc.starred)
                ):
                    continue
                changed.append(doc)
                updated += 1
            if changed:
                await self._replace_documents(changed)
            if page.documents and not changed:
                break
            continuation = page.upstreamContinuation
            if continuation is None:
                break
        await self._refresh_feed_categories(int(time.time()))
        await self._feeds.meta_set(
            "last_synced_at", str(int(time.time() * 1000))
        )
        await self._feeds.meta_set("partial", "0")
        return {
            "scanned": scanned,
            "updated": updated,
            "elapsedMs": int((time.time() - started) * 1000),
        }

    async def maybe_sync(self) -> None:
        """Startup-time entry point: rebuild when empty, else catch up.

        Best-effort by design: a FreshRSS outage must never break app
        startup — the next cycle (or an explicit rebuild) heals it.
        """
        if self._adapter is None:
            return
        try:
            count = await self.entry_count()
            if count == 0:
                await self.rebuild()
            elif await self._stale():
                await self.sync_incremental()
        except ConfigError:
            # FreshRSS not configured (tests, degraded dev) — nothing to index.
            return

    def _require_adapter(self) -> FreshRSSAdapter:
        if self._adapter is None:
            raise ConfigError(
                "FreshRSS is not configured; the search index cannot sync."
            )
        return self._adapter

    async def entry_count(self) -> int:
        await self._db.migrate()
        return await self._store.count()

    async def index_info(self) -> dict:
        count = await self.entry_count()
        last = await self._store.meta_get("last_synced_at")
        partial = await self._store.meta_get("partial")
        return {
            "entryCount": count,
            "lastSyncedAt": last,
            "partial": partial == "1",
        }

    # -- query --------------------------------------------------------------

    async def search(
        self,
        *,
        query: str,
        limit: int,
        keyset: tuple[str, str] | None = None,
        feed_url: str | None = None,
        category_id: str | None = None,
        unread_only: bool = False,
        starred_only: bool = False,
        published_from: str | None = None,
        published_to: str | None = None,
    ) -> dict:
        """One page of hits, newest first, with a safe plain-text excerpt."""
        await self._db.migrate()
        terms = split_terms(query)
        if not terms:
            raise SearchQueryError("Search query is empty.")
        if len(terms) > _MAX_SEARCH_TERMS:
            raise SearchQueryError(
                f"Search supports at most {_MAX_SEARCH_TERMS} terms."
            )
        rows = await self._store.query(
            terms=terms,
            feed_url=feed_url,
            category_id=category_id,
            unread_only=unread_only,
            starred_only=starred_only,
            published_from=published_from,
            published_to=published_to,
            keyset=keyset,
            limit=limit,
        )
        has_more = len(rows) > limit
        rows = rows[:limit]
        terms_folded = [term.casefold() for term in terms]
        items = []
        for row in rows:
            items.append(
                {
                    "entryRef": row["entry_ref"],
                    "title": row["title"],
                    "feedTitle": row["feed_title"],
                    "feedUrl": row["feed_url"],
                    "author": row["author"] or None,
                    "url": row["url"],
                    "publishedAt": row["published_at"],
                    "read": bool(row["read"]),
                    "starred": bool(row["starred"]),
                    "snippet": build_snippet(
                        row["content_text"], terms_folded
                    ),
                    "matchedFields": matched_fields(row, terms_folded),
                }
            )
        next_keyset = None
        if has_more and rows:
            last = rows[-1]
            next_keyset = (last["published_at"], last["item_id"])
        return {
            "rows": items,
            "hasMore": has_more,
            "nextKeyset": next_keyset,
        }

    # -- write-through ------------------------------------------------------

    async def set_entry_read(self, entry_ref: str, read: bool) -> None:
        """Mirror a read-state write (set semantics) into the projection.

        A no-op when the entry is not indexed yet; the next sync picks
        the state up from FreshRSS either way.
        """
        await self._db.migrate()
        await self._writer.set_read(entry_ref, int(read))

    async def set_entry_starred(self, entry_ref: str, starred: bool) -> None:
        """Mirror a starred-state write (set semantics) into the projection.

        A no-op when the entry is not indexed yet; the next sync picks
        the state up from FreshRSS either way.
        """
        await self._db.migrate()
        await self._writer.set_starred(entry_ref, int(starred))

    # -- internals ----------------------------------------------------------

    async def _replace_documents(self, documents: list) -> None:
        """Replace the projected rows for these entries (delete + insert)."""
        now = int(time.time())
        for doc in documents:
            await self._writer.delete_entry(doc.item_id)
            await self._writer.insert_entry(
                item_id=doc.item_id,
                entry_ref=doc.entryRef,
                feed_url=doc.feedUrl,
                feed_title=doc.feedTitle,
                title=doc.title,
                author=doc.author or "",
                url=doc.url or "",
                content_text=doc.contentText,
                published_at=doc.publishedAt,
                read=int(doc.read),
                starred=int(doc.starred),
                fetched_at=now,
            )

    async def _refresh_feed_categories(self, now: int) -> None:
        """Mirror the FreshRSS subscription list into search_feeds."""
        feeds = await self._require_adapter().list_feeds()
        await self._feeds.clear_feeds()
        for feed in feeds:
            await self._feeds.insert_feed(
                feed_url=feed.feed_url,
                feed_title=feed.title,
                category_id=feed.category_id,
                refreshed_at=now,
            )

    async def _known_states(self) -> dict:
        rows = await self._store.known_states()
        states = {}
        for row in rows:
            states[row["item_id"]] = {
                "published_at": row["published_at"],
                "read": row["read"],
                "starred": row["starred"],
            }
        return states

    async def _stale(self) -> bool:
        last = await self._store.meta_get("last_synced_at")
        if last is None:
            return True
        try:
            age = time.time() - int(last) / 1000
        except ValueError:
            return True
        return age >= _SYNC_INTERVAL_SECONDS


def matched_fields(row, terms_folded: list[str]) -> list[str]:
    """Which indexed fields visibly contain a term (case-insensitive)."""
    title = row["title"].casefold()
    feed = row["feed_title"].casefold()
    author = (row["author"] or "").casefold()
    content = (row["content_text"] or "").casefold()
    fields: list[str] = []
    if any(term in title for term in terms_folded):
        fields.append("title")
    if any(term in feed for term in terms_folded):
        fields.append("feed")
    if author and any(term in author for term in terms_folded):
        fields.append("author")
    if any(term in content for term in terms_folded):
        fields.append("content")
    return fields or ["content"]


def build_snippet(content: str, terms_folded: list[str], width: int = 80) -> str:
    """Plain-text excerpt around the first term hit (always safe text)."""
    if not content:
        return ""
    folded = content.casefold()
    position = -1
    for term in terms_folded:
        position = folded.find(term)
        if position >= 0:
            break
    if position < 0:
        return content[:width]
    start = max(0, position - width // 2)
    end = min(len(content), position + width // 2)
    prefix = "… " if start > 0 else ""
    suffix = " …" if end < len(content) else ""
    return f"{prefix}{content[start:end].strip()}{suffix}"
