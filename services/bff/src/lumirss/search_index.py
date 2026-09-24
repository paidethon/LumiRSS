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

import asyncio
import contextlib
import json
import time
from typing import Any

from lumirss.cursor import InvalidCursor
from lumirss.opaque_ref import decode_opaque_ref, encode_opaque_ref

from .adapters.freshrss import ConfigError, FreshRSSAdapter
from .entry_intake import content_hash
from .models import EntryDocument
from .search_meta_store import SearchFeedStore
from .search_store import SearchStore
from .search_writer import SearchEntryWriter
from .storage import Database

_SEARCH_CURSOR_PREFIX = "q1."
_SEARCH_CURSOR_V2_PREFIX = "q2."
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


def encode_search_cursor(
    published_at: str, item_id: str, *, scope: dict | None = None
) -> str:
    """``q1.`` is the legacy unscoped envelope; ``q2.`` binds the cursor
    to its query scope so replaying it under different filters is a
    400, not silent paging of a different result set (pool #10)."""
    payload: dict
    prefix = _SEARCH_CURSOR_PREFIX
    if scope is not None:
        prefix = _SEARCH_CURSOR_V2_PREFIX
        payload = {"p": published_at, "i": item_id, "s": scope}
    else:
        payload = {"p": published_at, "i": item_id}
    return encode_opaque_ref(
        prefix, json.dumps(payload, ensure_ascii=False)
    )


def decode_search_cursor(
    value: str, *, scope: dict | None = None
) -> tuple[str, str]:
    v2 = value.startswith(_SEARCH_CURSOR_V2_PREFIX)
    payload = decode_opaque_ref(
        value,
        prefix=_SEARCH_CURSOR_V2_PREFIX if v2 else _SEARCH_CURSOR_PREFIX,
        max_length=_SEARCH_CURSOR_MAX,
        error_type=InvalidCursor,
        description="Search cursor",
    )
    try:
        parsed = json.loads(payload)
        published_at, item_id = parsed["p"], parsed["i"]
        if not isinstance(published_at, str) or not isinstance(item_id, str):
            raise ValueError("cursor payload has wrong types")
        if v2 and (scope is None or parsed.get("s") != scope):
            raise ValueError("cursor scope mismatch")
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
        # FreshRSS stream items carry only feed/<numeric-id>, not the feed
        # URL; the subscription list provides the title -> URL mapping used
        # to resolve feed scoping for harvested documents.
        self._feed_title_to_url: dict[str, str] = {}
        # Serializes rebuild(): two concurrent rebuilds (manual API + the
        # background sync loop) would DROP each other's staging table.
        self._rebuild_lock = asyncio.Lock()

    @property
    def store(self) -> SearchStore:
        """Read-path store — N142 source resolution / N143 row lookup /
        N145 aggregates resolve against the SAME projection this service
        queries (tests override the whole service; prod = the routed
        per-user DB either way)."""
        return self._store

    # -- sync ---------------------------------------------------------------

    async def rebuild(self, *, max_pages: int = _REBUILD_MAX_PAGES) -> dict:
        """Replace the whole projection from FreshRSS (bounded).

        Pages stream into a staging table while the live projection keeps
        serving; staging swaps in during ONE short transaction. A failure
        mid-walk therefore leaves the previous index intact and marks
        ``rebuild_incomplete`` so the next sync retries a full rebuild.
        Returns honest stats: ``partial`` is True when the cap stopped
        the walk before the upstream continuation ran out.
        """
        async with self._rebuild_lock:
            return await self._rebuild_locked(max_pages=max_pages)

    async def _rebuild_locked(self, *, max_pages: int) -> dict:
        self._require_adapter()
        await self._db.migrate()
        started = time.time()
        await self._feeds.meta_set("rebuild_incomplete", "1")
        await self._refresh_feed_categories(int(started))
        await self._db.execute("DROP TABLE IF EXISTS search_rebuild_stage")
        # N031/N032/N034/N040：stage 表携带 intake 元数据列——
        # content_max_len 从活投影带入（子查询）、content_hash/time_flags
        # 按 stage 时刻计算、crawled_at 来自适配器——swap 后投影语义不变。
        await self._db.execute(
            "CREATE TABLE search_rebuild_stage (item_id TEXT UNIQUE NOT NULL, entry_ref TEXT UNIQUE NOT NULL, feed_url TEXT NOT NULL, feed_title TEXT NOT NULL DEFAULT '', title TEXT NOT NULL DEFAULT '', author TEXT NOT NULL DEFAULT '', url TEXT NOT NULL DEFAULT '', content_text TEXT NOT NULL DEFAULT '', published_at TEXT NOT NULL, read INTEGER NOT NULL DEFAULT 0, starred INTEGER NOT NULL DEFAULT 0, fetched_at INTEGER NOT NULL, content_max_len INTEGER NOT NULL DEFAULT 0, content_hash TEXT NOT NULL DEFAULT '', time_flags INTEGER NOT NULL DEFAULT 0, crawled_at TEXT)"
        )
        pages = 0
        total = 0
        continuation: str | None = None
        partial = False
        try:
            while pages < max_pages:
                page = await self._adapter.list_entry_documents(
                    continuation=continuation
                )
                pages += 1
                if page.documents:
                    await self._writer.stage_documents(
                        page.documents,
                        feed_urls=[self._resolve_feed_url(doc) for doc in page.documents],
                        fetched_at=int(time.time()),
                    )
                    total += len(page.documents)
                continuation = page.upstreamContinuation
                if continuation is None:
                    break
            if continuation is not None:
                partial = True
            now = int(time.time())
            await self._refresh_feed_categories(now)
            await self._writer.swap_staged()
        except BaseException:
            with contextlib.suppress(Exception):
                await self._db.execute(
                    "DROP TABLE IF EXISTS search_rebuild_stage"
                )
            raise
        await self._db.execute("DROP TABLE IF EXISTS search_rebuild_stage")
        await self._feeds.meta_set("last_synced_at", str(now * 1000))
        await self._feeds.meta_set("partial", "1" if partial else "0")
        await self._feeds.meta_set("rebuild_incomplete", "0")
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
        # Hoisted: a full-table state read per page was pure repeat work.
        # N031：state 额外携带 content_hash —— 同一 id 重新交付但内容
        # 哈希变化的条目必须进入 replace 管线（修订/变体在写入路径捕获）。
        known = await self._known_states()
        for _page in range(max_pages):
            page = await self._adapter.list_entry_documents(
                continuation=continuation
            )
            changed: list = []
            for doc in page.documents:
                scanned += 1
                state = known.get(doc.item_id)
                doc_hash = content_hash(doc.contentHtml or "")
                if (
                    state is not None
                    and state["published_at"] == doc.publishedAt
                    and state["read"] == int(doc.read)
                    and state["starred"] == int(doc.starred)
                    and state["content_hash"] == doc_hash
                ):
                    continue
                changed.append(doc)
                known[doc.item_id] = {
                    "published_at": doc.publishedAt,
                    "read": int(doc.read),
                    "starred": int(doc.starred),
                    "content_hash": doc_hash,
                }
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
        """Startup-time entry point: rebuild when empty or when a previous
        rebuild aborted, else catch up.

        Best-effort by design: a FreshRSS outage must never break app
        startup — the next cycle (or an explicit rebuild) heals it.
        """
        if self._adapter is None:
            return
        try:
            count = await self.entry_count()
            incomplete = (
                await self._store.meta_get("rebuild_incomplete")
            ) == "1"
            if count == 0 or incomplete:
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
        intitle: str | None = None,
        phrase: str | None = None,
        exclude: str | None = None,
        has_summary: bool | None = None,
        expand_synonyms: bool = False,
        synonym_map: dict | None = None,
    ) -> dict:
        """One page of hits, newest first, with a safe plain-text excerpt.

        F29 高级条件（可选）：``intitle`` 仅标题词条；``phrase`` 精确
        短语；``exclude`` 排除词条（全部 whitespace-split、有界）。
        """
        await self._db.migrate()
        terms = split_terms(query)
        if not terms:
            raise SearchQueryError("Search query is empty.")
        if len(terms) > _MAX_SEARCH_TERMS:
            raise SearchQueryError(
                f"Search supports at most {_MAX_SEARCH_TERMS} terms."
            )
        # F078：同义词单层扩展（命中 term 并入 expansions；不递归；
        # expand_synonyms=False 或无命中 → 原词原样）。
        matched_synonyms: list[dict] = []
        added_expansions: list[str] = []
        if expand_synonyms:
            from lumirss.search_synonyms import expand_terms
            MAX_EFFECTIVE_TERMS = 100

            synonym_map = synonym_map if synonym_map is not None else await self._load_synonym_map()
            lowered = [t.casefold() for t in terms]
            for term_folded, expansions in synonym_map.items():
                if term_folded in lowered:
                    matched_synonyms.append({"term": term_folded, "expansions": expansions})
            if matched_synonyms:
                original_terms = list(terms)
                terms = expand_terms(terms, synonym_map)[:MAX_EFFECTIVE_TERMS]
                added_expansions = [t for t in terms if t.casefold() not in {x.casefold() for x in original_terms}]
        intitle_terms = split_terms(intitle or "")
        if len(intitle_terms) > 2:
            raise SearchQueryError("intitle supports at most 2 terms.")
        exclude_terms = split_terms(exclude or "")
        if len(exclude_terms) > 2:
            raise SearchQueryError("exclude supports at most 2 terms.")
        clean_phrase = (phrase or "").strip()
        if len(clean_phrase) > 120:
            raise SearchQueryError("phrase is too long.")
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
            intitle_terms=intitle_terms or None,
            phrase=clean_phrase or None,
            exclude_terms=exclude_terms or None,
            has_summary=has_summary,
        )
        has_more = len(rows) > limit
        primary_rows = rows[:limit]
        # F078：扩展词 OR 合并——原词条走主查询（分页契约不变），每个
        # 扩展词单独一次有界查询，去重后并入首页（诚实：扩展命中标注
        # cached 语义不变；主查询的 keyset/hasMore 不受影响）。
        extra_rows: list = []
        seen_ids = {str(r["item_id"]) for r in primary_rows}
        if added_expansions:
            expansions: list[str] = list(added_expansions)
            for expansion in expansions[: max(0, 100 - len(terms))]:
                expansion_rows = await self._store.query(
                    terms=split_terms(expansion),
                    feed_url=feed_url,
                    category_id=category_id,
                    unread_only=unread_only,
                    starred_only=starred_only,
                    published_from=published_from,
                    published_to=published_to,
                    keyset=None,
                    limit=250,
                    has_summary=has_summary,
                )
                for row in expansion_rows:
                    item_id = str(row["item_id"])
                    if item_id not in seen_ids:
                        seen_ids.add(item_id)
                        extra_rows.append(row)
        rows = primary_rows + extra_rows[: max(0, limit * 2 - len(primary_rows))]
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
                    # F072：命中偏移（老客户端可选字段；仅正文命中时非空）
                    "matchPositions": match_positions(
                        row["content_text"], terms_folded
                    ),
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
            # F078：本次命中的同义词（preview/解释用；未开启扩展 → 空表）
            "matchedSynonyms": matched_synonyms,
        }

    async def _load_synonym_map(self) -> dict:
        from lumirss.search_synonyms import SynonymStore

        try:
            return await SynonymStore(self._db).load_enabled_map()
        except Exception:  # noqa: BLE001 — 同义词加载失败 fail-open（不扩展）
            return {}

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
        """Replace the projected rows for these entries (one transaction)."""
        await self._writer.replace_entries(
            documents,
            feed_urls=[self._resolve_feed_url(doc) for doc in documents],
            fetched_at=int(time.time()),
        )

    async def _refresh_feed_categories(self, now: int) -> None:
        """Mirror the FreshRSS subscription list into search_feeds, and
        refresh the title -> feed_url resolution map for the harvest."""
        feeds = await self._require_adapter().list_feeds()
        self._feed_title_to_url = {
            feed.title: feed.feed_url for feed in feeds if feed.title
        }
        await self._feeds.clear_feeds()
        await self._feeds.replace_feeds(feeds, refreshed_at=now)

    def _resolve_feed_url(self, doc: EntryDocument) -> str:
        """Real feed URL for a harvested document.

        FreshRSS stream items expose ``origin.streamId = feed/<numeric>``,
        not the feed URL, so the sync resolves the URL through the
        subscription list (title match). Unresolved documents keep the
        raw stream id — they stay searchable but cannot match feed or
        category filters (honest degradation, self-heals on next sync).
        """
        if doc.feedUrl.startswith(("http://", "https://")):
            return doc.feedUrl
        resolved = self._feed_title_to_url.get(doc.feedTitle)
        if resolved is not None:
            return resolved
        raw = doc.feedUrl.removeprefix("feed/")
        return raw if raw.startswith(("http://", "https://")) else doc.feedUrl

    async def _known_states(self) -> dict:
        rows = await self._store.known_states()
        states = {}
        for row in rows:
            states[row["item_id"]] = {
                "published_at": row["published_at"],
                "read": row["read"],
                "starred": row["starred"],
                "content_hash": row["content_hash"],
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


def match_positions(
    content: str, terms_folded: list[str], limit: int = 10
) -> list[dict[str, Any]]:
    """F072 命中定位：term 在 content_text 中的前 ≤limit 处偏移。

    复用 build_snippet 的 casefold 口径；按偏移升序合并全部 term 的
    命中（同一偏移去重）；无正文命中 → 空列表（仅标题命中 → 不启用
    定位条，诚实降级）。"""
    lowered = (content or "").casefold()
    found: list[tuple[int, str]] = []
    for term in terms_folded:
        if not term:
            continue
        start = 0
        hits_for_term = 0
        while hits_for_term < limit:
            index = lowered.find(term, start)
            if index < 0:
                break
            found.append((index, term))
            start = index + len(term)
            hits_for_term += 1
    seen_offsets: set[int] = set()
    result: list[dict[str, Any]] = []
    for offset, term in sorted(found):
        if offset in seen_offsets:
            continue
        seen_offsets.add(offset)
        result.append({"offset": offset, "term": term})
        if len(result) >= limit:
            break
    return result


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
