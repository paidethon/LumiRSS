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
# F29（2026-09 移动端专项）：高级条件的最大槽位。
_MAX_INTITLE_TERMS = 2
_MAX_EXCLUDE_TERMS = 2


def like_pattern(term: str) -> str:
    """Bind-time LIKE pattern; backslash-escape the LIKE wildcards."""
    escaped = (
        term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    )
    return "%" + escaped + "%"


# Parameter order: four term slots x three columns (title, content,
# author); then intitle slots x2 (guard + pattern); phrase x3 (guard +
# title + content); exclude slots x2 (guard + NOT LIKE x3); feed_url x2
# (value + NULL guard), category x2, unread guard, starred guard, from
# x2, to x2, keyset flag + keyset x3 (NULL disables pagination), limit.
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
    # F29 intitle：仅标题命中的词条（NULL = 该槽未用）。
    " AND (? IS NULL OR s.title LIKE ? ESCAPE '\\')"
    " AND (? IS NULL OR s.title LIKE ? ESCAPE '\\')"
    # F29 phrase：精确短语（按子串匹配标题或正文；NULL = 未用）。
    " AND (? IS NULL OR s.title LIKE ? ESCAPE '\\'"
    "      OR s.content_text LIKE ? ESCAPE '\\')"
    # F29 exclude：排除词（三个列都不得包含；NULL = 未用）。
    " AND (? IS NULL OR (s.title NOT LIKE ? ESCAPE '\\'"
    "      AND s.content_text NOT LIKE ? ESCAPE '\\'"
    "      AND s.author NOT LIKE ? ESCAPE '\\'))"
    " AND (? IS NULL OR (s.title NOT LIKE ? ESCAPE '\\'"
    "      AND s.content_text NOT LIKE ? ESCAPE '\\'"
    "      AND s.author NOT LIKE ? ESCAPE '\\'))"
    " AND (? IS NULL OR s.feed_url = ?)"
    " AND (? IS NULL OR EXISTS (SELECT 1 FROM search_feeds f"
    "      WHERE f.category_id = ? AND f.feed_url = s.feed_url))"
    " AND (? = 0 OR s.read = 0)"
    " AND (? = 0 OR s.starred = 1)"
    " AND (? IS NULL OR s.published_at >= ?)"
    " AND (? IS NULL OR s.published_at < ?)"
    " AND (? IS NULL OR s.published_at < ?"
    "      OR (s.published_at = ? AND s.item_id < ?))"
    # F017 has_summary：仅摘要维度（NULL = 不启用；1 = 有摘要；0 = 无摘要）
    " AND (? IS NULL OR (? = 1 AND s.content_text != '')"
    "      OR (? = 0 AND (s.content_text IS NULL OR s.content_text = '')))"
    " ORDER BY s.published_at DESC, s.item_id DESC LIMIT ?"
)


class SearchStore:
    """Read path for the derived search projection."""

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
        intitle_terms: list[str] | None = None,
        phrase: str | None = None,
        exclude_terms: list[str] | None = None,
        has_summary: bool | None = None,
    ) -> list[Any]:
        """One page of hits, newest first; limit+1 rows detect hasMore.

        F29 高级条件（全部可选、可组合）：``intitle_terms`` 仅标题命中；
        ``phrase`` 精确短语（子串）；``exclude_terms`` 全列排除。
        """
        params: list = []
        for term in terms:
            pattern = like_pattern(term)
            params.extend([pattern, pattern, pattern])
        # 未用的基础词条槽 = 匹配一切（AND 上无害；与既有语义一致）。
        empty = like_pattern("")
        while len(params) < 3 * _MAX_SEARCH_TERMS:
            params.extend([empty, empty, empty])
        # intitle 槽（NULL 关闭未用的槽位）。
        intitle = list(intitle_terms or [])[:_MAX_INTITLE_TERMS]
        while len(intitle) < _MAX_INTITLE_TERMS:
            intitle.append("")
        for term in intitle:
            if term:
                params.extend([like_pattern(term), like_pattern(term)])
            else:
                params.extend([None, None])
        # phrase 槽。
        if phrase:
            pattern = like_pattern(phrase)
            params.extend([pattern, pattern, pattern])
        else:
            params.extend([None, None, None])
        # exclude 槽。
        exclude = list(exclude_terms or [])[:_MAX_EXCLUDE_TERMS]
        while len(exclude) < _MAX_EXCLUDE_TERMS:
            exclude.append("")
        for term in exclude:
            if term:
                pattern = like_pattern(term)
                params.extend([pattern, pattern, pattern, pattern])
            else:
                params.extend([None, None, None, None])
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
        # F017：has_summary 三槽（维度开关 + 真/假分支；位于 keyset 之后）
        params.extend([has_summary, has_summary, has_summary])
        params.append(limit + 1)
        return await self._db.fetch_all(_SQL_SEARCH, tuple(params))

    async def count(self) -> int:
        row = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM search_entries"
        )
        return int(row["n"]) if row else 0

    async def known_states(self) -> list[Any]:
        return await self._db.fetch_all(
            "SELECT item_id, published_at, read, starred, content_hash FROM search_entries"
        )

    async def entry_row_by_ref(self, entry_ref: str) -> Any | None:
        """One projection row by entryRef — the resolve path's cheap leg
        (card/list resolvers hit this before falling back to FreshRSS)."""
        await self._db.migrate()
        return await self._db.fetch_one(
            "SELECT entry_ref, title, feed_title, feed_url, author, url, published_at, read, starred, content_text FROM search_entries WHERE entry_ref = ?",
            (entry_ref,),
        )

    async def meta_get(self, key: str) -> str | None:
        row = await self._db.fetch_one(
            "SELECT value FROM search_meta WHERE key = ?", (key,)
        )
        return row["value"] if row else None
