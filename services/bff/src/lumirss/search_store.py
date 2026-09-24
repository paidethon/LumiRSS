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


def _filter_params(
    *,
    terms: list[str],
    intitle_terms: list[str] | None,
    phrase: str | None,
    exclude_terms: list[str] | None,
    feed_url: str | None,
    category_id: str | None,
    unread_only: bool,
    starred_only: bool,
    published_from: str | None,
    published_to: str | None,
    has_summary: bool | None,
) -> list:
    """_SQL_DIST_* 的绑定参数（与 _SQL_DIST_WHERE 槽位顺序一一对应；
    未用槽位的关闭方式与 query() 完全一致）。"""
    params: list = []
    for term in terms:
        pattern = like_pattern(term)
        params.extend([pattern, pattern, pattern])
    empty = like_pattern("")
    while len(params) < 3 * _MAX_SEARCH_TERMS:
        params.extend([empty, empty, empty])
    intitle = list(intitle_terms or [])[:_MAX_INTITLE_TERMS]
    while len(intitle) < _MAX_INTITLE_TERMS:
        intitle.append("")
    for term in intitle:
        if term:
            params.extend([like_pattern(term), like_pattern(term)])
        else:
            params.extend([None, None])
    if phrase:
        pattern = like_pattern(phrase)
        params.extend([pattern, pattern, pattern])
    else:
        params.extend([None, None, None])
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
    params.extend([has_summary, has_summary, has_summary])
    return params


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

# ---------------------------------------------------------------------------
# N145 来源内搜索分布：与 _SQL_SEARCH 相同的过滤链（同词同条件、同绑定
# 口径，但无 keyset/分页），聚合在 SQL 内完成（GROUP BY + COUNT）——
# 浏览器只收到每来源/每日计数，绝不搬运正文。
# 语句为模块级静态字面量的组合（无任何用户输入拼接）；参数顺序与
# _filter_params 一致：词条 x3 → intitle x2 → phrase x3 → exclude x2 槽
# → feed x2 → category x2 → unread → starred → from x2 → to x2
# → has_summary x3（days 额外尾部两个日期界）。
# ---------------------------------------------------------------------------

_SQL_DIST_WHERE = (
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
    " AND (? IS NULL OR s.title LIKE ? ESCAPE '\\')"
    " AND (? IS NULL OR s.title LIKE ? ESCAPE '\\')"
    " AND (? IS NULL OR s.title LIKE ? ESCAPE '\\'"
    "      OR s.content_text LIKE ? ESCAPE '\\')"
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
    " AND (? IS NULL OR (? = 1 AND s.content_text != '')"
    "      OR (? = 0 AND (s.content_text IS NULL OR s.content_text = '')))"
)

_SQL_DIST_SOURCES = (
    "SELECT s.feed_url AS feed_url, s.feed_title AS feed_title,"
    " COUNT(*) AS n FROM search_entries s"
    + _SQL_DIST_WHERE
    + " GROUP BY s.feed_url, s.feed_title ORDER BY n DESC, s.feed_url ASC LIMIT ?"
)

_SQL_DIST_DAYS = (
    "SELECT substr(s.published_at, 1, 10) AS day, COUNT(*) AS n"
    " FROM search_entries s"
    + _SQL_DIST_WHERE
    + " AND s.published_at >= ? AND s.published_at < ?"
    " GROUP BY day ORDER BY day ASC"
)

_SQL_DIST_TOTAL = (
    "SELECT COUNT(*) AS n FROM search_entries s" + _SQL_DIST_WHERE
)


class SearchStore:
    """Read path for the derived search projection."""

    def __init__(self, database: Database) -> None:
        self._db = database

    async def ensure_migrated(self) -> None:
        """Lazy migration for direct read paths (N143/N145 routes that
        don't go through the sync service first)."""
        await self._db.migrate()

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

    # -- N145 来源内搜索分布（聚合读路径） --------------------------------

    async def distribution_sources(
        self,
        *,
        terms: list[str],
        intitle_terms: list[str] | None = None,
        phrase: str | None = None,
        exclude_terms: list[str] | None = None,
        feed_url: str | None = None,
        category_id: str | None = None,
        unread_only: bool = False,
        starred_only: bool = False,
        published_from: str | None = None,
        published_to: str | None = None,
        has_summary: bool | None = None,
        limit: int = 21,
    ) -> list[Any]:
        """Top-N 来源计数（limit 取 n+1 由调用方探测截断诚实性）。"""
        params = _filter_params(
            terms=terms,
            intitle_terms=intitle_terms,
            phrase=phrase,
            exclude_terms=exclude_terms,
            feed_url=feed_url,
            category_id=category_id,
            unread_only=unread_only,
            starred_only=starred_only,
            published_from=published_from,
            published_to=published_to,
            has_summary=has_summary,
        )
        params.append(max(1, limit))
        return await self._db.fetch_all(_SQL_DIST_SOURCES, tuple(params))

    async def distribution_days(
        self,
        *,
        terms: list[str],
        day_from: str,
        day_to: str,
        intitle_terms: list[str] | None = None,
        phrase: str | None = None,
        exclude_terms: list[str] | None = None,
        feed_url: str | None = None,
        category_id: str | None = None,
        unread_only: bool = False,
        starred_only: bool = False,
        published_from: str | None = None,
        published_to: str | None = None,
        has_summary: bool | None = None,
    ) -> list[Any]:
        """窗口内逐日计数（[day_from, day_to) 排他上界；SQL 分桶）。"""
        params = _filter_params(
            terms=terms,
            intitle_terms=intitle_terms,
            phrase=phrase,
            exclude_terms=exclude_terms,
            feed_url=feed_url,
            category_id=category_id,
            unread_only=unread_only,
            starred_only=starred_only,
            published_from=published_from,
            published_to=published_to,
            has_summary=has_summary,
        )
        params.extend([day_from, day_to])
        return await self._db.fetch_all(_SQL_DIST_DAYS, tuple(params))

    async def distribution_total(
        self,
        *,
        terms: list[str],
        intitle_terms: list[str] | None = None,
        phrase: str | None = None,
        exclude_terms: list[str] | None = None,
        feed_url: str | None = None,
        category_id: str | None = None,
        unread_only: bool = False,
        starred_only: bool = False,
        published_from: str | None = None,
        published_to: str | None = None,
        has_summary: bool | None = None,
    ) -> int:
        """过滤链全量计数（无窗口；与 sources 聚合同一 WHERE）。"""
        params = _filter_params(
            terms=terms,
            intitle_terms=intitle_terms,
            phrase=phrase,
            exclude_terms=exclude_terms,
            feed_url=feed_url,
            category_id=category_id,
            unread_only=unread_only,
            starred_only=starred_only,
            published_from=published_from,
            published_to=published_to,
            has_summary=has_summary,
        )
        row = await self._db.fetch_one(_SQL_DIST_TOTAL, tuple(params))
        return int(row["n"]) if row else 0

    async def feed_in_category(self, *, category_id: str, feed_url: str) -> bool:
        """来源是否属于分类（N143 why-missed 的分类条件求值）。"""
        row = await self._db.fetch_one(
            "SELECT 1 FROM search_feeds WHERE category_id = ? AND feed_url = ?",
            (category_id, feed_url),
        )
        return row is not None

    async def resolve_source_token(self, token: str) -> str | None:
        """N142 来源名/URL 片段 → feed_url（有界，找不到 = None）。

        解析顺序：标题精确（casefold 由 LIKE/比较承担——SQLite LIKE 对
        ASCII 不区分大小写）→ 标题子串（更短标题优先，避免泛词命中长
        标题）→ feed_url 子串（site:xxx 场景）。全部绑定参数，无拼接。
        """
        await self._db.migrate()
        needle = like_pattern(token)
        for sql in (
            "SELECT feed_url FROM search_feeds WHERE feed_title = ? COLLATE NOCASE LIMIT 1",
            "SELECT feed_url FROM search_feeds WHERE feed_title LIKE ? ESCAPE '\\' ORDER BY length(feed_title) ASC, feed_url ASC LIMIT 1",
            "SELECT feed_url FROM search_feeds WHERE feed_url LIKE ? ESCAPE '\\' ORDER BY length(feed_url) ASC, feed_url ASC LIMIT 1",
        ):
            row = await self._db.fetch_one(sql, (needle,))
            if row is not None and row["feed_url"]:
                return str(row["feed_url"])
        return None
