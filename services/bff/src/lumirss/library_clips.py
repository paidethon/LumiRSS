"""Web clip store (phase2 M2, recovery P0-03) — server-derived content.

A clip is a full LibraryItem (kind='clip'): the one kind that carries an
article body inside Lumi SQLite. Since the phase2 recovery the body is
produced by the server-side pipeline (fetch → extract → sanitize, see
clip_fetch.fetch_extract_sanitize) — the create API no longer accepts or
stores client-submitted HTML. Every multi-row write (library_items +
library_clips + the search_library projection) runs in ONE transaction
(db_tx.transaction) so a crash can never leave an orphan identity row or
an unsearchable clip. All SQL is single-line inline literals with bound
params; no UPSERT syntax (explicit SELECT-then-INSERT/UPDATE).
"""

import json
import sqlite3
from dataclasses import dataclass

from lumirss.clip_fetch import ClipForbidden
from lumirss.db_tx import transaction
from lumirss.itemref import new_library_uuid
from lumirss.opaque_ref import decode_opaque_ref, encode_opaque_ref
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_URL_LENGTH = 2048
_MAX_TITLE_LENGTH = 500
_MAX_BYLINE_LENGTH = 200
_MAX_HTML_BYTES = 2 * 1024 * 1024
_MAX_TEXT_BYTES = 512 * 1024
_DEFAULT_LIMIT = 50
_MAX_LIMIT = 200

_CURSOR_PREFIX = "c1clip."


class ClipInvalid(ValueError):
    """Clip payload failed validation (url, lengths, missing body)."""


class ClipNotFound(Exception):
    """No clip exists under the requested uuid."""


@dataclass(frozen=True)
class ClipView:
    ref: str
    url: str
    title: str
    byline: str | None
    content_html: str
    content_text: str
    fetched_at: str
    created_at: str

    def to_dict(self, *, with_content: bool = False) -> dict:
        payload = {
            "ref": self.ref,
            "url": self.url,
            "title": self.title,
            "byline": self.byline,
            "fetchedAt": self.fetched_at,
            "createdAt": self.created_at,
        }
        if with_content:
            payload["contentHtml"] = self.content_html
            payload["contentText"] = self.content_text
        return payload


class ClipStore:
    """Persistence for library_items(kind='clip') + search projection."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create_clip(
        self,
        *,
        url: str,
        title: str,
        content_html: str,
        content_text: str,
        byline: str | None = None,
        fetched_at: str | None = None,
    ) -> tuple[ClipView, bool]:
        """Store server-derived clip content; duplicate urls converge."""
        await self._db.migrate()
        clean_url = _validate_url(url)
        clean_title = _validate_title(title)
        clean_html = _validate_html(content_html)
        clean_text = _validate_text(content_text)
        clean_byline = _validate_byline(byline)
        now = utc_now()
        fetched = fetched_at or now
        existing = await self._find_by_url(clean_url)
        if existing is not None:
            return existing, False
        item_uuid = new_library_uuid()

        def _tx(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO library_items (uuid, kind, created_at) VALUES (?, 'clip', ?)",
                (item_uuid, now),
            )
            conn.execute(
                "INSERT INTO library_clips (item_uuid, url, title, byline, content_html, content_text, fetched_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    item_uuid,
                    clean_url,
                    clean_title,
                    clean_byline,
                    clean_html,
                    clean_text,
                    fetched,
                    now,
                ),
            )
            ref = f"library:{item_uuid}"
            row = conn.execute(
                "SELECT ref FROM search_library WHERE ref = ?", (ref,)
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO search_library (ref, kind, title, body, url, updated_at) VALUES (?, 'clip', ?, ?, ?, ?)",
                    (ref, clean_title, clean_text[:4000], clean_url, now),
                )
            else:
                conn.execute(
                    "UPDATE search_library SET kind = 'clip', title = ?, body = ?, url = ?, updated_at = ? WHERE ref = ?",
                    (clean_title, clean_text[:4000], clean_url, now, ref),
                )

        try:
            await transaction(self._db, _tx)
        except sqlite3.IntegrityError:
            existing = await self._find_by_url(clean_url)
            if existing is None:
                raise
            return existing, False
        view = await self.get_clip(item_uuid)
        assert view is not None
        return view, True

    async def get_clip(self, item_uuid: str) -> ClipView | None:
        await self._db.migrate()
        row = await self._db.fetch_one("SELECT item_uuid, url, title, byline, content_html, content_text, fetched_at, created_at FROM library_clips WHERE item_uuid = ?", (item_uuid,))
        if row is None:
            return None
        return _clip_from_row(row)

    async def delete_clip(self, item_uuid: str) -> bool:
        """Delete the identity row (cascades the clip) + projection atomically."""
        await self._db.migrate()

        def _tx(conn: sqlite3.Connection) -> bool:
            cursor = conn.execute(
                "DELETE FROM library_items WHERE uuid = ? AND kind = 'clip'",
                (item_uuid,),
            )
            if cursor.rowcount == 0:
                return False
            conn.execute(
                "DELETE FROM search_library WHERE ref = ?",
                (f"library:{item_uuid}",),
            )
            return True

        return await transaction(self._db, _tx)

    async def list_clips(
        self,
        *,
        cursor: str | None = None,
        limit: int = _DEFAULT_LIMIT,
    ) -> tuple[list[ClipView], str | None]:
        if limit < 1 or limit > _MAX_LIMIT:
            raise ClipInvalid(f"limit must be between 1 and {_MAX_LIMIT}.")
        await self._db.migrate()
        keyset = _decode_cursor(cursor) if cursor else None
        key_created = keyset[0] if keyset else None
        key_uuid = keyset[1] if keyset else None
        rows = await self._db.fetch_all(
            "SELECT item_uuid, url, title, byline, content_html, content_text, fetched_at, created_at FROM library_clips WHERE (? IS NULL OR created_at < ? OR (created_at = ? AND item_uuid < ?)) ORDER BY created_at DESC, item_uuid DESC LIMIT ?",
            (key_created, key_created, key_created, key_uuid, limit + 1),
        )
        has_more = len(rows) > limit
        rows = rows[:limit]
        items = [_clip_from_row(row) for row in rows]
        next_cursor = None
        if has_more and items:
            last = items[-1]
            next_cursor = _encode_cursor(last.created_at, last.ref.split(":", 1)[1])
        return items, next_cursor

    async def count_clips(self) -> int:
        await self._db.migrate()
        row = await self._db.fetch_one("SELECT COUNT(*) AS n FROM library_clips")
        return int(row["n"]) if row is not None else 0

    async def _find_by_url(self, url: str) -> ClipView | None:
        row = await self._db.fetch_one("SELECT item_uuid, url, title, byline, content_html, content_text, fetched_at, created_at FROM library_clips WHERE url = ?", (url,))
        return _clip_from_row(row) if row is not None else None


def _clip_from_row(row: sqlite3.Row) -> ClipView:
    item_uuid = str(row["item_uuid"])
    byline = row["byline"]
    return ClipView(
        ref=f"library:{item_uuid}",
        url=str(row["url"]),
        title=str(row["title"]),
        byline=str(byline) if byline is not None else None,
        content_html=str(row["content_html"]),
        content_text=str(row["content_text"]),
        fetched_at=str(row["fetched_at"]),
        created_at=str(row["created_at"]),
    )


def _validate_url(url: str) -> str:
    if not isinstance(url, str) or not url.strip():
        raise ClipForbidden("Clip url must be an http(s) URL.", "invalid_url")
    clean = url.strip()
    if len(clean) > _MAX_URL_LENGTH:
        raise ClipForbidden("Clip url is too long.", "invalid_url")
    if not clean.lower().startswith(("http://", "https://")):
        raise ClipForbidden("Clip url must use http or https.", "invalid_url")
    if any(ch.isspace() for ch in clean):
        raise ClipForbidden("Clip url must not contain whitespace.", "invalid_url")
    return clean


def _validate_title(title: str) -> str:
    if not isinstance(title, str) or not title.strip():
        raise ClipInvalid("Clip title must not be empty.")
    clean = title.strip()
    if len(clean) > _MAX_TITLE_LENGTH:
        raise ClipInvalid("Clip title is too long.")
    return clean


def _validate_byline(byline: str | None) -> str | None:
    if byline is None:
        return None
    if not isinstance(byline, str):
        raise ClipInvalid("Clip byline must be a string.")
    clean = byline.strip()
    if not clean:
        return None
    if len(clean) > _MAX_BYLINE_LENGTH:
        raise ClipInvalid("Clip byline is too long.")
    return clean


def _validate_html(content_html: str) -> str:
    """Server-sanitized content only: length-checked, never re-cleaned
    here (the sanitizer in article_sanitize is the cleaning authority)."""
    if not isinstance(content_html, str) or not content_html.strip():
        raise ClipInvalid("Clip contentHtml must not be empty.")
    if len(content_html.encode("utf-8")) > _MAX_HTML_BYTES:
        raise ClipInvalid("Clip contentHtml exceeds the 2MB limit.")
    return content_html


def _validate_text(content_text: str) -> str:
    if not isinstance(content_text, str):
        raise ClipInvalid("Clip contentText must be a string.")
    if len(content_text.encode("utf-8")) > _MAX_TEXT_BYTES:
        raise ClipInvalid("Clip contentText exceeds the 512KB limit.")
    return content_text


def _encode_cursor(created_at: str, item_uuid: str) -> str:
    payload = json.dumps([created_at, item_uuid], separators=(",", ":"))
    return encode_opaque_ref(_CURSOR_PREFIX, payload)


def _decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        payload = decode_opaque_ref(
            cursor,
            prefix=_CURSOR_PREFIX,
            max_length=512,
            error_type=ClipInvalid,
            description="clip cursor",
        )
        created_at, item_uuid = json.loads(payload)
        if not isinstance(created_at, str) or not isinstance(item_uuid, str):
            raise ClipInvalid("clip cursor payload is not a key pair.")
        return created_at, item_uuid
    except json.JSONDecodeError as exc:
        raise ClipInvalid("clip cursor payload is not valid JSON.") from exc
