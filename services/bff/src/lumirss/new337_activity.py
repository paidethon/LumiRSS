"""NEW-337 空间活动摘要 —— 按授权范围汇总本空间文章和讨论变化。

边界（硬规则）：

- 只汇总**空间共享面**的事件（投稿/审批、会议、讨论/回复、版本通知、
  附件共享、成员变化）——这些表本身就是显式共享的产物；
- 绝不包含私人阅读记录（阅读状态/队列/便签在各自 per-user 库内，
  本模块根本无法也绝不去触碰）；
- 时间段由用户显式选择（from/to ISO；上限 366 天，防全表扫）；
  零 AI、零后台任务——纯 SELECT 聚合，无新表。
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from lumirss.space_core import SpaceInvalid, SpaceStore
from lumirss.storage import Database

MAX_RANGE_DAYS = 366

# 各共享面表的事件时间列（created_at 驱动；reviewed/closed/resolved/
# revoked 的「发生时点」列单独列出，用于已审结/已闭合等次级计数）。
_COUNT_TABLES = (
    "space_contributions",
    "space_meetings",
    "space_discussions",
    "space_discussion_replies",
    "space_version_notices",
    "space_attachment_shares",
    "space_disagreements",
)


def _parse_bound(value: str | None, field: str, *, default_days_ago: int | None = None) -> str:
    if value is None or not str(value).strip():
        if default_days_ago is None:
            raise SpaceInvalid(f"{field} 必须是 ISO 时间戳。")
        return (datetime.now(UTC) - timedelta(days=default_days_ago)).isoformat(timespec="seconds")
    normalized = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise SpaceInvalid(f"{field} 必须是 ISO 时间戳。") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat(timespec="seconds")


class ActivitySummary:
    """空间共享面活动聚合（纯读；无写入路径）。"""

    def __init__(self, control_db: Database, spaces: SpaceStore) -> None:
        self._db = control_db
        self._spaces = spaces

    async def _count(self, table: str, from_at: str, to_at: str) -> int:
        if table not in _COUNT_TABLES:  # 白名单兜底，绝不拼任意表名
            raise SpaceInvalid("未知的活动表。")
        row = await self._db.fetch_one(
            f"SELECT COUNT(*) AS n FROM {table} WHERE space_id = ? AND created_at >= ? AND created_at <= ?",  # noqa: S608 — 表名来自上方白名单
            (self._space_id, from_at, to_at),
        )
        return int(row["n"]) if row else 0

    async def _count_by_status(
        self, table: str, status: str, by_column: str, from_at: str, to_at: str
    ) -> int:
        row = await self._db.fetch_one(
            f"SELECT COUNT(*) AS n FROM {table} WHERE space_id = ? AND status = ? AND {by_column} >= ? AND {by_column} <= ?",  # noqa: S608 — 表名/列名均为本模块字面量
            (self._space_id, status, from_at, to_at),
        )
        return int(row["n"]) if row else 0

    async def _count_nonnull(self, table: str, column: str, from_at: str, to_at: str) -> int:
        row = await self._db.fetch_one(
            f"SELECT COUNT(*) AS n FROM {table} WHERE space_id = ? AND {column} IS NOT NULL AND {column} >= ? AND {column} <= ?",  # noqa: S608 — 同上
            (self._space_id, from_at, to_at),
        )
        return int(row["n"]) if row else 0

    async def _recent(
        self, sql: str, from_at: str, to_at: str
    ) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(sql, (self._space_id, from_at, to_at))
        return [dict(row) for row in rows]

    async def summarize(
        self,
        space_id: str,
        *,
        actor_user_id: str,
        from_raw: str | None,
        to_raw: str | None,
    ) -> dict[str, Any]:
        membership = await self._spaces.require_member(space_id, actor_user_id)
        self._space_id = space_id
        to_at = _parse_bound(to_raw, "to", default_days_ago=0)
        from_at = _parse_bound(from_raw, "from", default_days_ago=7)
        if from_at > to_at:
            raise SpaceInvalid("from 必须早于 to。")
        span = datetime.fromisoformat(to_at) - datetime.fromisoformat(from_at)
        if span > timedelta(days=MAX_RANGE_DAYS):
            raise SpaceInvalid(f"时间段最长 {MAX_RANGE_DAYS} 天。")

        counts = {
            "contributions": {
                "submitted": await self._count("space_contributions", from_at, to_at),
                "approved": await self._count_by_status(
                    "space_contributions", "approved", "reviewed_at", from_at, to_at
                ),
                "rejected": await self._count_by_status(
                    "space_contributions", "rejected", "reviewed_at", from_at, to_at
                ),
            },
            "meetings": {
                "created": await self._count("space_meetings", from_at, to_at),
                "closed": await self._count_nonnull("space_meetings", "closed_at", from_at, to_at),
            },
            "discussions": {
                "asked": await self._count("space_discussions", from_at, to_at),
                "replies": await self._count("space_discussion_replies", from_at, to_at),
                "resolved": await self._count_nonnull("space_discussions", "resolved_at", from_at, to_at),
            },
            "versionNotices": {
                "reported": await self._count("space_version_notices", from_at, to_at),
            },
            "attachmentShares": {
                "shared": await self._count("space_attachment_shares", from_at, to_at),
                "revoked": await self._count_nonnull("space_attachment_shares", "revoked_at", from_at, to_at),
            },
            "disagreements": {
                "created": await self._count("space_disagreements", from_at, to_at),
            },
            "members": await self._count_members(from_at, to_at),
        }
        recent = {
            "contributions": await self._recent(
                "SELECT id, title, status, submitted_by_username AS actor, created_at AS at "
                "FROM space_contributions WHERE space_id = ? AND created_at >= ? AND created_at <= ? "
                "ORDER BY created_at DESC, rowid DESC LIMIT 10",
                from_at,
                to_at,
            ),
            "meetings": await self._recent(
                "SELECT id, title, status, created_by_username AS actor, created_at AS at "
                "FROM space_meetings WHERE space_id = ? AND created_at >= ? AND created_at <= ? "
                "ORDER BY created_at DESC, rowid DESC LIMIT 10",
                from_at,
                to_at,
            ),
            "discussions": await self._recent(
                "SELECT id, title, status, asked_by_username AS actor, created_at AS at "
                "FROM space_discussions WHERE space_id = ? AND created_at >= ? AND created_at <= ? "
                "ORDER BY created_at DESC, rowid DESC LIMIT 10",
                from_at,
                to_at,
            ),
            "versionNotices": await self._recent(
                "SELECT id, entry_ref, version_label AS title, reported_by_username AS actor, created_at AS at "
                "FROM space_version_notices WHERE space_id = ? AND created_at >= ? AND created_at <= ? "
                "ORDER BY created_at DESC, rowid DESC LIMIT 10",
                from_at,
                to_at,
            ),
            "attachmentShares": await self._recent(
                "SELECT id, name AS title, owner_username AS actor, created_at AS at "
                "FROM space_attachment_shares WHERE space_id = ? AND created_at >= ? AND created_at <= ? "
                "ORDER BY created_at DESC, rowid DESC LIMIT 10",
                from_at,
                to_at,
            ),
            "members": await self._recent(
                "SELECT id, username AS title, role AS status, role AS actor, created_at AS at "
                "FROM space_members WHERE space_id = ? AND created_at >= ? AND created_at <= ? "
                "ORDER BY created_at DESC, rowid DESC LIMIT 10",
                from_at,
                to_at,
            ),
        }
        _ = membership  # 成员资格已在 require_member 中校验
        return {
            "spaceId": space_id,
            "from": from_at,
            "to": to_at,
            "scope": "space-shared-only",
            "note": "仅汇总空间共享面事件；私人阅读记录不在任何空间视图内。",
            "counts": counts,
            "recent": recent,
        }

    async def _count_members(self, from_at: str, to_at: str) -> int:
        row = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM space_members WHERE space_id = ? AND created_at >= ? AND created_at <= ?",
            (self._space_id, from_at, to_at),
        )
        return int(row["n"]) if row else 0
