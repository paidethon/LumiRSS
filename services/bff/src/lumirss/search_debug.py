"""N143 搜索排除原因 — miss diagnosis for one owned entry.

Re-runs the search filter chain against a single projection row and
reports every concrete condition that would exclude it (text terms,
intitle/phrase/exclude, source/category, unread/starred, date bounds,
summary flag). Semantics mirror the SQL in ``search_store._SQL_SEARCH``
with the same Python-side casefold matching the F074 explain path uses
(:func:`lumirss.search_index.matched_fields`).

Pure logic, no I/O: the router fetches the row (own-scope only — a
foreign ref is simply absent from the caller's database and becomes a
404 with no existence leak) and pre-computes the category membership
check in SQL.
"""

from typing import Any


class SearchEntryNotFound(Exception):
    """The entryRef is not in the caller's own search projection.

    Own-scope only: another user's ref is simply absent from this
    database, so the same 404 covers "not found" and "not yours" with
    no existence leak (mapped to 404 search_entry_not_found).
    """


def _fold(value: str | None) -> str:
    return (value or "").casefold()


def _contains(value: str | None, term: str) -> bool:
    return _fold(term) in _fold(value)


def diagnose_row(
    row: Any,
    *,
    terms: list[str],
    intitle_terms: list[str],
    phrase: str | None,
    exclude_terms: list[str],
    feed_url: str | None,
    in_category: bool,
    unread_only: bool,
    starred_only: bool,
    published_from: str | None,
    published_to: str | None,
    has_summary: bool | None,
) -> list[dict[str, str]]:
    """逐条件复检一行投影；返回全部未通过条件（顺序 = SQL 条件顺序）。

    空列表 = 该条目满足全部条件（属于「应命中」，未看到属于排序/分页
    位置问题，由调用方如实标注 rank）。
    """
    reasons: list[dict[str, str]] = []
    title = row["title"]
    author = row["author"]
    content = row["content_text"]
    published_at = row["published_at"]

    # 1. 基础词条（title / content / author 任一包含即可）。
    for term in terms:
        if not (
            _contains(title, term)
            or _contains(content, term)
            or _contains(author, term)
        ):
            reasons.append(
                {
                    "kind": "term",
                    "detail": f"词条「{term}」未出现在标题、正文或作者中。",
                }
            )
    # 2. intitle（仅标题）。
    for term in intitle_terms:
        if not _contains(title, term):
            reasons.append(
                {"kind": "intitle", "detail": f"词条「{term}」不在标题中（仅标题条件）。"}
            )
    # 3. 精确短语（标题或正文原词序子串）。
    if phrase and not (_contains(title, phrase) or _contains(content, phrase)):
        reasons.append(
            {
                "kind": "phrase",
                "detail": f"精确短语「{phrase}」未按原词序出现在标题或正文中。",
            }
        )
    # 4. 排除词（三列任一包含即排除）。
    for term in exclude_terms:
        if (
            _contains(title, term)
            or _contains(content, term)
            or _contains(author, term)
        ):
            reasons.append({"kind": "exclude", "detail": f"命中排除词「{term}」。"})
    # 5. 来源过滤。
    if feed_url and str(row["feed_url"]) != feed_url:
        reasons.append(
            {
                "kind": "source",
                "detail": (
                    "来源过滤不匹配：条目属于"
                    f"「{row['feed_title'] or row['feed_url']}」。"
                ),
            }
        )
    # 6. 分类过滤（router 已按 search_feeds 投影求值）。
    if not in_category:
        reasons.append(
            {"kind": "category", "detail": "分类过滤不匹配：条目来源不在该分类下。"}
        )
    # 7. 未读过滤。
    if unread_only and int(row["read"] or 0) != 0:
        reasons.append({"kind": "unread", "detail": "条目已读，被「仅未读」过滤。"})
    # 8. 收藏过滤。
    if starred_only and int(row["starred"] or 0) != 1:
        reasons.append({"kind": "starred", "detail": "条目未收藏，被「仅收藏」过滤。"})
    # 9. 日期范围（字符串比较口径与 SQL 相同：from 含端点、to 排他）。
    if published_from and not str(published_at) >= published_from:
        reasons.append(
            {
                "kind": "date",
                "detail": (
                    f"发布时间 {published_at} 早于起始日期 {published_from}。"
                ),
            }
        )
    if published_to and not str(published_at) < published_to:
        reasons.append(
            {
                "kind": "date",
                "detail": f"发布时间 {published_at} 不早于截止日期 {published_to}。",
            }
        )
    # 10. 摘要维度（口径与 SQL 一致：正文文本非空 = 有摘要）。
    if has_summary is True and (content or "") == "":
        reasons.append(
            {"kind": "hasSummary", "detail": "摘要条件为「有摘要」，但条目正文文本为空。"}
        )
    if has_summary is False and (content or "") != "":
        reasons.append(
            {"kind": "hasSummary", "detail": "摘要条件为「无摘要」，但条目有正文文本。"}
        )
    return reasons
