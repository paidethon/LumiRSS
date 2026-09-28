"""NEW-210 来源抓取停机计划 —— per-feed 暂停区间的校验、存储与判定。

窗口形态：``start_at``（UTC Z 串，缺省 = 现在）到 ``end_at``（UTC Z 串，
可为 NULL = 开放式，直到用户显式取消）。

- 校验：feed_url 非空（≤2048）；reason ≤200；时刻必须是可解析的
  RFC3339 形态（归一为 UTC「Z」串）；同时给出 start/end 时要求
  start < end；
- 「生效中」谓词（:func:`is_active`）：status='active' 且
  ``start_at <= now`` 且（``end_at IS NULL`` 或 ``now < end_at``）；
  同一来源允许多条计划（历史保留），任一生效即视为暂停；
- 取消是 set 语义（active → cancelled），行永不删除；已取消的计划
  再次取消 → 稳定 409（不是幂等 204——重复取消是调用方状态陈旧的
  信号，如实报告）。

诚实边界（模块存在的理由，与 source_freshness 同一口径）：FreshRSS
的抓取调度粒度由实例 CRON_MIN 决定，greader API 不提供 per-feed 暂停。
本计划在 Lumi 侧的可消费面：本 store 的 :func:`paused_feed_urls` +
``/api/v1/new210/pauses/active`` 机器可读端点 + 本组表面（NEW-202
观察列表 / NEW-206 日历）对暂停来源如实标注「抓取暂停中」。绝不伪装
成「已停止 FreshRSS 抓取」；逐源调度需在 FreshRSS 原生界面调整。
"""

import uuid as _uuid
from typing import Any

from lumirss.source_overrides import canonical_utc
from lumirss.storage import Database
from lumirss.util import utc_now

MAX_FEED_URL = 2048
MAX_REASON = 200


class PausePlanInvalid(ValueError):
    """计划非法（URL/时刻/区间），路由层映射 422。"""


class PausePlanNotFound(Exception):
    """计划不存在 —— 404 pause_plan_not_found。"""


class PausePlanAlreadyCancelled(Exception):
    """计划已取消，再次取消 —— 409 pause_plan_already_cancelled。"""


def validate_plan_input(
    *,
    feed_url: Any,
    reason: Any,
    start_at: Any,
    end_at: Any,
    open_ended: Any,
    now: str | None = None,
) -> dict[str, Any]:
    """校验并归一化计划输入（非法 raise PausePlanInvalid → 422）。

    返回 {feed_url, reason, start_at, end_at}（UTC Z 串口径）。
    ``end_at`` 缺省语义：``open_ended=True`` → NULL（直到取消）；
    两者都缺席 → 422（必须声明恢复时间或显式开放式，不允许含糊）。
    """
    clean_url = str(feed_url or "").strip()
    if not clean_url:
        raise PausePlanInvalid("feedUrl 不能为空。")
    if len(clean_url) > MAX_FEED_URL:
        raise PausePlanInvalid(f"feedUrl 过长（≤{MAX_FEED_URL} 字符）。")
    clean_reason: str | None = None
    if reason is not None and str(reason).strip():
        clean_reason = str(reason).strip()
        if len(clean_reason) > MAX_REASON:
            raise PausePlanInvalid(f"reason 过长（≤{MAX_REASON} 字符）。")
    start = canonical_utc(start_at) if start_at else (now or utc_now())
    if start is None:
        raise PausePlanInvalid("startAt 必须是可解析的 ISO 时刻。")
    if open_ended and end_at:
        raise PausePlanInvalid("endAt 与 openEnded 只能二选一。")
    if open_ended:
        end = None
    else:
        if not end_at:
            raise PausePlanInvalid(
                "必须提供 endAt（恢复时间）或显式 openEnded=true（直到取消）。"
            )
        end = canonical_utc(end_at)
        if end is None:
            raise PausePlanInvalid("endAt 必须是可解析的 ISO 时刻。")
        if end <= start:
            raise PausePlanInvalid("endAt 必须晚于 startAt。")
    return {
        "feed_url": clean_url,
        "reason": clean_reason,
        "start_at": start,
        "end_at": end,
    }


def _field(plan: dict[str, Any], snake: str, camel: str) -> Any:
    """计划 dict 兼容 store 内部（snake）与 API 视图（camel）两种键。"""
    return plan[snake] if snake in plan else plan[camel]


def is_active(plan: dict[str, Any], *, now: str | None = None) -> bool:
    """生效中谓词（见模块 docstring；纯函数，now 可注入）。

    接受 store 行（snake_case）或 API 视图（camelCase）两种键形态。"""
    if str(_field(plan, "status", "status")) != "active":
        return False
    moment = now or utc_now()
    if str(_field(plan, "start_at", "startAt")) > moment:
        return False
    end = _field(plan, "end_at", "endAt")
    return end is None or str(end) > moment


def _row_to_plan(row: Any) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "feedUrl": str(row["feed_url"]),
        "reason": row["reason"],
        "startAt": str(row["start_at"]),
        "endAt": row["end_at"],
        "status": str(row["status"]),
        "cancelledAt": row["cancelled_at"],
        "createdAt": str(row["created_at"]),
    }


class PausePlanStore:
    """SQL 唯一入口；inline literal at each execute site（repo 约定）。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(self, plan: dict[str, Any]) -> dict[str, Any]:
        now = utc_now()
        plan_id = str(_uuid.uuid4())
        await self._db.migrate()
        await self._db.execute(
            "INSERT INTO new210_pause_plans"
            " (id, feed_url, reason, start_at, end_at, status, created_at)"
            " VALUES (?, ?, ?, ?, ?, 'active', ?)",
            (
                plan_id,
                plan["feed_url"],
                plan["reason"],
                plan["start_at"],
                plan["end_at"],
                now,
            ),
        )
        return {
            "id": plan_id,
            "feedUrl": plan["feed_url"],
            "reason": plan["reason"],
            "startAt": plan["start_at"],
            "endAt": plan["end_at"],
            "status": "active",
            "cancelledAt": None,
            "createdAt": now,
        }

    async def list_plans(self, *, now: str | None = None) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, feed_url, reason, start_at, end_at, status, cancelled_at,"
            " created_at FROM new210_pause_plans"
            " ORDER BY created_at DESC, id DESC LIMIT 200",
            (),
        )
        plans = [_row_to_plan(row) for row in rows]
        for plan in plans:
            plan["activeNow"] = is_active(plan, now=now)
        return plans

    async def get(self, plan_id: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, feed_url, reason, start_at, end_at, status, cancelled_at,"
            " created_at FROM new210_pause_plans WHERE id = ?",
            (plan_id,),
        )
        return _row_to_plan(row) if row is not None else None

    async def cancel(self, plan_id: str) -> dict[str, Any]:
        """取消（set 语义）。不存在 → PausePlanNotFound；已取消 →
        PausePlanAlreadyCancelled（409，诚实于调用方状态陈旧）。"""
        plan = await self.get(plan_id)
        if plan is None:
            raise PausePlanNotFound(plan_id)
        if plan["status"] != "active":
            raise PausePlanAlreadyCancelled(plan_id)
        await self._db.execute(
            "UPDATE new210_pause_plans SET status = 'cancelled',"
            " cancelled_at = ? WHERE id = ? AND status = 'active'",
            (utc_now(), plan_id),
        )
        updated = await self.get(plan_id)
        assert updated is not None  # 行刚被本连接更新过
        return updated

    async def delete(self, plan_id: str) -> bool:
        """删除一条计划行（housekeeping；返回是否真的删了）。"""
        await self._db.migrate()
        changed = await self._db.execute(
            "DELETE FROM new210_pause_plans WHERE id = ?", (plan_id,)
        )
        return bool(changed)

    async def paused_feed_urls(self, *, now: str | None = None) -> list[str]:
        """当前处于暂停区间的去重 feed URL 列表（本组表面的消费点）。"""
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT feed_url, start_at, end_at, status FROM new210_pause_plans"
            " WHERE status = 'active' ORDER BY start_at ASC LIMIT 500",
            (),
        )
        moment = now or utc_now()
        seen: list[str] = []
        for row in rows:
            plan = {
                "status": str(row["status"]),
                "start_at": str(row["start_at"]),
                "end_at": row["end_at"],
            }
            if is_active(plan, now=moment) and str(row["feed_url"]) not in seen:
                seen.append(str(row["feed_url"]))
        return seen

