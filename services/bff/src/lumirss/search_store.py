"""Search projection storage — read path and metadata.

This module is the only place search queries touch SQLite. The statement
is a static literal with bound parameters; the caller passes plain
values. LIKE patterns are built by :func:`like_pattern` and bound as
VALUES — the ``ESCAPE '\\'`` clause makes %, _ and \\ typed by the user
match literally. Unused term slots bind the match-nothing empty pattern.
"""

from typing import Any

from .storage import Database

_MAX_SEARCH_TERMS = 4


def like_pattern(term: str) -> str:
    """Bind-time LIKE pattern; backslash-escape the LIKE wildcards."""
    escaped = (
        term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )
    return "%" + escaped + "%"


# Parameter order: four term slots x three columns (title, content,
# author); then feed_url x2 (value + NULL guard), category x2, unread
# guard, starred guard, from x2, to x2, keyset flag + keyset x3 (NULL
# disables pagination), limit.
_SQL_SEARCH = (
    "SELECT s.item_id, s.entry_ref, s.title, s.feed_title, s.feed_url,"
    " s.author, s.url, s.published_at, s.read, s.starred,"
    " s.content_text AS content_text"
    " FROM search_entries s"
    " WHERE (s.title LIKE ? ESCAPE '\\'"
    "     OR s.content_text LIKE ? ESCAPE '\\'"
    "     OR s.author LIKE ? ESCAPE '\\')"
    "   AND (s.title LIKE ? ESCAPE '\\'"
    "     OR s.content_text LIKE ? ESCAPE '\\'"
    "     OR s.author LIKE ? ESCAPE '\\')"
    "   AND (s.title LIKE ? ESCAPE '\\'"
    "     OR s.content_text LIKE ? ESCAPE '\\'"
    "     OR s.author LIKE ? ESCAPE '\\')"
    "   AND (s.title LIKE ? ESCAPE '\\'"
    "     OR s.content_text LIKE ? ESCAPE '\\'"
    "     OR s.author LIKE ? ESCAPE '\\')"
    " AND (? IS NULL OR s.feed_url = ?)"
    " AND (? IS NULL OR EXISTS (SELECT 1 FROM search_feeds f"
    "      WHERE f.category_id = ? AND f.feed_url = s.feed_url))"
    " AND (? = 0 OR s.read = 0)"
    " AND (? = 0 OR s.starred = 1)"
    " AND (? IS NULL OR s.published_at >= ?)"
    " AND (? IS NULL OR s.published_at < ?)"
    " AND (? IS NULL OR s.published_at < ?"
    "      OR (s.published_at = ? AND s.item_id < ?))"
    " ORDER BY s.published_at DESC, s.item_id DESC LIMIT ?"
)


class SearchStore:
    """Read path and metadata for the derived search projection."""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def query(
        self,
        *,
        terms: list[str],
        feed_url: str | None,
        category_id: str | None,
        unread_only: bool,
        starred_only: bool,
        published_from: str | None,
        published_to: str | None,
        keyset: tuple[str, str] | None,
        limit: int,
    ) -> list[Any]:
        """One page of hits, newest first; limit+1 rows detect hasMore."""
        params: list = []
        for term in terms:
            pattern = like_pattern(term)
            params.extend([pattern, pattern, pattern])
        empty = like_pattern("")
        while len(params) < 3 * _MAX_SEARCH_TERMS:
            params.extend([empty, empty, empty])
        params.extend(
            [
                feed_url,
                feed_url,
                category_id,
                category_id,
                int(unread_only),
                int(starred_only),
                published_from,
                published_from,
                published_to,
                published_to,
            ]
        )
        if keyset is not None:
            params.extend([1, keyset[0], keyset[0], keyset[1]])
        else:
            params.extend([None, None, None, None])
        params.append(limit + 1)
        return await self._db.fetch_all(_SQL_SEARCH, tuple(params))

    async def count(self) -> int:
        row = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM search_entries"
        )
        return int(row["n"]) if row else 0

    async def known_states(self) -> list[Any]:
        return await self._db.fetch_all(
            "SELECT item_id, published_at, read, starred FROM search_entries"
        )

    async def meta_get(self, key: str) -> str | None:
        row = await self._db.fetch_one(
            "SELECT value FROM search_meta WHERE key = ?", (key,)
        )
        return row["value"] if row else None
