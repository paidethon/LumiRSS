"""N191/N193 每账户策略行 — 控制库 user_quotas 的唯一读写口。

N191 用户额度策略包：管理员为单个成员设置策略上限
``caps = {"maxSources": int, "aiQuotaPerDay": int}``（键可缺省 =
未设限），成员端没有任何写路径（不能自助提升）。执行点全部在
服务端：

- 订阅（routers/subscriptions.py）：按投影 ``search_feeds`` 计数，
  第 N+1 个来源 → 429 quota_exceeded（上游零请求）；
- AI 配额咨询（ai_quota.quota_denial / GET settings/ai/quota）：
  管理员日上限与成员自设上限取更小者；成员未配置时管理员上限
  单独生效（day 窗口）。

N193 单用户后台任务暂停：同一行携带 ``background_paused`` /
``background_pause_reason``——AccountsStore.active_user_ids() 据此
把被暂停成员从所有后台循环（for_each_active_user）排除；登录与
阅读不受影响。

全部 SQL 为内联字面量 + 绑定参数；写站点集中在 store 内
（set_caps / clear_caps / set_background_pause 三处，事务内
SELECT-then-INSERT/UPDATE，无 UPSERT）。
"""

import json
import time

from lumirss.db_tx import transaction

# 策略上限的合理边界：0 与负数一律拒绝（未设限 = 键缺省，不是 0）。
MAX_SOURCES_CAP = 10_000
MAX_AI_DAILY_CAP = 100_000
MAX_REASON_LENGTH = 200

_CAP_KEYS = ("maxSources", "aiQuotaPerDay")


class QuotaPolicyError(Exception):
    """策略体不合法（稳定 400 invalid_request）。"""


def _now() -> int:
    return int(time.time())


def _normalize_caps(caps: dict[str, object]) -> dict[str, int]:
    """校验 + 归一 caps：只认两个已知键，正整数，其余键拒绝。"""
    clean: dict[str, int] = {}
    for key, value in caps.items():
        if key not in _CAP_KEYS:
            raise QuotaPolicyError(f"Unknown quota cap: {key}.")
        if isinstance(value, bool) or not isinstance(value, int):
            raise QuotaPolicyError(f"{key} must be an integer.")
        limit = int(value)
        ceiling = MAX_SOURCES_CAP if key == "maxSources" else MAX_AI_DAILY_CAP
        if limit < 1 or limit > ceiling:
            raise QuotaPolicyError(f"{key} must be between 1 and {ceiling}.")
        clean[key] = limit
    return clean


def _parse_caps(raw: object) -> dict[str, int]:
    try:
        data = json.loads(str(raw or "{}"))
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    result: dict[str, int] = {}
    for key in _CAP_KEYS:
        value = data.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            result[key] = value
    return result


class UserQuotaStore:
    """All user_quotas SQL lives here (control DB, inline literals)."""

    def __init__(self, database) -> None:
        self._db = database

    async def get_row(self, user_id: str) -> dict[str, object] | None:
        """策略行原文（caps 已解析；无行 = None = 一切未设限）。"""
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT user_id, caps, background_paused, background_pause_reason,"
            " updated_by, updated_at FROM user_quotas WHERE user_id = ?",
            (user_id,),
        )
        if row is None:
            return None
        data = dict(row)
        data["caps"] = _parse_caps(data.get("caps"))
        data["background_paused"] = bool(data.get("background_paused"))
        return data

    async def caps_for(self, user_id: str) -> dict[str, int]:
        """只取已设上限（热路径：订阅 / AI 配额咨询）。"""
        await self._db.migrate()
        row = await self._db.fetch_one("SELECT caps FROM user_quotas WHERE user_id = ?", (user_id,))
        return _parse_caps(row["caps"]) if row else {}

    async def set_caps(self, *, user_id: str, caps: dict[str, object], updated_by: str) -> dict[str, int]:
        """写入策略上限（缺省键 = 清除该上限；保留 N193 后台标志）。"""
        clean = _normalize_caps(caps)
        await self._db.migrate()
        now = _now()

        def _write(conn) -> None:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT caps FROM user_quotas WHERE user_id = ?", (user_id,)).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO user_quotas (user_id, caps, updated_by, updated_at)"
                    " VALUES (?, ?, ?, ?)",
                    (user_id, json.dumps(clean), updated_by, now),
                )
            else:
                conn.execute(
                    "UPDATE user_quotas SET caps = ?, updated_by = ?, updated_at = ?"
                    " WHERE user_id = ?",
                    (json.dumps(clean), updated_by, now, user_id),
                )

        await transaction(self._db, _write)
        return clean

    async def clear_caps(self, *, user_id: str, updated_by: str) -> bool:
        """清除策略上限（N193 后台标志保留——两者生命周期独立）。"""
        await self._db.migrate()
        now = _now()
        cursor = await self._db.execute(
            "UPDATE user_quotas SET caps = '{}', updated_by = ?, updated_at = ? WHERE user_id = ?",
            (updated_by, now, user_id),
        )
        return bool(cursor)

    async def set_background_pause(self, *, user_id: str, paused: bool, reason: str | None) -> bool:
        """N193 后台暂停/恢复（恢复清空原因）；行不存在则创建空策略行。"""
        await self._db.migrate()
        now = _now()
        clean_reason = None
        if paused and reason:
            clean_reason = reason.strip()[:MAX_REASON_LENGTH] or None

        def _write(conn) -> None:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT user_id FROM user_quotas WHERE user_id = ?", (user_id,)).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO user_quotas (user_id, caps, background_paused,"
                    " background_pause_reason, updated_at) VALUES (?, '{}', ?, ?, ?)",
                    (user_id, 1 if paused else 0, clean_reason, now),
                )
            else:
                conn.execute(
                    "UPDATE user_quotas SET background_paused = ?,"
                    " background_pause_reason = ?, updated_at = ? WHERE user_id = ?",
                    (1 if paused else 0, clean_reason, now, user_id),
                )

        await transaction(self._db, _write)
        return True

    async def background_paused_ids(self) -> set[str]:
        """被后台暂停的成员集合（诊断/测试用；主路径走 active_user_ids）。"""
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT user_id FROM user_quotas WHERE background_paused = 1", ()
        )
        return {str(r["user_id"]) for r in rows}


async def admin_ai_daily_cap(control_db, user_id: str) -> int | None:
    """管理员为该成员设置的 AI 日上限（未设 = None）。"""
    caps = await UserQuotaStore(control_db).caps_for(user_id)
    return caps.get("aiQuotaPerDay")


async def effective_ai_limits(
    control_db, user_id: str, *, window: str, max_calls: int
) -> tuple[str, int]:
    """F064 口径 + N191 管理员上限合成。

    管理员日上限只在更低时收窄（“overrides user-set if lower”）；
    成员完全未配置而管理员已设限 → 管理员上限以 day 窗口单独生效。
    返回 (window, max_calls)，未设限时保持原值（0 = 不拦截）。
    """
    admin_cap = await admin_ai_daily_cap(control_db, user_id)
    if admin_cap is None:
        return window, max_calls
    if not window or max_calls <= 0:
        return "day", admin_cap
    if admin_cap < max_calls:
        return window, admin_cap
    return window, max_calls
