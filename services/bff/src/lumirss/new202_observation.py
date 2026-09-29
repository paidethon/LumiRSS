"""NEW-202 订阅停更观察 —— 观察期状态、事实聚合与到期复核。

语义边界（模块存在的理由）：

- 观察 = 用户为可疑停更的来源设一段复核期。**系统绝不自动停订**：
  到期只在查询时如实标注 ``expired=true``，由用户选择继续观察
  （extend / continue）或停订（unsubscribed——实际退订走既有
  ``DELETE /api/v1/subscriptions/{ref}`` 或 NEW-209 回收箱路径）；
- 「不把抓取失败误判停更」是本模块的核心口径（:func:`build_facts`）：
  抓取健康来自 source_refresh_log（error = 抓取失败，verdict =
  ``fetch_failure``，与「真没发文」明确区分）；发文变化来自派生投影
  search_entries 的 published_at（观察期内有无新文、最后发文时刻）。
  投影与检查记录都没有 → ``no_data``（资料缺失 ≠ 没有发文，诚实）；
- 消费 NEW-210：观察列表对处于停机计划的来源标注 ``fetchPaused``。

同一来源同时至多一条 active 观察（部分唯一索引兜底 + 写前检查给出
稳定 409 observation_exists）。
"""

import uuid as _uuid
from typing import Any

from lumirss.source_overrides import canonical_utc
from lumirss.storage import Database
from lumirss.util import utc_now

DAYS_MIN = 7
DAYS_MAX = 180

VERDICT_FETCH_FAILURE = "fetch_failure"
VERDICT_NO_NEW_POSTS = "no_new_posts"
VERDICT_STILL_POSTING = "still_posting"
VERDICT_NO_DATA = "no_data"


class ObservationInvalid(ValueError):
    """观察输入非法（天数/时刻），路由层映射 422。"""


class ObservationNotFound(Exception):
    """观察不存在 —— 404 observation_not_found。"""


class ObservationExists(Exception):
    """该来源已有一条 active 观察 —— 409 observation_exists。"""


def canonical_moment(value: Any) -> str:
    """RFC3339 → UTC Z 串；非法 raise ObservationInvalid → 422。"""
    canonical = canonical_utc(value if isinstance(value, str) else "")
    if canonical is None:
        raise ObservationInvalid("时刻必须是可解析的 ISO 时刻。")
    return canonical


def validate_days(value: Any, field: str = "days") -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ObservationInvalid(f"{field} 必须是整数天。")
    if not DAYS_MIN <= value <= DAYS_MAX:
        raise ObservationInvalid(f"{field} 必须在 {DAYS_MIN}-{DAYS_MAX} 天之间。")
    return value


def _iso_plus_days(iso: str, days: int) -> str:
    from datetime import datetime, timedelta

    moment = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return (moment + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def verdict_for(
    *,
    fetch_health: str | None,
    projection_rows: int,
    posts_since_start: int,
) -> str:
    """事实 → 判定（纯函数）。

    抓取失败优先于一切发文结论——抓取都进不来时，「没有新文」不是
    停更证据。"""
    if fetch_health == "error":
        return VERDICT_FETCH_FAILURE
    if projection_rows == 0:
        return VERDICT_NO_DATA
    if posts_since_start == 0:
        return VERDICT_NO_NEW_POSTS
    return VERDICT_STILL_POSTING


def _row_to_observation(row: Any) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "feedUrl": str(row["feed_url"]),
        "note": row["note"],
        "startedAt": str(row["started_at"]),
        "endsAt": str(row["ends_at"]),
        "status": str(row["status"]),
        "resolution": row["resolution"],
        "closedAt": row["closed_at"],
        "createdAt": str(row["created_at"]),
    }


class ObservationStore:
    """SQL 唯一入口；inline literal at each execute site（repo 约定）。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self,
        *,
        feed_url: str,
        days: int,
        note: str | None = None,
        now: str | None = None,
    ) -> dict[str, Any]:
        moment = now or utc_now()
        existing = await self.active_for_feed(feed_url)
        if existing is not None:
            raise ObservationExists(feed_url)
        observation_id = str(_uuid.uuid4())
        await self._db.migrate()
        await self._db.execute(
            "INSERT INTO new202_observations"
            " (id, feed_url, note, started_at, ends_at, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, 'active', ?)",
            (
                observation_id,
                feed_url,
                (note or "").strip() or None,
                moment,
                _iso_plus_days(moment, days),
                moment,
            ),
        )
        row = await self._db.fetch_one(
            "SELECT * FROM new202_observations WHERE id = ?", (observation_id,)
        )
        assert row is not None
        return _row_to_observation(row)

    async def active_for_feed(self, feed_url: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT * FROM new202_observations WHERE feed_url = ? AND status = 'active'",
            (feed_url,),
        )
        return _row_to_observation(row) if row is not None else None

    async def list_observations(self, *, status: str = "active") -> list[dict[str, Any]]:
        await self._db.migrate()
        if status == "all":
            rows = await self._db.fetch_all(
                "SELECT * FROM new202_observations"
                " ORDER BY ends_at ASC, id ASC LIMIT 200",
                (),
            )
        else:
            rows = await self._db.fetch_all(
                "SELECT * FROM new202_observations WHERE status = ?"
                " ORDER BY ends_at ASC, id ASC LIMIT 200",
                (status,),
            )
        return [_row_to_observation(row) for row in rows]

    async def get(self, observation_id: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT * FROM new202_observations WHERE id = ?", (observation_id,)
        )
        return _row_to_observation(row) if row is not None else None

    async def extend(self, observation_id: str, days: int, *, now: str | None = None) -> dict[str, Any]:
        """继续观察：到期日 = max(now, ends_at) + days（不缩短既有期）。"""
        observation = await self.get(observation_id)
        if observation is None:
            raise ObservationNotFound(observation_id)
        moment = now or utc_now()
        base = max(str(observation["endsAt"]), moment)
        await self._db.execute(
            "UPDATE new202_observations SET ends_at = ? WHERE id = ?",
            (_iso_plus_days(base, days), observation_id),
        )
        updated = await self.get(observation_id)
        assert updated is not None
        return updated

    async def close(
        self, observation_id: str, resolution: str, *, now: str | None = None
    ) -> dict[str, Any]:
        """到期复核收尾（set 语义）：continue（继续保留订阅，结束本期）
        或 unsubscribed（用户已决定停订——实际退订走既有退订端点）。"""
        observation = await self.get(observation_id)
        if observation is None:
            raise ObservationNotFound(observation_id)
        if observation["status"] != "active":
            raise ObservationExists(observation_id)
        if resolution not in ("continue", "unsubscribed"):
            raise ObservationInvalid("resolution 必须是 continue 或 unsubscribed。")
        await self._db.execute(
            "UPDATE new202_observations SET status = 'closed', resolution = ?,"
            " closed_at = ? WHERE id = ?",
            (resolution, now or utc_now(), observation_id),
        )
        updated = await self.get(observation_id)
        assert updated is not None
        return updated


async def build_facts(db: Database, observation: dict[str, Any]) -> dict[str, Any]:
    """聚合一个观察的事实面（投影 + 检查记录 + 停机计划）。

    全部只读派生数据；投影未覆盖的订阅诚实缺席（no_data ≠ 停更）。"""
    from lumirss.new210_pause import PausePlanStore
    from lumirss.refresh_log import SourceRefreshLogStore

    feed_url = str(observation["feedUrl"])
    await db.migrate()
    row = await db.fetch_one(
        "SELECT COUNT(*) AS total,"
        " COALESCE(SUM(CASE WHEN published_at >= ? THEN 1 ELSE 0 END), 0) AS since_start,"
        " COALESCE(MAX(published_at), '') AS last_post"
        " FROM search_entries WHERE feed_url = ?",
        (str(observation["startedAt"]), feed_url),
    )
    projection_rows = int(row["total"]) if row is not None else 0
    posts_since_start = int(row["since_start"]) if row is not None else 0
    last_post_at = str(row["last_post"]) if row is not None else ""
    fetch_health = await SourceRefreshLogStore(db).latest_result(feed_url)
    paused_urls = await PausePlanStore(db).paused_feed_urls()
    now = utc_now()
    return {
        "lastPostAt": last_post_at or None,
        "postsSinceStart": posts_since_start,
        "projectionRows": projection_rows,
        "fetchHealth": fetch_health,
        "verdict": verdict_for(
            fetch_health=fetch_health,
            projection_rows=projection_rows,
            posts_since_start=posts_since_start,
        ),
        "fetchPaused": feed_url in paused_urls,
        "expired": bool(observation["status"] == "active" and observation["endsAt"] <= now),
        "basis": "projection+refresh-log",
        "note": (
            "抓取失败（fetchHealth=error）不构成停更证据；投影缺失显示为"
            " no_data（资料缺失 ≠ 没有发文）。系统绝不自动停订。"
        ),
    }
