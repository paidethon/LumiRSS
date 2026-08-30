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
    """The decoded cursor payload: continuation + the scope it belongs to.

    0011: scope 增加 source_type / category_id（可选，旧 c1 cursor 不携带
    → None，向后兼容）。它们与 feed_url 一样属于过滤 scope：cursor
    只能在自己的 scope 内翻页。
    """

    def __init__(
        self,
        continuation: str,
        view: str,
        feed_url: str | None,
        source_type: str | None = None,
        category_id: str | None = None,
    ) -> None:
        self.continuation = continuation
        self.view = view
        self.feed_url = feed_url
        self.source_type = source_type
        self.category_id = category_id

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"CursorScope(view={self.view!r}, feed_url={self.feed_url!r}, "
            f"source_type={self.source_type!r}, category_id={self.category_id!r})"
        )

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, CursorScope)
            and self.continuation == other.continuation
            and self.view == other.view
            and self.feed_url == other.feed_url
            and self.source_type == other.source_type
            and self.category_id == other.category_id
        )


def encode_cursor(
    continuation: str,
    view: str,
    feed_url: str | None,
    source_type: str | None = None,
    category_id: str | None = None,
) -> str:
    """Package a FreshRSS continuation + filter scope into an opaque cursor."""
    if view not in VIEWS:
        raise ValueError(f"view must be one of {VIEWS}.")
    if not continuation:
        raise ValueError("continuation must not be empty.")
    if not continuation.isdigit():
        raise ValueError("continuation must be a digit string.")
    payload = json.dumps(
        {"c": continuation, "v": view, "f": feed_url, "st": source_type, "cat": category_id},
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
    if not isinstance(payload, dict) or not {"c", "v", "f"} <= set(payload.keys()):
        raise InvalidCursor("cursor payload has the wrong schema.")
    # 0011：合法键固定为 c/v/f/st/cat（未知键拒绝，st/cat 缺省 → None）
    if not set(payload.keys()) <= {"c", "v", "f", "st", "cat"}:
        raise InvalidCursor("cursor payload has unknown fields.")
    continuation = payload["c"]
    view = payload["v"]
    feed_url = payload["f"]
    # 0011：新增 scope 字段（旧 cursor 缺省 → None，向后兼容）
    source_type = payload.get("st")
    category_id = payload.get("cat")
    if not isinstance(continuation, str) or not continuation.isdigit():
        raise InvalidCursor("cursor continuation must be a non-empty digit string.")
    if view not in VIEWS:
        raise InvalidCursor("cursor view is not a known view.")
    if feed_url is not None and not isinstance(feed_url, str):
        raise InvalidCursor("cursor feedUrl must be a string or null.")
    if source_type is not None and not isinstance(source_type, str):
        raise InvalidCursor("cursor sourceType must be a string or null.")
    if category_id is not None and not isinstance(category_id, str):
        raise InvalidCursor("cursor categoryId must be a string or null.")
    return CursorScope(
        continuation=continuation,
        view=view,
        feed_url=feed_url,
        source_type=source_type,
        category_id=category_id,
    )
