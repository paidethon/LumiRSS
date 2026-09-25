"""F064 AI 配额事前拦截 — 本地时区窗口的原子调用名额管理。

语义（诚实口径）：
- 未配置（window 为空或 max_calls=0）→ 不拦截；
- 已配置：调用前在服务端原子「检查+预占」一个名额（BEGIN IMMEDIATE
  串行化，并发下超额请求绝不到达上游）；预占即计数、失败不回退——
  与「失败请求也计数」一致，宁可保守多计，绝不漏计放行超额调用；
- 超额 → QuotaExceeded（429 quota_exceeded，带 retryAfter 秒数与
  windowReset ISO 时间，上游零请求）；
- 窗口按服务端本地时区滚动（day=本地自然日，month=本地自然月）。

全部 SQL 为内联字面量 + 绑定参数；写站点 1 处（claim 事务内）。
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from lumirss.db_tx import transaction

_QUOTA_READ_SQL = "SELECT calls FROM ai_usage WHERE window_key = ?"


class QuotaExceeded(Exception):
    """本窗口名额已用尽（映射 429 quota_exceeded）。"""

    def __init__(self, retry_after: int, window_reset: str, used: int) -> None:
        super().__init__(f"AI quota exceeded; retry after {retry_after}s.")
        self.retry_after = max(1, retry_after)
        self.window_reset = window_reset
        self.used = used


@dataclass(frozen=True)
class QuotaWindow:
    key: str
    start_iso: str
    reset_iso: str


def _now() -> datetime:
    """服务端本地时区当前时间（测试注入点）。"""
    return datetime.now().astimezone()


def window_bounds(now: datetime | None = None, window: str = "day") -> QuotaWindow:
    """本地时区窗口边界：key / 起点 ISO / 重置点 ISO。"""
    local = (now or _now()).astimezone()
    if window == "month":
        start = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        return QuotaWindow(
            key=f"month:{start.strftime('%Y-%m')}",
            start_iso=start.isoformat(timespec="seconds"),
            reset_iso=next_month.isoformat(timespec="seconds"),
        )
    # 默认按日窗口（含 window == "day"）
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return QuotaWindow(
        key=f"day:{start.strftime('%Y-%m-%d')}",
        start_iso=start.isoformat(timespec="seconds"),
        reset_iso=(start + timedelta(days=1)).isoformat(timespec="seconds"),
    )


async def claim_ai_call(db: Any, *, window: str, max_calls: int) -> QuotaWindow:
    """原子预占一个调用名额；超额 → QuotaExceeded。

    返回命中的窗口（调用方可记录口径）；BEGIN IMMEDIATE 保证并发下
    恰好 max_calls 个请求能通过。"""
    await db.migrate()
    bounds = window_bounds(window=window)

    def _claim(conn: Any) -> bool:
        # BEGIN IMMEDIATE 串行化写者：并发预占在同一写锁上排队，
        # 恰好 max_calls 个请求能通过（helper 成功后统一 COMMIT）。
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(_QUOTA_READ_SQL, (bounds.key,)).fetchone()
        current = int(row["calls"]) if row is not None else 0
        if current >= max_calls:
            return False
        if row is None:
            conn.execute(
                "INSERT INTO ai_usage (window_key, window_start, calls) VALUES (?, ?, 1)",
                (bounds.key, bounds.start_iso),
            )
        else:
            conn.execute(
                "UPDATE ai_usage SET calls = calls + 1 WHERE window_key = ?",
                (bounds.key,),
            )
        return True

    granted = await transaction(db, _claim)
    if not granted:
        raise QuotaExceeded(
            retry_after=_seconds_until(bounds.reset_iso),
            window_reset=bounds.reset_iso,
            used=max_calls,
        )
    return bounds


def _seconds_until(reset_iso: str) -> int:
    try:
        reset = datetime.fromisoformat(reset_iso)
    except ValueError:
        return 1
    return max(1, int((reset - _now()).total_seconds()) + 1)


async def usage_snapshot(db: Any, window: str, max_calls: int) -> dict[str, Any]:
    """GET /settings/ai/quota 的口径：当前窗口已用 / 剩余 / 重置时间。"""
    await db.migrate()
    bounds = window_bounds(window=window)
    row = await db.fetch_one(_QUOTA_READ_SQL, (bounds.key,))
    used = int(row["calls"]) if row is not None else 0
    remaining = max(0, max_calls - used)
    return {
        "window": window,
        "maxCalls": max_calls,
        "used": used,
        "remaining": remaining,
        "windowStart": bounds.start_iso,
        "windowReset": bounds.reset_iso,
        "retryAfter": _seconds_until(bounds.reset_iso),
    }


async def quota_denial(request: Any) -> Any:
    """路由侧守卫：已配置配额则原子预占；超额 → 429 JSONResponse。

    返回 None = 放行（含未配置）。响应体与 Retry-After 头都携带
    retryAfter / windowReset。

    N191：管理员策略上限在成员自设配置之后合成——更低者生效；
    成员未配置而管理员已设限时，管理员上限以 day 窗口单独生效
    （成员端没有任何路径可以提升它）。"""
    from fastapi.responses import JSONResponse

    from lumirss.ai_settings import (
        KEY_QUOTA_MAX_CALLS,
        KEY_QUOTA_WINDOW,
        AiSettingsStore,
    )

    db = request.app.state.db
    values = await AiSettingsStore(db).load()
    window = values[KEY_QUOTA_WINDOW]
    max_calls = int(values[KEY_QUOTA_MAX_CALLS] or "0")
    from lumirss.user_scope import current_user_id

    uid = current_user_id()
    if uid:
        from lumirss.user_quotas import effective_ai_limits

        window, max_calls = await effective_ai_limits(
            request.app.state.control_db, uid, window=window, max_calls=max_calls
        )
    if not window or max_calls <= 0:
        return None
    try:
        await claim_ai_call(db, window=window, max_calls=max_calls)
    except QuotaExceeded as exc:
        return JSONResponse(
            status_code=429,
            headers={"Retry-After": str(exc.retry_after)},
            content={
                "error": {
                    "type": "quota_exceeded",
                    "message": (
                        "AI 用量已达本窗口上限，"
                        f"{exc.retry_after} 秒后（{exc.window_reset}）重置。"
                    ),
                    "retryAfter": exc.retry_after,
                    "windowReset": exc.window_reset,
                }
            },
        )
    return None
