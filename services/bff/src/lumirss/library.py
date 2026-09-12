"""Library domain store (phase2 M1) — canonical Lumi-owned content.

Owns the ``library_items`` identity table plus kind-specific payload
tables (currently ``library_bookmarks``). RSS entries are referenced via
``rss:`` ItemRefs and never copied here; FreshRSS stays the RSS-domain
source of truth. Every statement is one single-line inline literal with
bound params; optional filters are expressed as ``(? IS NULL OR …)`` so
no SQL text is ever built dynamically.
"""

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from lumirss.itemref import (
    LIBRARY_DOMAIN,
    RSS_DOMAIN,
    InvalidItemRef,
    new_library_uuid,
    parse_item_ref,
)
from lumirss.opaque_ref import decode_opaque_ref, encode_opaque_ref
from lumirss.search_library import LibrarySearchWriter
from lumirss.storage import Database
from lumirss.util import utc_now

_CURSOR_PREFIX = "c1lib."
_MAX_CURSOR_LENGTH = 512

_MAX_URL_LENGTH = 2048
_MAX_TITLE_LENGTH = 500
_MAX_NOTE_LENGTH = 4000
_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200

_ALLOWED_URL_SCHEMES = ("http://", "https://")


class BookmarkInvalid(ValueError):
    """Bookmark payload failed validation (scheme, length, shape)."""


class BookmarkNotFound(Exception):
    """No bookmark exists under the requested uuid."""


@dataclass(frozen=True)
class BookmarkView:
    """Wire shape of one bookmark (library domain only)."""

    ref: str
    item_type: str
    url: str | None
    rss_item_ref: str | None
    title: str
    note: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "itemType": self.item_type,
            "url": self.url,
            "rssItemRef": self.rss_item_ref,
            "title": self.title,
            "note": self.note,
            "createdAt": self.created_at,
        }


class LibraryStore:
    """Persistence for library_items + library_bookmarks."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._search = LibrarySearchWriter(db)

    # -- bookmarks ---------------------------------------------------------

    async def create_url_bookmark(
        self, url: str, title: str, note: str = ""
    ) -> tuple[BookmarkView, bool]:
        """Create (or idempotently return) a url bookmark.

        The unique url index makes duplicate creates converge on the
        existing row; the response carries the canonical uuid plus a
        ``created`` flag so imports can report new vs skipped honestly.
        """
        clean_url = _validate_bookmark_url(url)
        clean_title = _validate_bookmark_title(title)
        clean_note = _validate_bookmark_note(note)
        await self._db.migrate()
        existing = await self._find_by_url(clean_url)
        if existing is not None:
            return existing, False
        item_uuid = new_library_uuid()
        now = utc_now()
        await self._db.execute("INSERT INTO library_items (uuid, kind, created_at) VALUES (?, 'bookmark', ?)", (item_uuid, now))
        try:
            await self._db.execute("INSERT INTO library_bookmarks (item_uuid, item_type, url, rss_item_ref, title, note, created_at) VALUES (?, 'url', ?, NULL, ?, ?, ?)", (item_uuid, clean_url, clean_title, clean_note, now))
        except sqlite3.IntegrityError:
            # Lost a race against a concurrent create of the same URL:
            # converge on the unique index instead of failing.
            await self._db.execute("DELETE FROM library_items WHERE uuid = ? AND NOT EXISTS (SELECT 1 FROM library_bookmarks b WHERE b.item_uuid = ?)", (item_uuid, item_uuid))
            existing = await self._find_by_url(clean_url)
            if existing is None:
                raise
            return existing, False
        view = BookmarkView(
            ref=f"{LIBRARY_DOMAIN}:{item_uuid}",
            item_type="url",
            url=clean_url,
            rss_item_ref=None,
            title=clean_title,
            note=clean_note,
            created_at=now,
        )
        await self._search.upsert(
            ref=view.ref, kind="bookmark", title=view.title,
            body=view.note[:4000], url=view.url,
        )
        return view, True

    async def create_rss_bookmark(
        self, rss_item_ref: str, title: str, note: str = ""
    ) -> tuple[BookmarkView, bool]:
        """Bookmark an RSS entry by reference only — never copies the body."""
        try:
            parsed = parse_item_ref(rss_item_ref)
        except InvalidItemRef as exc:
            raise BookmarkInvalid(str(exc)) from exc
        if parsed.domain != RSS_DOMAIN:
            raise BookmarkInvalid("RSS bookmarks require an rss:<entryRef> ref.")
        clean_title = _validate_bookmark_title(title)
        clean_note = _validate_bookmark_note(note)
        await self._db.migrate()
        existing = await self._find_by_rss_ref(parsed.format())
        if existing is not None:
            return existing, False
        item_uuid = new_library_uuid()
        now = utc_now()
        await self._db.execute("INSERT INTO library_items (uuid, kind, created_at) VALUES (?, 'bookmark', ?)", (item_uuid, now))
        await self._db.execute("INSERT INTO library_bookmarks (item_uuid, item_type, url, rss_item_ref, title, note, created_at) VALUES (?, 'rss', NULL, ?, ?, ?, ?)", (item_uuid, parsed.format(), clean_title, clean_note, now))
        view = BookmarkView(
            ref=f"{LIBRARY_DOMAIN}:{item_uuid}",
            item_type="rss",
            url=None,
            rss_item_ref=parsed.format(),
            title=clean_title,
            note=clean_note,
            created_at=now,
        )
        await self._search.upsert(
            ref=view.ref, kind="bookmark", title=view.title,
            body=view.note[:4000], url=None,
        )
        return view, True

    async def get_bookmark(self, item_uuid: str) -> BookmarkView | None:
        await self._db.migrate()
        row = await self._db.fetch_one("SELECT b.item_uuid, b.item_type, b.url, b.rss_item_ref, b.title, b.note, b.created_at FROM library_bookmarks b WHERE b.item_uuid = ?", (item_uuid,))
        if row is None:
            return None
        return _bookmark_from_row(row)

    async def delete_bookmark(self, item_uuid: str) -> bool:
        """Delete a bookmark and its identity row; False when absent."""
        row = await self._db.fetch_one("SELECT uuid FROM library_items WHERE uuid = ? AND kind = 'bookmark'", (item_uuid,))
        if row is None:
            return False
        # library_items is the identity root; bookmarks cascade via FK.
        await self._db.execute("DELETE FROM library_items WHERE uuid = ?", (item_uuid,))
        await self._search.delete(f"{LIBRARY_DOMAIN}:{item_uuid}")
        return True

    async def update_bookmark(
        self, item_uuid: str, title: str | None, note: str | None
    ) -> BookmarkView:
        current = await self.get_bookmark(item_uuid)
        if current is None:
            raise BookmarkNotFound(item_uuid)
        new_title = (
            _validate_bookmark_title(title) if title is not None else current.title
        )
        new_note = (
            _validate_bookmark_note(note) if note is not None else current.note
        )
        await self._db.execute("UPDATE library_bookmarks SET title = ?, note = ? WHERE item_uuid = ?", (new_title, new_note, item_uuid))
        updated = await self.get_bookmark(item_uuid)
        assert updated is not None  # row existed one statement ago
        await self._search.upsert(
            ref=updated.ref, kind="bookmark", title=updated.title,
            body=updated.note[:4000], url=updated.url,
        )
        return updated

    async def list_bookmarks(
        self,
        *,
        cursor: str | None = None,
        limit: int = _DEFAULT_LIMIT,
        q: str | None = None,
    ) -> tuple[list[BookmarkView], str | None]:
        """Keyset-paged bookmark list, newest first; q filters title/url/note."""
        if limit < 1 or limit > _MAX_LIMIT:
            raise BookmarkInvalid(f"limit must be between 1 and {_MAX_LIMIT}.")
        await self._db.migrate()
        keyset = _decode_bookmark_cursor(cursor) if cursor else None
        needle = q.strip() if q else ""
        like = f"%{_escape_like(needle)}%" if needle else None
        key_created = keyset[0] if keyset else None
        key_uuid = keyset[1] if keyset else None
        rows = await self._db.fetch_all("SELECT b.item_uuid, b.item_type, b.url, b.rss_item_ref, b.title, b.note, b.created_at FROM library_bookmarks b WHERE (? IS NULL OR b.title LIKE ? ESCAPE '\\' OR b.url LIKE ? ESCAPE '\\' OR b.note LIKE ? ESCAPE '\\') AND (? IS NULL OR b.created_at < ? OR (b.created_at = ? AND b.item_uuid < ?)) ORDER BY b.created_at DESC, b.item_uuid DESC LIMIT ?", (like, like, like, like, key_created, key_created, key_created, key_uuid, limit + 1))
        has_more = len(rows) > limit
        rows = rows[:limit]
        items = [_bookmark_from_row(row) for row in rows]
        next_cursor = None
        if has_more and items:
            last = items[-1]
            next_cursor = _encode_bookmark_cursor(last.created_at, _uuid_of(last.ref))
        return items, next_cursor

    async def list_all_bookmarks(self) -> list[BookmarkView]:
        """Unpaged list for export (bounded by count guard at call site)."""
        await self._db.migrate()
        rows = await self._db.fetch_all("SELECT b.item_uuid, b.item_type, b.url, b.rss_item_ref, b.title, b.note, b.created_at FROM library_bookmarks b ORDER BY b.created_at ASC, b.item_uuid ASC")
        return [_bookmark_from_row(row) for row in rows]

    async def count_bookmarks(self) -> int:
        await self._db.migrate()
        row = await self._db.fetch_one("SELECT COUNT(*) AS n FROM library_bookmarks")
        return int(row["n"]) if row is not None else 0

    async def get_kind(self, item_uuid: str) -> str | None:
        """Kind of a library identity row, or None when absent."""
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT kind FROM library_items WHERE uuid = ?", (item_uuid,)
        )
        return str(row["kind"]) if row is not None else None

    async def get_library_item(self, item_uuid: str) -> BookmarkView | None:
        """Resolve a library:<uuid> ref to its view (bookmark kinds today)."""
        await self._db.migrate()
        row = await self._db.fetch_one("SELECT kind FROM library_items WHERE uuid = ?", (item_uuid,))
        if row is None:
            return None
        if row["kind"] != "bookmark":
            # Later gates add kinds; unknown kinds resolve to None here so
            # the source registry renders an honest placeholder, not a crash.
            return None
        return await self.get_bookmark(item_uuid)

    async def _find_by_url(self, url: str) -> BookmarkView | None:
        row = await self._db.fetch_one("SELECT b.item_uuid, b.item_type, b.url, b.rss_item_ref, b.title, b.note, b.created_at FROM library_bookmarks b WHERE b.url = ?", (url,))
        return _bookmark_from_row(row) if row is not None else None

    async def _find_by_rss_ref(self, rss_ref: str) -> BookmarkView | None:
        row = await self._db.fetch_one("SELECT b.item_uuid, b.item_type, b.url, b.rss_item_ref, b.title, b.note, b.created_at FROM library_bookmarks b WHERE b.rss_item_ref = ?", (rss_ref,))
        return _bookmark_from_row(row) if row is not None else None


def _uuid_of(library_ref: str) -> str:
    return parse_item_ref(library_ref).key


def _bookmark_from_row(row: sqlite3.Row) -> BookmarkView:
    item_uuid = str(row["item_uuid"])
    return BookmarkView(
        ref=f"{LIBRARY_DOMAIN}:{item_uuid}",
        item_type=str(row["item_type"]),
        url=row["url"],
        rss_item_ref=row["rss_item_ref"],
        title=str(row["title"]),
        note=str(row["note"]),
        created_at=str(row["created_at"]),
    )


def _validate_bookmark_url(url: str) -> str:
    if not isinstance(url, str) or not url.strip():
        raise BookmarkInvalid("Bookmark url must be a non-empty string.")
    clean = url.strip()
    if len(clean) > _MAX_URL_LENGTH:
        raise BookmarkInvalid("Bookmark url is too long.")
    if not clean.lower().startswith(_ALLOWED_URL_SCHEMES):
        raise BookmarkInvalid("Bookmark url must use http or https.")
    if any(ch.isspace() for ch in clean):
        raise BookmarkInvalid("Bookmark url must not contain whitespace.")
    return clean


def _validate_bookmark_title(title: str) -> str:
    if not isinstance(title, str):
        raise BookmarkInvalid("Bookmark title must be a string.")
    clean = title.strip()
    if not clean:
        raise BookmarkInvalid("Bookmark title must not be empty.")
    if len(clean) > _MAX_TITLE_LENGTH:
        raise BookmarkInvalid("Bookmark title is too long.")
    return clean


def _validate_bookmark_note(note: str) -> str:
    if not isinstance(note, str):
        raise BookmarkInvalid("Bookmark note must be a string.")
    if len(note) > _MAX_NOTE_LENGTH:
        raise BookmarkInvalid("Bookmark note is too long.")
    return note


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _encode_bookmark_cursor(created_at: str, item_uuid: str) -> str:
    payload = json.dumps([created_at, item_uuid], separators=(",", ":"))
    return encode_opaque_ref(_CURSOR_PREFIX, payload)


def _decode_bookmark_cursor(cursor: str) -> tuple[str, str]:
    try:
        payload = decode_opaque_ref(
            cursor,
            prefix=_CURSOR_PREFIX,
            max_length=_MAX_CURSOR_LENGTH,
            error_type=BookmarkInvalid,
            description="bookmark cursor",
        )
        created_at, item_uuid = json.loads(payload)
        if not isinstance(created_at, str) or not isinstance(item_uuid, str):
            raise BookmarkInvalid("bookmark cursor payload is not a key pair.")
        return created_at, item_uuid
    except json.JSONDecodeError as exc:
        raise BookmarkInvalid("bookmark cursor payload is not valid JSON.") from exc
