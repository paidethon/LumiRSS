"""N090 翻译隐私路由 —— per-source translation_policy=local_only 的读写与判定。

- set_translation_policy：设置/清除（None = 清除，恢复跟随全局）；
- is_local_only / local_only_feed_set / local_only_entry_refs：
  服务端执行点使用的判定（段落生成的 403 在这里判，UI 徽章不算数——
  F066 ai_disabled 同一执行位置、同一诚实口径）。

独立成文件：source_overrides.py 的 execute 站点已满，「每文件 ≤4
execute 站点」的惯例由新文件承载。投影缺失该条目 → fail-open（视为
未启用，与 F066 同款降级；下次同步自愈）。
"""

from typing import Any

from lumirss.util import utc_now

POLICY_LOCAL_ONLY = "local_only"
POLICIES = (POLICY_LOCAL_ONLY,)


class TranslationPolicyInvalid(ValueError):
    """policy 值非法（映射 422）。"""


async def set_translation_policy(db: Any, feed_url: str, policy: str | None) -> None:
    """设置来源翻译策略；``None`` = 清除。保留同行其它覆盖维度。"""
    if policy is not None and policy not in POLICIES:
        raise TranslationPolicyInvalid(f"translationPolicy 必须是 {POLICIES[0]} 或 null。")
    await db.migrate()
    row = await db.fetch_one(
        "SELECT hidden_until FROM source_overrides WHERE feed_url = ?",
        (feed_url,),
    )
    if row is None:
        await db.execute(
            "INSERT INTO source_overrides (feed_url, hidden_until, show_from, stale_alert_hours, extract_policy, reader_style_json, ai_disabled, translation_policy, updated_at) VALUES (?, NULL, NULL, NULL, 'rss', NULL, 0, ?, ?)",
            (feed_url, policy, utc_now()),
        )
        return
    await db.execute(
        "UPDATE source_overrides SET translation_policy = ?, updated_at = ? WHERE feed_url = ?",
        (policy, utc_now(), feed_url),
    )


async def translation_policy_for_feed(db: Any, feed_url: str | None) -> str | None:
    """feed_url → policy（NULL = 未启用 / 来源未知 fail-open）。"""
    if not feed_url:
        return None
    await db.migrate()
    row = await db.fetch_one(
        "SELECT translation_policy FROM source_overrides WHERE feed_url = ?",
        (feed_url,),
    )
    if row is None:
        return None
    value = row["translation_policy"]
    return str(value) if value in POLICIES else None


async def is_local_only(db: Any, feed_url: str | None) -> bool:
    return await translation_policy_for_feed(db, feed_url) == POLICY_LOCAL_ONLY


async def local_only_entry_refs(db: Any, refs: list[str]) -> set[str]:
    """给定 entry_ref 列表，返回其中属于 local_only 来源的子集。"""
    if db is None or not refs:
        return set()
    try:
        await db.migrate()
    except Exception:  # noqa: BLE001 — fail-open
        return set()
    local_only: set[str] = set()
    for ref in {str(r) for r in refs}:
        row = await db.fetch_one(
            """SELECT so.translation_policy AS p FROM search_entries se
            JOIN source_overrides so ON so.feed_url = se.feed_url
            WHERE se.entry_ref = ?""",
            (ref,),
        )
        if row is not None and row["p"] == POLICY_LOCAL_ONLY:
            local_only.add(ref)
    return local_only
