"""Inbox push sources (0021).

Two audiences, one router:

- user routes (session): manage connectors and read what they pushed —
  GET /api/v1/inbox/sources, POST /api/v1/inbox/sources,
  DELETE /api/v1/inbox/sources/{uuid}, GET /api/v1/inbox/items,
  DELETE /api/v1/inbox/items/{uuid};
- machine route (bearer): POST /api/v1/inbox/ingest/{uuid} — external
  scripts/agents push JSON items that become Lumi-owned ``api_item``
  content (ADR 0004). The route IS the auth boundary: the per-source
  bearer secret is compared in constant time and NEVER logged, mirroring
  the mail bridge ingest. The two auth middlewares defer bearer-bearing
  requests on this prefix (see middleware.py).

Everything pushed is untrusted input: unknown fields are rejected,
HTML is sanitized server-side before storage, and the final render
boundary stays DOMPurify in the browser.
"""

import base64
import contextlib
import json
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import urlparse

from fastapi import APIRouter, Request

from lumirss.cursor import InvalidCursor
from lumirss.errors import InvalidInboxPayload
from lumirss.inbox_store import (
    InboxItemNotFound,
    InboxSourceNotFound,
    InboxStore,
)
from lumirss.models import (
    InboxIngestItem,
    InboxIngestResult,
    InboxItemList,
    InboxItemRow,
    InboxSource,
    InboxSourceCreate,
    InboxSourceCreated,
)

from ..deps import _get_inbox_store, _rag_mark_stale

router = APIRouter()

_DEFAULT_LIMIT = 20
_MAX_CATEGORIES = 24
_MAX_CATEGORY_LENGTH = 64
_CURSOR_PREFIX = "inbox1."
_MAX_CURSOR_LENGTH = 512


class _TextSink(HTMLParser):
    """Collect text out of already-sanitized HTML (stdlib parser)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def text(self) -> str:
        return " ".join(" ".join(self._parts).split())


def _html_to_text(html: str) -> str:
    sink = _TextSink()
    try:
        sink.feed(html)
    except Exception:  # noqa: BLE001 — text derivation must never 500
        return ""
    return sink.text()


def _validate_optional_url(url: str | None) -> str | None:
    """Inbox URLs are stored for display/open, never fetched server-side —
    only a scheme+host sanity check applies (no javascript: links)."""
    if url is None:
        return None
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise InvalidInboxPayload("url must be an absolute http(s) URL.")
    return url


def _validate_published_at(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InvalidInboxPayload(
            "publishedAt must be an ISO-8601 timestamp."
        ) from exc
    return value


def _clean_categories(categories: list[str]) -> list[str]:
    cleaned: list[str] = []
    for raw in categories[:_MAX_CATEGORIES]:
        item = raw.strip()[:_MAX_CATEGORY_LENGTH]
        if item and item not in cleaned:
            cleaned.append(item)
    return cleaned


def _encode_cursor(created_at: str, item_uuid: str) -> str:
    payload = json.dumps({"k": created_at, "u": item_uuid}).encode()
    return _CURSOR_PREFIX + base64.urlsafe_b64encode(payload).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        raw = cursor.removeprefix(_CURSOR_PREFIX)
        padded = raw + "=" * (-len(raw) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()))
        return str(data["k"]), str(data["u"])
    except Exception as exc:
        raise InvalidCursor("Invalid inbox cursor.") from exc


@router.post("/api/v1/inbox/sources", response_model=InboxSourceCreated)
async def create_inbox_source(
    request: Request, body: InboxSourceCreate
) -> InboxSourceCreated:
    """Create an inbox connector. The bearer secret is returned exactly
    once; it cannot be retrieved afterwards."""
    store = _get_inbox_store(request)
    created = await store.create_source(body.name.strip())
    return InboxSourceCreated(
        uuid=created["uuid"],
        name=created["name"],
        secret=created["secret"],
        ingestPath=f"/api/v1/inbox/ingest/{created['uuid']}",
        createdAt=created["createdAt"],
    )


@router.get("/api/v1/inbox/sources", response_model=list[InboxSource])
async def list_inbox_sources(request: Request) -> list[InboxSource]:
    store = _get_inbox_store(request)
    rows = await store.list_sources()
    return [
        InboxSource(
            uuid=row["uuid"],
            name=row["name"],
            enabled=row["enabled"],
            lastSuccessAt=row["lastSuccessAt"],
            lastError=row["lastError"],
            createdAt=row["createdAt"],
        )
        for row in rows
    ]


@router.delete("/api/v1/inbox/sources/{source_uuid}")
async def delete_inbox_source(request: Request, source_uuid: str) -> dict:
    """Delete a connector and every item it pushed (identity, payload and
    search projections in one operation; RAG invalidation best-effort)."""
    store = _get_inbox_store(request)
    deleted_refs = await store.delete_source(source_uuid)
    if deleted_refs is None:
        raise InboxSourceNotFound(source_uuid)
    if deleted_refs:
        await _rag_mark_stale(request, deleted_refs)
    return {"deleted": True, "items": len(deleted_refs)}


@router.post("/api/v1/inbox/ingest/{source_uuid}", response_model=InboxIngestResult)
async def ingest_inbox_item(
    source_uuid: str, request: Request, item: InboxIngestItem
) -> InboxIngestResult:
    """Machine-to-machine push (bearer secret, constant-time compare).

    Idempotent on (source, guid): replaying an item returns ``exists``
    with 200 instead of duplicating. Unknown source and wrong secret are
    indistinguishable (404) so the endpoint does not leak existence."""
    store: InboxStore = _get_inbox_store(request)
    auth = request.headers.get("authorization", "")
    supplied = auth[7:] if auth.lower().startswith("bearer ") else ""
    source = await store.get_source(source_uuid)
    if source is None or not store.secrets_match(supplied, source["secret"]):
        raise InboxSourceNotFound(source_uuid)

    try:
        url = _validate_optional_url(item.url)
        published_at = _validate_published_at(item.publishedAt)
        content_html = ""
        content_text = (item.content or "").strip()
        if item.contentHtml:
            from lumirss.article_sanitize import sanitize_html

            content_html = sanitize_html(item.contentHtml)
            if not content_text:
                content_text = _html_to_text(content_html)
        title = (item.title or item.guid).strip()[:512]

        status, ref = await store.ingest(
            source,
            guid=item.guid.strip(),
            title=title,
            url=url,
            author=(item.author or "").strip() or None,
            content_html=content_html,
            content_text=content_text[:200_000],
            published_at=published_at,
            categories=_clean_categories(item.categories),
        )
    except Exception as exc:
        # Connector health stays honest (Q-P2-03): a rejected or failed
        # push surfaces as lastError in the source registry instead of a
        # permanently green connector. Recording is best-effort — never
        # mask the original failure.
        with contextlib.suppress(Exception):
            await store.record_error(
                source_uuid,
                str(exc) if isinstance(exc, InvalidInboxPayload) else "ingest failed",
            )
        raise
    return InboxIngestResult(status=status, ref=ref)


@router.get("/api/v1/inbox/items", response_model=InboxItemList)
async def list_inbox_items(
    request: Request,
    cursor: str | None = None,
    limit: int = _DEFAULT_LIMIT,
    sourceUuid: str | None = None,
) -> InboxItemList:
    """Newest-first page of bare ItemRef rows; the web client renders them
    through POST /api/v1/resolve so display stays registry-owned."""
    if limit < 1 or limit > 50:
        raise InvalidInboxPayload("limit must be between 1 and 50.")
    store = _get_inbox_store(request)
    keyset = _decode_cursor(cursor) if cursor is not None else None
    rows, has_more = await store.list_items(
        source_uuid=sourceUuid, keyset=keyset, limit=limit
    )
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = _encode_cursor(last["createdAt"], _uuid_of(last["ref"]))
    return InboxItemList(
        items=[
            InboxItemRow(
                ref=row["ref"],
                createdAt=row["createdAt"],
                sourceUuid=row["sourceUuid"],
            )
            for row in rows
        ],
        nextCursor=next_cursor,
        hasMore=has_more,
    )


@router.delete("/api/v1/inbox/items/{item_uuid}")
async def delete_inbox_item(request: Request, item_uuid: str) -> dict:
    store = _get_inbox_store(request)
    ref = await store.delete_item(item_uuid)
    if ref is None:
        raise InboxItemNotFound(item_uuid)
    await _rag_mark_stale(request, [ref])
    return {"deleted": True}


def _uuid_of(ref: str) -> str:
    return ref.removeprefix("library:")
