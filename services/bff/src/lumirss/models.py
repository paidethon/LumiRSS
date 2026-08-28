"""LumiRSS entry models (0003 scope).

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


class EntryListResponse(BaseModel):
    """Envelope for GET /api/v1/entries (pagination fields come in 0004)."""

    items: list[EntryListItem]


class EntryDetail(BaseModel):
    """One article with its body as plain text (contentText, never HTML)."""

    entryRef: str
    title: str
    feedTitle: str
    author: str | None = None
    url: str | None = None
    publishedAt: str | None = None
    contentText: str
