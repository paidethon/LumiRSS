"""Admin API — account lifecycle for the operator (0067, O146/O151/O152).

Scope of admin power (deliberately minimal, O151):
- create / revoke invitations (signup + recovery kinds);
- list users, pause / resume members (never the owner; never the last
  active admin);
- provision roles — owner-only: grant / revoke the admin role (never
  the owner's own role; never the last active admin);
- revoke a member's sessions;
- register FreshRSS pool accounts (deployment-side CLI creates them;
  this API only registers the binding material);
- read the minimal audit trail.

Admins have NO route to read another user's business content — feeds,
entries, library, AI sessions stay private. 403 shapes are stable; the
audit log records lifecycle actions (never credentials).
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.accounts_store import (
    INVITE_TTL_HOURS_DEFAULT,
    AccountError,
    AccountsStore,
    hash_password,
)
from lumirss.auth_store import AuthStore
from lumirss.user_scope import principal_of

router = APIRouter(prefix="/api/v1/admin")

_NO_STORE = {"Cache-Control": "no-store"}


def _accounts(request: Request) -> AccountsStore:
    return AccountsStore(request.app.state.control_db)


def _forbid(message: str = "Administrator role required.") -> JSONResponse:
    return JSONResponse(
        status_code=403,
        content={"error": {"type": "forbidden", "message": message}},
        headers=_NO_STORE,
    )


async def _require_admin(request: Request) -> dict[str, str] | None:
    """Server-verified principal with an admin role (never body data)."""
    principal = principal_of(request.scope)
    if principal is None or principal.get("role") not in ("owner", "admin"):
        return None
    return principal


def _require_owner(request: Request) -> dict[str, str] | None:
    """Server-verified principal with the OWNER role.

    Role provisioning is deliberately stricter than the rest of the admin
    surface: an admin must never be able to mint another admin (or demote
    one) — power over roles belongs to the operator alone."""
    principal = principal_of(request.scope)
    if principal is None or principal.get("role") != "owner":
        return None
    return principal


class InviteCreateRequest(BaseModel):
    """POST /admin/invites."""

    label: str | None = Field(default=None, max_length=64)
    ttlHours: int = Field(default=INVITE_TTL_HOURS_DEFAULT, ge=1, le=24 * 30)
    kind: str = Field(default="signup", pattern="^(signup|recovery)$")
    targetUsername: str | None = Field(default=None, max_length=32)


class PoolAddRequest(BaseModel):
    """POST /admin/pool — register one pre-provisioned FreshRSS account.

    The API password is created deployment-side (FreshRSS CLI); it is
    stored in the control secrets file (0600), never in SQLite, and is
    never echoed back.
    """

    freshrssUsername: str = Field(min_length=1, max_length=64)
    freshrssBaseUrl: str = Field(min_length=1, max_length=256)
    apiPassword: str = Field(min_length=1, max_length=256)
    publicUrl: str = Field(default="", max_length=256)


class UserRoleRequest(BaseModel):
    """POST /admin/users/{id}/role — owner-only provisioning body.

    Anything outside ``member``/``admin`` (including ``owner`` — there is
    exactly one owner and it is never assignable through the API) is a
    validation error (422)."""

    role: str = Field(pattern="^(member|admin)$")


@router.get("/users", response_model=None, response_model_exclude_none=True)
async def list_users(request: Request) -> JSONResponse:
    if await _require_admin(request) is None:
        return _forbid()
    return await _accounts(request).list_users()


@router.post("/invites", response_model=None, response_model_exclude_none=True)
async def create_invite(body: InviteCreateRequest, request: Request) -> JSONResponse:
    """Create an invitation. The raw token is returned exactly once —
    the operator hands it to the invitee out of band."""
    principal = await _require_admin(request)
    if principal is None:
        return _forbid()
    accounts = _accounts(request)
    target_user = None
    if body.kind == "recovery":
        if not body.targetUsername:
            return JSONResponse(
                status_code=400,
                content={"error": {"type": "invalid_request", "message": "Recovery invites need targetUsername."}},
                headers=_NO_STORE,
            )
        user = await accounts.get_user_by_username(body.targetUsername.strip().lower())
        if user is None:
            return JSONResponse(
                status_code=404,
                content={"error": {"type": "user_not_found", "message": "No such member."}},
                headers=_NO_STORE,
            )
        target_user = str(user["id"])
    try:
        raw, invite = await accounts.create_invite(
            created_by=principal["user_id"],
            ttl_hours=body.ttlHours,
            label=body.label,
            kind=body.kind,
            target_user=target_user,
        )
    except AccountError as exc:
        return JSONResponse(
            status_code=400,
            content={"error": {"type": "invalid_request", "message": str(exc)}},
            headers=_NO_STORE,
        )
    await accounts.audit(actor=principal["user_id"], action=f"invite_create_{body.kind}", object_type="invite", object_id=str(invite.get("id")))
    return JSONResponse(content={"token": raw, "invite": invite}, headers=_NO_STORE)


@router.get("/invites", response_model=None, response_model_exclude_none=True)
async def list_invites(request: Request) -> JSONResponse:
    if await _require_admin(request) is None:
        return _forbid()
    return await _accounts(request).list_invites()


@router.delete("/invites/{invite_id}", response_model=None, response_model_exclude_none=True)
async def revoke_invite(invite_id: str, request: Request) -> JSONResponse:
    principal = await _require_admin(request)
    if principal is None:
        return _forbid()
    revoked = await _accounts(request).revoke_invite(invite_id)
    if not revoked:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "invite_not_found", "message": "Invite not found, already used or already revoked."}},
            headers=_NO_STORE,
        )
    await _accounts(request).audit(actor=principal["user_id"], action="invite_revoke", object_type="invite", object_id=invite_id)
    return {"revoked": True}


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
    - every accepted change is audited (no credentials involved)."""
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
    can never be targeted, and the last active admin cannot be paused."""
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
    operator hands to the member (O150 — honest, no email pretending)."""
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


@router.get("/pool", response_model=None, response_model_exclude_none=True)
async def pool_status(request: Request) -> JSONResponse:
    if await _require_admin(request) is None:
        return _forbid()
    accounts = _accounts(request)
    counts = await accounts.pool_status()
    users = await accounts.list_users(limit=500)
    members: list[dict[str, object]] = []
    # Binding presence is read from each member's own database (bounded
    # loop — the deployment is small-scale by design).
    from lumirss.user_scope import user_context

    for user in users:
        if user["role"] == "owner":
            continue
        row = None
        with user_context(str(user["id"])):
            try:
                await request.app.state.db.migrate()
                row = await request.app.state.db.fetch_one("SELECT username, base_url FROM freshrss_binding WHERE id = 1")
            except Exception:  # noqa: BLE001 — unbound counts as pending
                row = None
        members.append({"id": str(user["id"]), "username": str(user["username"]), "bound": bool(row), "boundTo": str(row["username"]) if row else None})
    return {"ready": counts.get("ready", 0), "assigned": counts.get("assigned", 0), "members": members}


@router.post("/pool", response_model=None, response_model_exclude_none=True)
async def pool_add(body: PoolAddRequest, request: Request) -> JSONResponse:
    """Register one pre-provisioned FreshRSS account (O155).

    No Docker socket, no shell: the account itself is created by the
    operator with the FreshRSS CLI beforehand; this endpoint records the
    binding material. The password lands in the control secrets file and
    is never returned.
    """
    principal = await _require_admin(request)
    if principal is None:
        return _forbid()
    accounts = _accounts(request)
    try:
        row = await accounts.pool_add(freshrss_username=body.freshrssUsername, base_url=body.freshrssBaseUrl)
    except AccountError as exc:
        return JSONResponse(
            status_code=409,
            content={"error": {"type": "pool_conflict", "message": str(exc)}},
            headers=_NO_STORE,
        )
    request.app.state.control_secrets.set(f"freshrss_pool:{body.freshrssUsername}", body.apiPassword)
    await accounts.audit(actor=principal["user_id"], action="pool_add", object_type="freshrss_pool", object_id=str(row.get("id")))
    return row


@router.get("/audit", response_model=None, response_model_exclude_none=True)
async def audit_tail(request: Request, limit: int = 100) -> JSONResponse:
    if await _require_admin(request) is None:
        return _forbid()
    return await _accounts(request).audit_list(limit=limit)
