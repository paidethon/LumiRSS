"""LumiRSS entry models (0003/0004 scope).

One definition point for the entry API shapes: the adapter builds these
directly and the routes return them, so there is no second mapping layer.
"""

from pydantic import BaseModel


class EntryListItem(BaseModel):
    """One article in the entry list — never contains the body."""

    entryRef: str
    title: str
    feedTitle: str
    author: str | None = None
    url: str | None = None
    publishedAt: str | None = None
    read: bool
    starred: bool


class EntryPage(BaseModel):
    """Adapter-level page: items + the raw FreshRSS continuation.

    The adapter understands upstream continuations only; turning them into
    public nextCursor values (and back) is the route layer's job.
    """

    items: list[EntryListItem]
    upstreamContinuation: str | None


class EntryListResponse(BaseModel):
    """Envelope for GET /api/v1/entries."""

    items: list[EntryListItem]
    nextCursor: str | None


class EntryDetail(BaseModel):
    """One article with its body as plain text (contentText, never HTML)."""

    entryRef: str
    title: str
    feedTitle: str
    author: str | None = None
    url: str | None = None
    publishedAt: str | None = None
    read: bool
    starred: bool
    contentText: str
