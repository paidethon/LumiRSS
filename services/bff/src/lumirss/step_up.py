"""N009 管理员临时提权（step-up auth）—— 敏感管理操作的第二道门。

威胁模型：管理员会话被借用/劫持时，普通浏览（用户列表、邀请漏斗）
不受影响；任何改变他人账户状态的操作（角色变更、暂停/恢复、配额
设置、成员密码重置）都要求管理员**在本会话内重新证明自己知道密码**
—— POST /admin/step-up 铸造一个短时令牌（5 分钟，散列入库，单次
使用），敏感路由校验 ``X-Lumi-Step-Up`` 头。

硬性质：
- 令牌只存 SHA-256 散列（token_hash）；明文只在铸造响应里出现一次；
- 消费是原子的单次语义（UPDATE ... WHERE used_at IS NULL AND
  expires_at > now）——重放/过期/他人令牌一律 403 step_up_required；
- 非管理员铸造请求按普通 403 forbidden 拒绝（member 无法造令牌）；
- 审计只记 mint/denied 动作与用户 id，绝不记令牌或密码。
"""

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from lumirss.token_hash import hash_token
from lumirss.util import utc_now

STEP_UP_HEADER = "X-Lumi-Step-Up"
STEP_UP_TTL_MINUTES = 5
_TOKEN_BYTES = 32


class StepUpDenied(Exception):
    """铸造失败（密码错误）→ 400 invalid_credentials 口径。"""


def _expiry() -> str:
    return (
        datetime.now(UTC) + timedelta(minutes=STEP_UP_TTL_MINUTES)
    ).isoformat(timespec="seconds")


async def mint_step_up_token(db: Any, user_id: str, password: str) -> dict[str, Any] | None:
    """验证管理员密码并铸造一次性令牌；密码错 → None（调用方 400）。"""
    from lumirss.accounts_store import verify_password_hash

    await db.migrate()
    row = await db.fetch_one(
        "SELECT password_hash FROM users WHERE id = ?", (user_id,)
    )
    if row is None or not verify_password_hash(password, row["password_hash"]):
        return None
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    now = utc_now()
    await db.execute(
        "INSERT INTO admin_step_up_tokens (token_hash, user_id, operation, created_at, expires_at) VALUES (?, ?, NULL, ?, ?)",
        (hash_token(token), user_id, now, _expiry()),
    )
    return {
        "token": token,
        "expiresInMinutes": STEP_UP_TTL_MINUTES,
        "expiresAt": _expiry(),
    }


async def consume_step_up_token(
    db: Any, token: str | None, user_id: str
) -> bool:
    """单次消费：存在 + 属于该管理员 + 未用过 + 未过期才放行。

    一条 UPDATE 完成「校验 + 作废」，重放并发也只会成功一次。
    （rowcount 经事务回调读取——Database.execute 只回 lastrowid。）"""
    if not token:
        return False

    import sqlite3

    from lumirss.db_tx import transaction

    def _tx(conn: sqlite3.Connection) -> bool:
        cursor = conn.execute(
            "UPDATE admin_step_up_tokens SET used_at = ? WHERE token_hash = ? AND user_id = ? AND used_at IS NULL AND expires_at > ?",
            (utc_now(), hash_token(token), user_id, utc_now()),
        )
        return bool(cursor.rowcount)

    return bool(await transaction(db, _tx))


def step_up_required_response(operation: str) -> dict[str, Any]:
    """403 step_up_required 错误体（提示如何铸造令牌）。"""
    return {
        "error": {
            "type": "step_up_required",
            "message": "该操作需要临时提权：先 POST /api/v1/admin/step-up，"
            f"再携带 {STEP_UP_HEADER} 头重试。",
            "operation": operation,
        }
    }


async def require_step_up(
    request: Any, principal: dict[str, str] | None, operation: str
) -> Any:
    """敏感路由的守卫：令牌有效 → None（放行）；否则 403 JSONResponse。

    用法（admin 路由内，_require_admin 之后）::

        denial = await require_step_up(request, principal, "user_role_change")
        if denial is not None:
            return denial
    """
    from fastapi.responses import JSONResponse

    from lumirss.user_scope import principal_of

    if principal is None:
        principal = principal_of(request.scope)
    user_id = str((principal or {}).get("user_id") or "")
    db = request.app.state.control_db
    token = request.headers.get(STEP_UP_HEADER)
    ok = await consume_step_up_token(db, token, user_id)
    if not ok:
        return JSONResponse(
            status_code=403,
            content=step_up_required_response(operation),
            headers={"Cache-Control": "no-store"},
        )
    return None
