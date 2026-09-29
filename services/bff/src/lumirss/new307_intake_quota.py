"""NEW-307 自动接入来源配额 —— 单个 API 来源的每天最大条目数。

- 配额行存在才拦截；无行 = 该来源不限；
- 发布前原子预占（BEGIN IMMEDIATE 串行化）：当次 granted =
  min(请求条数, 剩余名额)，超出部分计入 pending（待处理计数）——
  不静默丢弃，用户在快照里看到 heldBack/pending 后调高上限或等
  次日本地自然日窗口滚动；
- 并发下绝不超额发布（同一写锁排队）；失败不回退（预占即计数，
  与 ai_quota 同一口径，宁可保守）；
- per-user：配额与计数都在 per-user 库（RoutingDatabase），A 给
  自己来源设的配额与用量对 B 完全不可见。
"""

from datetime import datetime
from typing import Any

from lumirss.db_tx import transaction
from lumirss.util import utc_now

MAX_ITEMS_PER_DAY = 100000


class IntakeQuotaInvalid(ValueError):
    """配额负载非法（映射 422）。"""


def clean_max_items(raw: Any) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise IntakeQuotaInvalid("maxItemsPerDay 必须是整数。")
    if not 1 <= raw <= MAX_ITEMS_PER_DAY:
        raise IntakeQuotaInvalid(f"maxItemsPerDay 必须在 1..{MAX_ITEMS_PER_DAY} 之间。")
    return raw


def day_key(moment: datetime | None = None) -> str:
    """本地自然日键（与 ai_quota 的本地时区窗口同口径）。"""
    return (moment or datetime.now().astimezone()).strftime("%Y-%m-%d")


def next_local_midnight(moment: datetime | None = None) -> str:
    base = (moment or datetime.now().astimezone())
    from datetime import timedelta

    reset = (base + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return reset.isoformat(timespec="seconds")


class IntakeQuotaStore:
    def __init__(self, db: Any) -> None:
        self._db = db

    async def set_quota(self, source_uuid: str, max_items_per_day: Any) -> dict[str, Any]:
        limit = clean_max_items(max_items_per_day)
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT source_uuid FROM api_intake_quota WHERE source_uuid = ?",
            (source_uuid,),
        )
        if row is None:
            await self._db.execute(
                "INSERT INTO api_intake_quota (source_uuid, max_items_per_day, updated_at) VALUES (?, ?, ?)",
                (source_uuid, limit, utc_now()),
            )
        else:
            await self._db.execute(
                "UPDATE api_intake_quota SET max_items_per_day = ?, updated_at = ? WHERE source_uuid = ?",
                (limit, utc_now(), source_uuid),
            )
        return {"sourceUuid": source_uuid, "maxItemsPerDay": limit}

    async def delete_quota(self, source_uuid: str) -> bool:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT source_uuid FROM api_intake_quota WHERE source_uuid = ?",
            (source_uuid,),
        )
        if row is None:
            return False
        await self._db.execute(
            "DELETE FROM api_intake_quota WHERE source_uuid = ?", (source_uuid,)
        )
        return True

    async def claim(self, source_uuid: str, wanted: int) -> dict[str, Any]:
        """原子预占 wanted 个名额；超出部分计入 pending。

        返回 {granted, heldBack, used, maxItemsPerDay, pending, dayKey}。
        无配额行 → granted=wanted（不拦截，其余字段如实为 0/None）。"""
        await self._db.migrate()
        today = day_key()

        def _claim(conn: Any) -> dict[str, Any]:
            conn.execute("BEGIN IMMEDIATE")
            quota_row = conn.execute(
                "SELECT max_items_per_day FROM api_intake_quota WHERE source_uuid = ?",
                (source_uuid,),
            ).fetchone()
            if quota_row is None:
                return {
                    "granted": wanted,
                    "heldBack": 0,
                    "used": 0,
                    "maxItemsPerDay": None,
                    "pending": 0,
                    "dayKey": today,
                }
            max_items = int(quota_row["max_items_per_day"])
            count_row = conn.execute(
                "SELECT items, pending FROM api_intake_counts WHERE source_uuid = ? AND day_key = ?",
                (source_uuid, today),
            ).fetchone()
            used = int(count_row["items"]) if count_row is not None else 0
            pending = int(count_row["pending"]) if count_row is not None else 0
            granted = max(0, min(wanted, max_items - used))
            held_back = wanted - granted
            new_used = used + granted
            new_pending = pending + held_back
            if count_row is None:
                conn.execute(
                    "INSERT INTO api_intake_counts (source_uuid, day_key, items, pending) VALUES (?, ?, ?, ?)",
                    (source_uuid, today, new_used, new_pending),
                )
            else:
                conn.execute(
                    "UPDATE api_intake_counts SET items = ?, pending = ? WHERE source_uuid = ? AND day_key = ?",
                    (new_used, new_pending, source_uuid, today),
                )
            return {
                "granted": granted,
                "heldBack": held_back,
                "used": new_used,
                "maxItemsPerDay": max_items,
                "pending": new_pending,
                "dayKey": today,
            }

        return await transaction(self._db, _claim)

    async def snapshot(self, source_uuid: str) -> dict[str, Any]:
        """配额现状（used/pending/remaining + 重置点）——调整入口依据。"""
        await self._db.migrate()
        today = day_key()
        quota_row = await self._db.fetch_one(
            "SELECT max_items_per_day, updated_at FROM api_intake_quota WHERE source_uuid = ?",
            (source_uuid,),
        )
        if quota_row is None:
            return {
                "sourceUuid": source_uuid,
                "configured": False,
                "maxItemsPerDay": None,
                "used": 0,
                "pending": 0,
                "remaining": None,
                "dayKey": today,
                "windowReset": next_local_midnight(),
                "honestyNote": "该来源未设每日条目配额；设置后到限只发布剩余名额，超出进入待处理计数，不静默丢弃。",
            }
        max_items = int(quota_row["max_items_per_day"])
        count_row = await self._db.fetch_one(
            "SELECT items, pending FROM api_intake_counts WHERE source_uuid = ? AND day_key = ?",
            (source_uuid, today),
        )
        used = int(count_row["items"]) if count_row is not None else 0
        pending = int(count_row["pending"]) if count_row is not None else 0
        return {
            "sourceUuid": source_uuid,
            "configured": True,
            "maxItemsPerDay": max_items,
            "used": used,
            "pending": pending,
            "remaining": max(0, max_items - used),
            "dayKey": today,
            "windowReset": next_local_midnight(),
            "updatedAt": str(quota_row["updated_at"]),
            "honestyNote": "到限后只发布剩余名额，超出条目计入待处理计数；请调高上限或等待次日窗口滚动。",
        }
