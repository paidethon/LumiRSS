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
- FIX-218 作用域绑定：令牌铸造时必须声明 (operation, targetUserId)，
  消费时逐字匹配同一作用域串——为「重置 A 的密码」确认的密码证明
  绝不能顺带授权「改 B 的角色」。跨操作/跨目标的令牌复用一律 403；
  旧的无作用域令牌（operation 为 NULL）永不匹配，默认拒绝；
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

# FIX-218：允许声明的作用域操作（与 admin 路由的守卫调用一一对应）。
# 新敏感操作必须同时登记在这里与对应路由的 require_step_up 调用处。
STEP_UP_OPERATIONS: tuple[str, ...] = (
    "user_role_change",
    "user_paused",
    "user_active",
    "user_password_reset",
    "user_quota_set",
    # NEW-304：webhook 签名钥轮换（实例级操作，target = 操作管理员本人
    # id —— 作用域仍逐字绑定，令牌不能转投其他敏感操作）。
    "webhook_key_rotation",
    # NEW-371..380 运行治理组：实例级敏感操作一律 target=操作管理员
    # 本人（与 webhook_key_rotation 同口径；作用域逐字绑定）。
    "task_kind_pause",
    "maintenance_schedule",
    "quota_batch_execute",
    "config_draft_apply",
    "handoff_export",
)

STEP_UP_OP_PATTERN = "^(?:" + "|".join(STEP_UP_OPERATIONS) + ")$"


def step_up_scope(operation: str, target_user_id: str | None) -> str:
    """(operation, target-resource) → 存库/比对的作用域串。"""
    return f"{operation}:{target_user_id}" if target_user_id else operation


class StepUpDenied(Exception):
    """铸造失败（密码错误）→ 400 invalid_credentials 口径。"""


def _expiry() -> str:
    return (
        datetime.now(UTC) + timedelta(minutes=STEP_UP_TTL_MINUTES)
    ).isoformat(timespec="seconds")


async def mint_step_up_token(
    db: Any, user_id: str, password: str, operation: str, target_user_id: str | None = None
) -> dict[str, Any] | None:
    """验证管理员密码并铸造**作用域绑定**的一次性令牌；密码错 → None。

    令牌的 ``operation`` 列存 (operation, target) 合成作用域串；消费端
    必须用同一作用域串才可能命中。"""
    from lumirss.accounts_store import verify_password_hash

    if operation not in STEP_UP_OPERATIONS:
        raise ValueError(f"Unknown step-up operation: {operation}.")
    await db.migrate()
    row = await db.fetch_one(
        "SELECT password_hash FROM users WHERE id = ?", (user_id,)
    )
    if row is None or not verify_password_hash(password, row["password_hash"]):
        return None
    token = secrets.token_urlsafe(_TOKEN_BYTES)
    now = utc_now()
    await db.execute(
        "INSERT INTO admin_step_up_tokens (token_hash, user_id, operation, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
        (hash_token(token), user_id, step_up_scope(operation, target_user_id), now, _expiry()),
    )
    return {
        "token": token,
        "operation": operation,
        "targetUserId": target_user_id,
        "expiresInMinutes": STEP_UP_TTL_MINUTES,
        "expiresAt": _expiry(),
    }


async def consume_step_up_token(
    db: Any, token: str | None, user_id: str, operation: str, target_user_id: str | None = None
) -> bool:
    """单次消费：存在 + 属于该管理员 + **作用域逐字匹配** + 未用过 +
    未过期才放行。

    一条 UPDATE 完成「校验 + 作废」，重放并发也只会成功一次。
    （rowcount 经事务回调读取——Database.execute 只回 lastrowid。）
    NULL operation 的旧格式令牌永不匹配任何要求的作用域——默认拒绝。"""
    if not token:
        return False

    import sqlite3

    from lumirss.db_tx import transaction

    scope = step_up_scope(operation, target_user_id)

    def _tx(conn: sqlite3.Connection) -> bool:
        cursor = conn.execute(
            "UPDATE admin_step_up_tokens SET used_at = ? WHERE token_hash = ? AND user_id = ? AND operation IS ? AND used_at IS NULL AND expires_at > ?",
            (utc_now(), hash_token(token), user_id, scope, utc_now()),
        )
        return bool(cursor.rowcount)

    return bool(await transaction(db, _tx))


def step_up_required_response(
    operation: str, target_user_id: str | None = None
) -> dict[str, Any]:
    """403 step_up_required 错误体（提示如何铸造**匹配作用域**的令牌）。"""
    body: dict[str, Any] = {
        "error": {
            "type": "step_up_required",
            "message": "该操作需要临时提权：先 POST /api/v1/admin/step-up"
            "（声明 operation 与 targetUserId），"
            f"再携带 {STEP_UP_HEADER} 头重试。",
            "operation": operation,
        }
    }
    if target_user_id is not None:
        body["error"]["targetUserId"] = target_user_id
    return body


async def require_step_up(
    request: Any,
    principal: dict[str, str] | None,
    operation: str,
    target_user_id: str | None = None,
) -> Any:
    """敏感路由的守卫：令牌有效且作用域匹配 → None（放行）；否则 403。

    用法（admin 路由内，_require_admin 之后）::

        denial = await require_step_up(
            request, principal, "user_role_change", user_id
        )
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
    ok = await consume_step_up_token(db, token, user_id, operation, target_user_id)
    if not ok:
        return JSONResponse(
            status_code=403,
            content=step_up_required_response(operation, target_user_id),
            headers={"Cache-Control": "no-store"},
        )
    return None
