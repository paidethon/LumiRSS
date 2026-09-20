"""F066 per-source AI 禁用 — source_overrides.ai_disabled 的读写与判定。

- set_ai_disabled：开/关（保留其它覆盖维度；行不存在时插入）；
- is_ai_disabled / ai_disabled_feed_set / disabled_entry_refs：
  服务端执行点使用的判定（UI 隐藏按钮不算数——统一走这里）。
- 口径：search_entries 投影缺失该条目 → 视为未禁用（fail-open，
  与 feed/category 过滤同款诚实降级；下次同步自愈）。

独立成文件以遵守「每文件 ≤4 execute 站点」（source_overrides.py 已满）。
写站点 2 处（INSERT / UPDATE 各一）。
"""

from typing import Any

from lumirss.util import utc_now


async def set_ai_disabled(db: Any, feed_url: str, disabled: bool) -> None:
    """设置来源 AI 禁用位；保留同行的其它覆盖维度。"""
    await db.migrate()
    row = await db.fetch_one(
        "SELECT hidden_until FROM source_overrides WHERE feed_url = ?",
        (feed_url,),
    )
    if row is None:
        await db.execute(
            "INSERT INTO source_overrides (feed_url, hidden_until, show_from, stale_alert_hours, extract_policy, reader_style_json, ai_disabled, updated_at) VALUES (?, NULL, NULL, NULL, 'rss', NULL, ?, ?)",
            (feed_url, 1 if disabled else 0, utc_now()),
        )
        return
    await db.execute(
        "UPDATE source_overrides SET ai_disabled = ?, updated_at = ? WHERE feed_url = ?",
        (1 if disabled else 0, utc_now(), feed_url),
    )


async def is_ai_disabled(db: Any, feed_url: str) -> bool:
    await db.migrate()
    row = await db.fetch_one(
        "SELECT ai_disabled FROM source_overrides WHERE feed_url = ?",
        (feed_url,),
    )
    return row is not None and bool(row["ai_disabled"])


async def ai_disabled_feed_set(db: Any) -> set[str]:
    if db is None:
        return set()
    try:
        await db.migrate()
        rows = await db.fetch_all(
            "SELECT feed_url FROM source_overrides WHERE ai_disabled = 1"
        )
    except Exception:  # noqa: BLE001 — 判定失败 fail-open（不过滤）
        return set()
    return {str(row["feed_url"]) for row in rows}


async def disabled_entry_refs(db: Any, refs: list[str]) -> set[str]:
    """给定 entry_ref 列表，返回其中属于「AI 禁用来源」的子集。"""
    if db is None or not refs:
        return set()
    try:
        await db.migrate()
    except Exception:  # noqa: BLE001 — fail-open
        return set()
    disabled: set[str] = set()
    try:
        for ref in {str(r) for r in refs}:
            row = await db.fetch_one(
                """SELECT so.ai_disabled AS d FROM search_entries se
                JOIN source_overrides so ON so.feed_url = se.feed_url
                WHERE se.entry_ref = ?""",
                (str(ref),),
            )
            if row is not None and bool(row["d"]):
                disabled.add(str(ref))
    except Exception:  # noqa: BLE001 — fail-open
        return set()
    return disabled


async def feed_url_for_entry(db: Any, entry_ref: str) -> str | None:
    """entry_ref → feed_url（投影缺失 → None，fail-open）。"""
    await db.migrate()
    row = await db.fetch_one(
        "SELECT feed_url FROM search_entries WHERE entry_ref = ?",
        (entry_ref,),
    )
    return str(row["feed_url"]) if row is not None else None


async def feed_refs(db: Any, feed_url: str, limit: int = 2000) -> list[str]:
    """某来源在投影中的 entry_ref（F066 禁用时 RAG 移除用；有界）。"""
    await db.migrate()
    rows = await db.fetch_all(
        "SELECT entry_ref FROM search_entries WHERE feed_url = ? LIMIT ?",
        (feed_url, limit),
    )
    return [str(row["entry_ref"]) for row in rows]
