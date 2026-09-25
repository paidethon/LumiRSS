"""N038 按来源保留策略预演 —— 投影口径估算 + 本地投影裁剪。

诚实边界（模块存在的理由）：

- 估算**只**基于 Lumi 派生投影（search_entries），响应以 ``basis``
  明确标注「预估值基于 Lumi 投影，实际删除需在 FreshRSS 原生界面
  执行」；P09 委托入口（/api/v1/freshrss/native-url）提供原生界面
  坐标，本模块绝不持有、绝不调用任何上游删除能力；
- apply 落库 source_overrides.retention_days 后执行的「prune」同样是
  **纯投影**操作：DELETE FROM search_entries（starred 恒排除）。
  FreshRSS 侧零调用（负向契约由测试以适配器 mock 断言）；
- 投影可再生成：下次同步可能把上游仍在的条目重新投影回来——这是
  派生数据的诚实行为，本列不充当上游物理删除的替代品。
"""

from typing import Any

from lumirss.storage import Database

RETENTION_DAYS_MIN = 7
RETENTION_DAYS_MAX = 3650

_BASIS_NOTE = "预估值基于 Lumi 投影，实际删除需在 FreshRSS 原生界面执行"


def retention_days_valid(value: int) -> bool:
    return RETENTION_DAYS_MIN <= value <= RETENTION_DAYS_MAX


def _cutoff(days: int, now: str | None = None) -> str:
    """published_at 截止线（UTC Z 串；与投影 published_at 同形比较）。"""
    from datetime import UTC, datetime, timedelta

    moment = (
        datetime.fromisoformat(now.replace("Z", "+00:00"))
        if now
        else datetime.now(UTC)
    )
    return (moment - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


async def retention_preview(
    db: Database,
    feed_url: str,
    *,
    days: int,
    applied_days: int | None = None,
    native_origin: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """预演：该来源早于 N 天的投影条目数（加星恒排除，单独计数）。

    只读：COUNT 查询，零写入。``applied_days`` = 已存储的保留策略
    （None = 该来源尚未启用）。"""
    await db.migrate()
    cutoff = _cutoff(days, now)
    row = await db.fetch_one(
        "SELECT COUNT(*) AS total,"
        " COALESCE(SUM(CASE WHEN published_at < ? THEN 1 ELSE 0 END), 0) AS older,"
        " COALESCE(SUM(CASE WHEN published_at < ? AND starred = 1 THEN 1 ELSE 0 END), 0) AS older_starred,"
        " COALESCE(SUM(CASE WHEN published_at < ? AND starred = 0 THEN 1 ELSE 0 END), 0) AS older_prunable"
        " FROM search_entries WHERE feed_url = ?",
        (cutoff, cutoff, cutoff, feed_url),
    )
    total = int(row["total"]) if row is not None else 0
    older = int(row["older"]) if row is not None else 0
    older_starred = int(row["older_starred"]) if row is not None else 0
    older_prunable = int(row["older_prunable"]) if row is not None else 0
    native_url: str | None = None
    if native_origin:
        native_url = native_origin.rstrip("/") + "/i/?f=" + feed_url
    return {
        "feedUrl": feed_url,
        "retentionDays": days,
        "appliedRetentionDays": applied_days,
        "cutoff": cutoff,
        "totalEntries": total,
        "olderEntries": older,
        "starredExcluded": older_starred,
        "prunableEntries": older_prunable,
        "basis": "projection",
        "note": _BASIS_NOTE,
        "freshrssNativeUrl": native_url,
    }


async def prune_projection(
    db: Database, feed_url: str, *, days: int, now: str | None = None
) -> int:
    """按保留天数裁剪**本地投影**（starred 恒排除；FreshRSS 零调用）。

    返回实际删除的投影行数。"""
    await db.migrate()
    cutoff = _cutoff(days, now)
    cursor = await db.execute(
        "DELETE FROM search_entries WHERE feed_url = ? AND starred = 0 AND published_at < ?",
        (feed_url, cutoff),
    )
    # Database.execute 返回 rowcount（SQL 文档化约定：INSERT/UPDATE/DELETE
    # → 受影响行数；无法判定时为 None → 诚实计 0）。
    return int(cursor) if cursor else 0
