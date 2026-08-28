"""Cursor — LumiRSS's opaque, URL-safe pagination cursor.

Format: ``c1.`` + base64url(utf-8 compact JSON payload) without ``=``
padding. The payload carries the FreshRSS continuation plus the filter
scope (view + feedUrl) it belongs to, so a cursor can be replayed on its
own and must not be mixed with a different view/feedUrl.

Encoding is NOT encryption, and a cursor is neither authentication nor
authorization: it is a reversible, versioned packaging of the upstream
continuation so clients never depend on FreshRSS shapes. Clients must
treat it as an opaque string.
"""

import base64
import json

VIEWS = ("all", "unread", "starred")

_CURSOR_PREFIX = "c1."
_MAX_CURSOR_LENGTH = 2048
_BASE64URL_ALPHABET = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
)


class InvalidCursor(ValueError):
    """Cursor has a wrong prefix, invalid characters, bad JSON/schema, or size."""


class CursorScope:
    """The decoded cursor payload: continuation + the scope it belongs to."""

    def __init__(self, continuation: str, view: str, feed_url: str | None) -> None:
        self.continuation = continuation
        self.view = view
        self.feed_url = feed_url

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return f"CursorScope(view={self.view!r}, feed_url={self.feed_url!r})"

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, CursorScope)
            and self.continuation == other.continuation
            and self.view == other.view
            and self.feed_url == other.feed_url
        )


def encode_cursor(continuation: str, view: str, feed_url: str | None) -> str:
    """Package a FreshRSS continuation + filter scope into an opaque cursor."""
    if view not in VIEWS:
        raise ValueError(f"view must be one of {VIEWS}.")
    if not continuation:
        raise ValueError("continuation must not be empty.")
    if not continuation.isdigit():
        raise ValueError("continuation must be a digit string.")
    payload = json.dumps(
        {"c": continuation, "v": view, "f": feed_url},
        separators=(",", ":"),
        ensure_ascii=False,
    )
    encoded = base64.urlsafe_b64encode(payload.encode("utf-8"))
    return _CURSOR_PREFIX + encoded.decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> CursorScope:
    """Reverse of encode_cursor; raises InvalidCursor on bad input."""
    if len(cursor) > _MAX_CURSOR_LENGTH:
        raise InvalidCursor("cursor is too long.")
    if not cursor.startswith(_CURSOR_PREFIX):
        raise InvalidCursor("cursor must start with 'c1.'.")
    raw = cursor[len(_CURSOR_PREFIX):]
    if not raw or not _BASE64URL_ALPHABET.issuperset(raw):
        raise InvalidCursor("cursor payload is not valid base64url.")
    padded = raw + "=" * (-len(raw) % 4)
    try:
        text = base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
        payload = json.loads(text)
    except (ValueError, UnicodeDecodeError) as exc:
        raise InvalidCursor("cursor payload is not valid JSON/UTF-8.") from exc
    if not isinstance(payload, dict) or set(payload.keys()) != {"c", "v", "f"}:
        raise InvalidCursor("cursor payload has the wrong schema.")
    continuation = payload["c"]
    view = payload["v"]
    feed_url = payload["f"]
    if not isinstance(continuation, str) or not continuation.isdigit():
        raise InvalidCursor("cursor continuation must be a non-empty digit string.")
    if view not in VIEWS:
        raise InvalidCursor("cursor view is not a known view.")
    if feed_url is not None and not isinstance(feed_url, str):
        raise InvalidCursor("cursor feedUrl must be a string or null.")
    return CursorScope(continuation=continuation, view=view, feed_url=feed_url)
