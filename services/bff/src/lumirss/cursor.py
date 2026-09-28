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

import hashlib
import json

from lumirss.opaque_ref import decode_opaque_ref, encode_opaque_ref

VIEWS = ("all", "unread", "starred")

_CURSOR_PREFIX = "c1."
_MAX_CURSOR_LENGTH = 2048


class InvalidCursor(ValueError):
    """Cursor has a wrong prefix, invalid characters, bad JSON/schema, or size."""


def scope_fingerprint(*parts: str | None) -> str:
    """Stable short fingerprint binding a keyset cursor to its query.

    FIX-363: a continuation token minted for one query (filters and/or
    account scope) must not be accepted by another query — the fingerprint
    rides inside the token and is re-checked at decode time.
    """

    joined = "\x1f".join(part or "" for part in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


class CursorScope:
    """The decoded cursor payload: continuation + the scope it belongs to.

    0011: scope 增加 source_type / category_id（可选，旧 c1 cursor 不携带
    → None，向后兼容）。它们与 feed_url 一样属于过滤 scope：cursor
    只能在自己的 scope 内翻页。FIX-363: account 绑定发放账户——跨账户
    重放一律在路由层拒绝（旧 token 无 account → 同样拒绝，失效即重翻）。
    """

    def __init__(
        self,
        continuation: str,
        view: str,
        feed_url: str | None,
        source_type: str | None = None,
        category_id: str | None = None,
        account: str | None = None,
    ) -> None:
        self.continuation = continuation
        self.view = view
        self.feed_url = feed_url
        self.source_type = source_type
        self.category_id = category_id
        self.account = account

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"CursorScope(view={self.view!r}, feed_url={self.feed_url!r}, "
            f"source_type={self.source_type!r}, category_id={self.category_id!r}, "
            f"account={self.account!r})"
        )

    def __eq__(self, other: object) -> bool:
        return (
            isinstance(other, CursorScope)
            and self.continuation == other.continuation
            and self.view == other.view
            and self.feed_url == other.feed_url
            and self.source_type == other.source_type
            and self.category_id == other.category_id
            and self.account == other.account
        )


def encode_cursor(
    continuation: str,
    view: str,
    feed_url: str | None,
    source_type: str | None = None,
    category_id: str | None = None,
    account: str | None = None,
) -> str:
    """Package a FreshRSS continuation + filter scope into an opaque cursor."""
    if view not in VIEWS:
        raise ValueError(f"view must be one of {VIEWS}.")
    if not continuation:
        raise ValueError("continuation must not be empty.")
    if not continuation.isdigit():
        raise ValueError("continuation must be a digit string.")
    payload = json.dumps(
        {
            "c": continuation,
            "v": view,
            "f": feed_url,
            "st": source_type,
            "cat": category_id,
            "a": account,
        },
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return encode_opaque_ref(_CURSOR_PREFIX, payload)


def decode_cursor(cursor: str) -> CursorScope:
    """Reverse of encode_cursor; raises InvalidCursor on bad input."""
    text = decode_opaque_ref(
        cursor,
        prefix=_CURSOR_PREFIX,
        max_length=_MAX_CURSOR_LENGTH,
        error_type=InvalidCursor,
        description="cursor",
    )
    try:
        payload = json.loads(text)
    except ValueError as exc:
        raise InvalidCursor("cursor payload is not valid JSON/UTF-8.") from exc
    if not isinstance(payload, dict) or not {"c", "v", "f"} <= set(payload.keys()):
        raise InvalidCursor("cursor payload has the wrong schema.")
    # 0011：合法键固定为 c/v/f/st/cat/a（未知键拒绝，st/cat/a 缺省 → None）
    if not set(payload.keys()) <= {"c", "v", "f", "st", "cat", "a"}:
        raise InvalidCursor("cursor payload has unknown fields.")
    continuation = payload["c"]
    view = payload["v"]
    feed_url = payload["f"]
    # 0011：新增 scope 字段（旧 cursor 缺省 → None，向后兼容）
    source_type = payload.get("st")
    category_id = payload.get("cat")
    account = payload.get("a")
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
    if account is not None and not isinstance(account, str):
        raise InvalidCursor("cursor account must be a string or null.")
    return CursorScope(
        continuation=continuation,
        view=view,
        feed_url=feed_url,
        source_type=source_type,
        category_id=category_id,
        account=account,
    )
