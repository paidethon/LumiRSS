"""F091 RAG 索引排除规则 —— source_overrides.rag_excluded 的读写与执行点。

- rag_excluded=1：该来源不进入 RAG 语料（重建排除 + 现有分块移除）；
- 优先级：ai_disabled=1 严格优先 —— 即使 rag_excluded=0，AI 禁用源
  仍然排除（F066 语义不被本列削弱）；
- 排除/恢复都只影响派生索引：原始条目数据不受任何影响。

写站点（set_rag_excluded）2 处（INSERT / UPDATE）。
"""

from typing import Any

from lumirss.util import utc_now


async def set_rag_excluded(db: Any, feed_url: str, excluded: bool) -> None:
    await db.migrate()
    row = await db.fetch_one(
        "SELECT feed_url FROM source_overrides WHERE feed_url = ?", (feed_url,)
    )
    if row is None:
        await db.execute(
            "INSERT INTO source_overrides (feed_url, hidden_until, show_from, stale_alert_hours, extract_policy, reader_style_json, ai_disabled, rag_excluded, updated_at) VALUES (?, NULL, NULL, NULL, 'rss', NULL, 0, ?, ?)",
            (feed_url, 1 if excluded else 0, utc_now()),
        )
        return
    await db.execute(
        "UPDATE source_overrides SET rag_excluded = ?, updated_at = ? WHERE feed_url = ?",
        (1 if excluded else 0, utc_now(), feed_url),
    )


async def rag_excluded_feed_set(db: Any) -> set[str]:
    """rag_excluded=1 的 feed_url 集合（_document_pages 排除用）。"""
    if db is None:
        return set()
    try:
        await db.migrate()
        rows = await db.fetch_all(
            "SELECT feed_url FROM source_overrides WHERE rag_excluded = 1"
        )
    except Exception:  # noqa: BLE001 — fail-open（不过滤）
        return set()
    return {str(row["feed_url"]) for row in rows}


async def list_exclusions(db: Any, limit: int = 500) -> list[dict[str, Any]]:
    """来源列表（出现在投影或覆盖表中的 feed）+ 排除状态 + 受影响分块数。"""
    await db.migrate()
    rows = await db.fetch_all(
        "SELECT se.feed_url AS feed_url, so.rag_excluded AS rag_excluded, so.ai_disabled AS ai_disabled, COUNT(c.chunk_id) AS chunks"
        " FROM (SELECT DISTINCT feed_url FROM search_entries UNION SELECT feed_url FROM source_overrides) se"
        " LEFT JOIN source_overrides so ON so.feed_url = se.feed_url"
        " LEFT JOIN rag_chunks c ON c.model_id = 'BAAI/bge-small-zh-v1.5' AND c.ref IN"
        "   (SELECT entry_ref FROM search_entries e WHERE e.feed_url = se.feed_url)"
        " GROUP BY se.feed_url ORDER BY se.feed_url ASC LIMIT ?",
        (max(1, min(limit, 1000)),),
    )
    return [
        {
            "feedUrl": str(row["feed_url"]),
            "ragExcluded": bool(row["rag_excluded"]),
            "aiDisabled": bool(row["ai_disabled"]),
            "affectedChunks": int(row["chunks"] or 0),
        }
        for row in rows
    ]
