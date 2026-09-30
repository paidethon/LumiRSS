"""Admin users responsibility slice (FIX-161): the operator's account
lifecycle power — step-up minting (N009), user listing, pause/resume
(O152), owner-only role provisioning, session revocation, password
reset (O150), per-user quota policy packages (N191) and per-user
background-task pause (N193). Routes moved verbatim from the former
``routers/admin.py`` monolith.
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.accounts_store import hash_password
from lumirss.auth_store import AuthStore
from lumirss.routers.admin._common import (
    _NO_STORE,
    _accounts,
    _forbid,
    _iso,
    _require_admin,
    _require_owner,
)
from lumirss.step_up import (
    STEP_UP_OP_PATTERN,
    STEP_UP_TTL_MINUTES,
    mint_step_up_token,
    require_step_up,
)

router = APIRouter()


class UserRoleRequest(BaseModel):
    """POST /admin/users/{id}/role — owner-only provisioning body.

    Anything outside ``member``/``admin`` (including ``owner`` — there is
    exactly one owner and it is never assignable through the API) is a
    validation error (422)."""

    role: str = Field(pattern="^(member|admin)$")


class AdminStepUpRequest(BaseModel):
    """POST /admin/step-up（N009）——管理员本会话内重新证明自己。

    FIX-218：令牌铸造时必须声明作用域 (operation, targetUserId)——
    消费端逐字匹配，为某一操作/目标确认的密码证明不能转投其他敏感
    操作或其他目标账户。"""

    password: str = Field(min_length=1, max_length=256)
    operation: str = Field(pattern=STEP_UP_OP_PATTERN)
    targetUserId: str = Field(min_length=1, max_length=64)


@router.post("/step-up", response_model=None, response_model_exclude_none=True)
async def admin_step_up(body: AdminStepUpRequest, request: Request) -> JSONResponse:
    """N009：铸造短时提权令牌（5 分钟，散列入库，单次使用）。

    - 仅 owner/admin 可铸造（member 永远 403，无法伪造提权）；
    - 校验的是当前管理员自己的密码（不是目标用户的）；
    - FIX-218：令牌绑定 (operation, targetUserId)——与敏感路由要求的
      作用域逐字匹配才会被消费；跨操作/跨目标复用一律 403；
    - 审计只记 mint 动作 + 用户 id + 作用域——令牌与密码绝不入日志。"""
    principal = await _require_admin(request)
    if principal is None:
        return _forbid()
    accounts = _accounts(request)
    try:
        minted = await mint_step_up_token(
            request.app.state.control_db,
            principal["user_id"],
            body.password,
            body.operation,
            body.targetUserId,
        )
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={"error": {"type": "invalid_request", "message": "Unknown step-up operation."}},
            headers=_NO_STORE,
        )
    if minted is None:
        await accounts.audit(
            actor=principal["user_id"],
            action="admin_step_up_mint_failed",
            object_type="step_up",
            object_id=principal["user_id"],
            outcome="denied",
        )
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "type": "invalid_credentials",
                    "message": "密码不正确。",
                }
            },
            headers=_NO_STORE,
        )
    await accounts.audit(
        actor=principal["user_id"],
        action="admin_step_up_mint",
        object_type="step_up",
        object_id=principal["user_id"],
        detail=f"{body.operation}:{body.targetUserId}",
    )
    return {
        "token": minted["token"],
        "expiresInMinutes": STEP_UP_TTL_MINUTES,
        "header": "X-Lumi-Step-Up",
    }


@router.get("/users", response_model=None, response_model_exclude_none=True)
async def list_users(request: Request) -> JSONResponse:
    if await _require_admin(request) is None:
        return _forbid()
    return await _accounts(request).list_users()


@router.post("/users/{user_id}/pause", response_model=None, response_model_exclude_none=True)
async def pause_user(user_id: str, request: Request) -> JSONResponse:
    return await _set_member_status(user_id, request, "paused")


@router.post("/users/{user_id}/resume", response_model=None, response_model_exclude_none=True)
async def resume_user(user_id: str, request: Request) -> JSONResponse:
    return await _set_member_status(user_id, request, "active")


@router.post("/users/{user_id}/role", response_model=None, response_model_exclude_none=True)
async def set_user_role(user_id: str, body: UserRoleRequest, request: Request) -> JSONResponse:
    """Owner-only role provisioning (0067).

    Activation admits everyone as ``member``; ONLY the owner can grant or
    revoke the ``admin`` role afterwards. Rules, all stable-shaped:
    - admins get 403 (an admin can never mint or demote another admin);
    - the owner account is untargetable (403) — no demotion, no re-role;
    - demoting the last active admin is refused (403) so a delegation
      mistake can never lock the operator out of admin surfaces;
    - unknown user → 404, unknown role → 422 (body validation);
    - every accepted change is audited (no credentials involved).
    - N009：需要临时提权令牌（X-Lumi-Step-Up），否则 403 step_up_required。"""
    principal = _require_owner(request)
    if principal is None:
        return _forbid("Owner role required.")
    accounts = _accounts(request)
    user = await accounts.get_user(user_id)
    if user is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "user_not_found", "message": "No such member."}},
            headers=_NO_STORE,
        )
    # N009：临时提权在 404 之后、任何状态变更之前（404 语义不变）。
    # FIX-218：提权令牌绑定 (操作, 目标账户)。
    denial = await require_step_up(request, principal, "user_role_change", user_id)
    if denial is not None:
        return denial
    if user["role"] == "owner":
        return _forbid("The owner account role cannot be changed.")
    if user["role"] == "admin" and body.role == "member" and user["status"] == "active":
        active_admins = await accounts.count_active_admins()
        if active_admins <= 1:
            return _forbid("Cannot demote the last active administrator.")
    changed = await accounts.set_user_role(user_id, body.role)
    if not changed:
        return JSONResponse(
            status_code=409,
            content={"error": {"type": "conflict", "message": "Role change did not apply (concurrent update?)."}},
            headers=_NO_STORE,
        )
    await accounts.audit(actor=principal["user_id"], action="user_role_change", object_type="user", object_id=user_id, detail=body.role)
    return {"id": user_id, "role": body.role}


async def _set_member_status(user_id: str, request: Request, status: str) -> JSONResponse:
    """Pause/resume with the two hard guards (O152): the owner account
    can never be targeted, and the last active admin cannot be paused.
    N009：需要临时提权令牌（X-Lumi-Step-Up）。"""
    principal = await _require_admin(request)
    if principal is None:
        return _forbid()
    accounts = _accounts(request)
    user = await accounts.get_user(user_id)
    if user is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "user_not_found", "message": "No such member."}},
            headers=_NO_STORE,
        )
    # N009：临时提权在 404 之后、任何状态变更之前（404 语义不变）。
    # FIX-218：提权令牌绑定 (操作, 目标账户)。
    denial = await require_step_up(request, principal, f"user_{status}", user_id)
    if denial is not None:
        return denial
    if user["role"] == "owner":
        return _forbid("The owner account cannot be paused or resumed here.")
    if status == "paused" and user["role"] == "admin" and user["status"] == "active":
        active_admins = await accounts.count_active_admins()
        if active_admins <= 1:
            return _forbid("Cannot pause the last active administrator.")
    changed = await accounts.set_user_status(user_id, status)
    if not changed:
        return JSONResponse(
            status_code=409,
            content={"error": {"type": "conflict", "message": "Status change did not apply (concurrent update?)."}},
            headers=_NO_STORE,
        )
    if status == "paused":
        await AuthStore(request.app.state.control_db).revoke_all_sessions(user_id=user_id)
    await accounts.audit(actor=principal["user_id"], action=f"user_{status}", object_type="user", object_id=user_id)
    return {"id": user_id, "status": status}


@router.post("/users/{user_id}/revoke-sessions", response_model=None, response_model_exclude_none=True)
async def revoke_user_sessions(user_id: str, request: Request) -> JSONResponse:
    principal = await _require_admin(request)
    if principal is None:
        return _forbid()
    user = await _accounts(request).get_user(user_id)
    if user is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "user_not_found", "message": "No such member."}},
            headers=_NO_STORE,
        )
    await AuthStore(request.app.state.control_db).revoke_all_sessions(user_id=user_id)
    await _accounts(request).audit(actor=principal["user_id"], action="user_revoke_sessions", object_type="user", object_id=user_id)
    return {"id": user_id, "sessionsRevoked": True}


@router.post("/users/{user_id}/reset-password", response_model=None, response_model_exclude_none=True)
async def reset_user_password(user_id: str, request: Request) -> JSONResponse:
    """Install an unguessable password (nobody knows it) and revoke all
    the user's sessions, then return a one-time recovery invite the
    operator hands to the member (O150 — honest, no email pretending).
    N009：需要临时提权令牌（X-Lumi-Step-Up）。"""
    principal = await _require_admin(request)
    if principal is None:
        return _forbid()
    accounts = _accounts(request)
    user = await accounts.get_user(user_id)
    if user is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "user_not_found", "message": "No such member."}},
            headers=_NO_STORE,
        )
    denial = await require_step_up(request, principal, "user_password_reset", user_id)
    if denial is not None:
        return denial
    # D-03：与其他 owner-targetable 端点同语义——owner 账号不可作为密码
    # 重置目标（403）。否则敌意 admin 可借重置链接接管 owner 身份；
    # owner 自己的密码走自助/恢复通道，不经本端点。
    if user["role"] == "owner":
        return _forbid("The owner account password cannot be reset here.")
    import secrets as _secrets

    await accounts.set_password_hash(user_id, hash_password(_secrets.token_urlsafe(24)))
    await AuthStore(request.app.state.control_db).revoke_all_sessions(user_id=user_id)
    raw, invite = await accounts.create_invite(
        created_by=principal["user_id"],
        ttl_hours=24,
        kind="recovery",
        target_user=user_id,
        label="password reset",
    )
    await accounts.audit(actor=principal["user_id"], action="user_password_reset", object_type="user", object_id=user_id)
    return {"id": user_id, "recoveryToken": raw, "invite": invite}


# ---------------------------------------------------------------------------
# N191 用户额度策略包 + N193 单用户后台任务暂停。
#
# 策略行（control DB user_quotas）的唯一管理面。执行全部在服务端：
# 订阅上限在 routers/subscriptions.py 事前拦截（429 quota_exceeded），
# AI 上限在 ai_quota.quota_denial 与 GET settings/ai/quota 合成（更低者
# 生效）；成员没有任何写路径（本节端点全部 admin-gated），也不能通过
# 自设 AI 配置绕过——合成取 min。N193 的 background_paused 由
# AccountsStore.active_user_ids() 读取，所有 for_each_active_user 后台
# 循环在源头跳过被暂停成员；登录与阅读不受影响。


class UserQuotaPutRequest(BaseModel):
    """PUT /admin/users/{id}/quota body。缺省键 = 清除该上限；
    正整数（1..上限界）才是有效设置。未知键 → 422。

    FIX-039：字段类型 strict int——JSON 布尔不得经 lax 强转伪装成
    1/0（store 层 _normalize_caps 拒绝 bool，两层校验必须同一契约；
    0 本身被 ge=1 拒绝，「未设限」只是键缺省，与 0 可区分）。"""

    maxSources: int | None = Field(default=None, ge=1, le=10_000, strict=True)
    aiQuotaPerDay: int | None = Field(default=None, ge=1, le=100_000, strict=True)


class BackgroundPauseRequest(BaseModel):
    """POST /admin/users/{id}/background-pause body。原因必填——
    「为什么他的后台任务停了」必须留下人读答案（同步落 audit_log）。"""

    reason: str = Field(min_length=1, max_length=200)


def _quota_json(row: dict[str, object] | None, user_id: str) -> dict[str, object]:
    if row is None:
        caps: dict[str, object] = {}
        paused = False
        pause_reason = None
        updated_at = None
        updated_by = None
    else:
        caps = dict(row.get("caps") or {})
        paused = bool(row.get("background_paused"))
        pause_reason = row.get("background_pause_reason")
        updated_at = row.get("updated_at")
        updated_by = row.get("updated_by")
    return {
        "userId": user_id,
        "caps": caps,
        "backgroundPaused": paused,
        "backgroundPauseReason": pause_reason,
        "updatedAt": _iso(int(updated_at)) if isinstance(updated_at, int) and updated_at > 0 else None,
        "updatedBy": str(updated_by) if updated_by else None,
    }


async def _quota_target(user_id: str, request: Request) -> JSONResponse | dict[str, object]:
    """共享前置：admin gate + 目标存在性（404）；不限制 owner——
    读策略行对任何账户都无副作用。返回 error JSONResponse 或 user dict。"""
    principal = await _require_admin(request)
    if principal is None:
        return _forbid()
    user = await _accounts(request).get_user(user_id)
    if user is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "user_not_found", "message": "No such member."}},
            headers=_NO_STORE,
        )
    return user


@router.get("/users/{user_id}/quota", response_model=None, response_model_exclude_none=True)
async def get_user_quota(user_id: str, request: Request) -> JSONResponse:
    target = await _quota_target(user_id, request)
    if isinstance(target, JSONResponse):
        return target
    from lumirss.user_quotas import UserQuotaStore

    row = await UserQuotaStore(request.app.state.control_db).get_row(user_id)
    return JSONResponse(content=_quota_json(row, user_id), headers=_NO_STORE)


@router.put("/users/{user_id}/quota", response_model=None, response_model_exclude_none=True)
async def set_user_quota(user_id: str, body: UserQuotaPutRequest, request: Request) -> JSONResponse:
    principal = await _require_admin(request)
    if principal is None:
        return _forbid()
    accounts = _accounts(request)
    user = await accounts.get_user(user_id)
    if user is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "user_not_found", "message": "No such member."}},
            headers=_NO_STORE,
        )
    # N009：临时提权在 404 之后、任何写入之前。
    # FIX-218：提权令牌绑定 (user_quota_set, 目标账户)。
    denial = await require_step_up(request, principal, "user_quota_set", user_id)
    if denial is not None:
        return denial
    from lumirss.user_quotas import UserQuotaStore

    caps = {key: value for key, value in body.model_dump().items() if value is not None}
    try:
        stored = await UserQuotaStore(request.app.state.control_db).set_caps(
            user_id=user_id, caps=caps, updated_by=principal["user_id"]
        )
    except Exception as exc:  # QuotaPolicyError → 稳定 400
        return JSONResponse(
            status_code=400,
            content={"error": {"type": "invalid_request", "message": str(exc)}},
            headers=_NO_STORE,
        )
    detail = ",".join(f"{key}={value}" for key, value in sorted(stored.items())) or "cleared"
    await accounts.audit(
        actor=principal["user_id"], action="user_quota_set", object_type="user", object_id=user_id, detail=detail
    )
    row = await UserQuotaStore(request.app.state.control_db).get_row(user_id)
    return JSONResponse(content=_quota_json(row, user_id), headers=_NO_STORE)


@router.delete("/users/{user_id}/quota", response_model=None, response_model_exclude_none=True)
async def clear_user_quota(user_id: str, request: Request) -> JSONResponse:
    principal = await _require_admin(request)
    if principal is None:
        return _forbid()
    accounts = _accounts(request)
    user = await accounts.get_user(user_id)
    if user is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "user_not_found", "message": "No such member."}},
            headers=_NO_STORE,
        )
    # N009：临时提权在 404 之后、任何写入之前。
    # FIX-218：提权令牌绑定 (user_quota_set, 目标账户)。
    denial = await require_step_up(request, principal, "user_quota_set", user_id)
    if denial is not None:
        return denial
    from lumirss.user_quotas import UserQuotaStore

    cleared = await UserQuotaStore(request.app.state.control_db).clear_caps(
        user_id=user_id, updated_by=principal["user_id"]
    )
    if cleared:
        await accounts.audit(
            actor=principal["user_id"], action="user_quota_cleared", object_type="user", object_id=user_id
        )
    row = await UserQuotaStore(request.app.state.control_db).get_row(user_id)
    return JSONResponse(content=_quota_json(row, user_id), headers=_NO_STORE)


@router.post("/users/{user_id}/background-pause", response_model=None, response_model_exclude_none=True)
async def background_pause_user(user_id: str, body: BackgroundPauseRequest, request: Request) -> JSONResponse:
    """N193：暂停单个成员的重型后台任务（登录/阅读不受影响）。

    与整账户暂停（O152）同源的两条硬边界：owner 不可定位；这里刻意
    不撤销任何会话——被暂停成员的会话与阅读必须继续有效。"""
    principal = await _require_admin(request)
    if principal is None:
        return _forbid()
    accounts = _accounts(request)
    user = await accounts.get_user(user_id)
    if user is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "user_not_found", "message": "No such member."}},
            headers=_NO_STORE,
        )
    if user["role"] == "owner":
        return _forbid("The owner account cannot be background-paused here.")
    from lumirss.user_quotas import UserQuotaStore

    await UserQuotaStore(request.app.state.control_db).set_background_pause(
        user_id=user_id, paused=True, reason=body.reason
    )
    await accounts.audit(
        actor=principal["user_id"], action="user_background_paused", object_type="user", object_id=user_id, detail=body.reason
    )
    return {"id": user_id, "backgroundPaused": True}


@router.post("/users/{user_id}/background-resume", response_model=None, response_model_exclude_none=True)
async def background_resume_user(user_id: str, request: Request) -> JSONResponse:
    principal = await _require_admin(request)
    if principal is None:
        return _forbid()
    accounts = _accounts(request)
    user = await accounts.get_user(user_id)
    if user is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "user_not_found", "message": "No such member."}},
            headers=_NO_STORE,
        )
    from lumirss.user_quotas import UserQuotaStore

    await UserQuotaStore(request.app.state.control_db).set_background_pause(
        user_id=user_id, paused=False, reason=None
    )
    await accounts.audit(
        actor=principal["user_id"], action="user_background_resumed", object_type="user", object_id=user_id
    )
    return {"id": user_id, "backgroundPaused": False}
