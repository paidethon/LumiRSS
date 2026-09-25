"""Admin API — account lifecycle for the operator (0067, O146/O151/O152).

Scope of admin power (deliberately minimal, O151):
- create / revoke invitations (signup + recovery kinds);
- save invite schemes (N001) and batch-generate invites from them;
- read the invite funnel (N004 — counts only, never invite codes);
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

from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.accounts_store import (
    INVITE_TTL_HOURS_DEFAULT,
    AccountError,
    AccountsStore,
    PoolEmpty,
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


def _iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=UTC).isoformat(timespec="seconds")


def _parse_iso_epoch(value: str) -> int | None:
    """ISO-8601 → epoch seconds (naive input treated as UTC); None when
    blank. Raises ValueError on unparseable input — a stable 400, never
    a silent mis-scheduled invite."""
    text = value.strip()
    if not text:
        return None
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return int(parsed.timestamp())


class InviteCreateRequest(BaseModel):
    """POST /admin/invites."""

    label: str | None = Field(default=None, max_length=64)
    ttlHours: int = Field(default=INVITE_TTL_HOURS_DEFAULT, ge=1, le=24 * 30)
    kind: str = Field(default="signup", pattern="^(signup|recovery)$")
    targetUsername: str | None = Field(default=None, max_length=32)
    # N001: stamp a saved scheme onto this invite (sources applied at
    # activation); N002: schedule the earliest activation instant (ISO-
    # 8601, compared against the server clock only); N003: hold one
    # FreshRSS pool slot at creation (409 pool_empty when none ready;
    # force=true is the explicit downgrade to no hold).
    schemeId: str | None = Field(default=None, max_length=64)
    notBefore: str | None = Field(default=None, max_length=40)
    holdPool: bool = False
    force: bool = False


class InviteSchemeCreateRequest(BaseModel):
    """POST /admin/invite-schemes (N001)."""

    name: str = Field(min_length=1, max_length=64)
    ttlHours: int = Field(default=INVITE_TTL_HOURS_DEFAULT, ge=1, le=24 * 30)
    initialSourceUrls: list[str] = Field(default_factory=list, max_length=50)
    freshrssPoolHold: bool = False
    quotaNote: str | None = Field(default=None, max_length=200)


class InviteSchemeBatchRequest(BaseModel):
    """POST /admin/invite-schemes/{id}/generate-invites (N001)."""

    count: int = Field(ge=1, le=100)
    notBefore: str | None = Field(default=None, max_length=40)
    # N003: create the batch without pool holds when the pool cannot
    # satisfy one-per-invite (honest downgrade, never a silent one).
    force: bool = False


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
    the operator hands it to the invitee out of band.

    N001/N002/N003 extensions (all optional, old bodies unchanged):
    schemeId stamps a saved scheme; notBefore schedules activation
    (server clock); holdPool reserves one FreshRSS pool slot at creation
    — with an empty pool this fails 409 pool_empty unless force=true
    creates the invite honestly without a hold."""
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
    scheme_id = None
    if body.schemeId:
        scheme = await accounts.get_scheme(body.schemeId)
        if scheme is None:
            return JSONResponse(
                status_code=404,
                content={"error": {"type": "scheme_not_found", "message": "No such invite scheme."}},
                headers=_NO_STORE,
            )
        scheme_id = str(scheme["id"])
    try:
        not_before = _parse_iso_epoch(body.notBefore) if body.notBefore else None
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={"error": {"type": "invalid_request", "message": "notBefore must be an ISO-8601 timestamp."}},
            headers=_NO_STORE,
        )
    hold = body.holdPool
    if hold and body.kind == "recovery":
        return JSONResponse(
            status_code=400,
            content={"error": {"type": "invalid_request", "message": "Only signup invites can hold a pool account."}},
            headers=_NO_STORE,
        )
    try:
        raw, invite = await accounts.create_invite(
            created_by=principal["user_id"],
            ttl_hours=body.ttlHours,
            label=body.label,
            kind=body.kind,
            target_user=target_user,
            scheme_id=scheme_id,
            not_before=not_before,
            hold_pool=hold,
        )
    except PoolEmpty:
        if not body.force:
            return JSONResponse(
                status_code=409,
                content={"error": {"type": "pool_empty", "message": "No ready FreshRSS account in the pool to hold."}},
                headers=_NO_STORE,
            )
        # Explicit downgrade: same invite, honestly without the hold.
        try:
            raw, invite = await accounts.create_invite(
                created_by=principal["user_id"],
                ttl_hours=body.ttlHours,
                label=body.label,
                kind=body.kind,
                target_user=target_user,
                scheme_id=scheme_id,
                not_before=not_before,
                hold_pool=False,
            )
        except AccountError as exc:
            return JSONResponse(
                status_code=400,
                content={"error": {"type": "invalid_request", "message": str(exc)}},
                headers=_NO_STORE,
            )
    except AccountError as exc:
        return JSONResponse(
            status_code=400,
            content={"error": {"type": "invalid_request", "message": str(exc)}},
            headers=_NO_STORE,
        )
    await accounts.audit(actor=principal["user_id"], action=f"invite_create_{body.kind}", object_type="invite", object_id=str(invite.get("id")))
    return JSONResponse(content={"token": raw, "invite": invite}, headers=_NO_STORE)


@router.post("/invite-schemes/{scheme_id}/generate-invites", response_model=None, response_model_exclude_none=True)
async def generate_invites_from_scheme(scheme_id: str, body: InviteSchemeBatchRequest, request: Request) -> JSONResponse:
    """Batch-generate N independent one-time invites from a scheme (N001).

    Every invite records the scheme and uses the scheme's TTL; a pool
    hold per invite is taken when the scheme asks for one — an
    insufficient pool fails the WHOLE batch 409 pool_empty (already
    created invites are rolled back, releasing their holds) unless
    force=true generates the batch without holds. Tokens appear exactly
    once, one per generated invite."""
    principal = await _require_admin(request)
    if principal is None:
        return _forbid()
    accounts = _accounts(request)
    scheme = await accounts.get_scheme(scheme_id)
    if scheme is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "scheme_not_found", "message": "No such invite scheme."}},
            headers=_NO_STORE,
        )
    try:
        not_before = _parse_iso_epoch(body.notBefore) if body.notBefore else None
    except ValueError:
        return JSONResponse(
            status_code=400,
            content={"error": {"type": "invalid_request", "message": "notBefore must be an ISO-8601 timestamp."}},
            headers=_NO_STORE,
        )
    hold = bool(scheme.get("freshrss_pool_hold")) and not body.force
    created: list[tuple[str, dict[str, object]]] = []
    try:
        for _ in range(body.count):
            raw, invite = await accounts.create_invite(
                created_by=principal["user_id"],
                ttl_hours=int(scheme["ttl_hours"]),
                label=str(scheme["name"]),
                kind="signup",
                scheme_id=str(scheme["id"]),
                not_before=not_before,
                hold_pool=hold,
            )
            created.append((raw, invite))
    except PoolEmpty:
        # Honest failure: roll the partial batch back (revoking also
        # releases each hold), then say exactly what was missing.
        for _raw, invite in created:
            await accounts.revoke_invite(str(invite.get("id")))
        status = await accounts.pool_status()
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "type": "pool_empty",
                    "message": f"Pool has {status.get('ready', 0)} ready account(s); {body.count} hold(s) were requested.",
                }
            },
            headers=_NO_STORE,
        )
    except AccountError as exc:
        for _raw, invite in created:
            await accounts.revoke_invite(str(invite.get("id")))
        return JSONResponse(
            status_code=400,
            content={"error": {"type": "invalid_request", "message": str(exc)}},
            headers=_NO_STORE,
        )
    await accounts.audit(
        actor=principal["user_id"],
        action="invite_batch_generate",
        object_type="invite_scheme",
        object_id=str(scheme["id"]),
        detail=f"count={len(created)}",
    )
    return JSONResponse(
        content={
            "scheme": scheme,
            "invites": [{"token": raw, "invite": invite} for raw, invite in created],
        },
        headers=_NO_STORE,
    )


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


# ---- 邀请方案（N001）--------------------------------------------------------


def _scheme_json(scheme: dict[str, object]) -> dict[str, object]:
    """Stable admin shape for a scheme row (camelCase, URLs decoded)."""
    return {
        "id": str(scheme.get("id")),
        "name": str(scheme.get("name")),
        "ttlHours": int(scheme.get("ttl_hours") or 0),
        "initialSourceUrls": [str(u) for u in scheme.get("initial_source_urls") or []],
        "freshrssPoolHold": bool(scheme.get("freshrss_pool_hold")),
        "quotaNote": scheme.get("quota_note"),
        "createdAt": int(scheme.get("created_at") or 0),
    }


@router.get("/invite-schemes", response_model=None, response_model_exclude_none=True)
async def list_invite_schemes(request: Request) -> JSONResponse:
    if await _require_admin(request) is None:
        return _forbid()
    schemes = await _accounts(request).list_schemes()
    return JSONResponse(content=[_scheme_json(scheme) for scheme in schemes], headers=_NO_STORE)


@router.post("/invite-schemes", response_model=None, response_model_exclude_none=True)
async def create_invite_scheme(body: InviteSchemeCreateRequest, request: Request) -> JSONResponse:
    """Save a named invite scheme (N001): TTL + optional initial source
    URLs + optional FreshRSS pool hold + quota note. Templates only —
    nothing is generated until /generate-invites is called."""
    principal = await _require_admin(request)
    if principal is None:
        return _forbid()
    try:
        scheme = await _accounts(request).create_scheme(
            name=body.name,
            ttl_hours=body.ttlHours,
            initial_source_urls=body.initialSourceUrls,
            freshrss_pool_hold=body.freshrssPoolHold,
            quota_note=body.quotaNote,
            created_by=principal["user_id"],
        )
    except AccountError as exc:
        return JSONResponse(
            status_code=400,
            content={"error": {"type": "invalid_request", "message": str(exc)}},
            headers=_NO_STORE,
        )
    await _accounts(request).audit(actor=principal["user_id"], action="invite_scheme_create", object_type="invite_scheme", object_id=str(scheme.get("id")))
    return JSONResponse(content=_scheme_json(scheme), headers=_NO_STORE)


@router.delete("/invite-schemes/{scheme_id}", response_model=None, response_model_exclude_none=True)
async def delete_invite_scheme(scheme_id: str, request: Request) -> JSONResponse:
    """Delete a scheme template. Already-generated invites and activated
    accounts keep their scheme_id — labels degrade honestly (LEFT JOIN)
    instead of history being rewritten."""
    principal = await _require_admin(request)
    if principal is None:
        return _forbid()
    deleted = await _accounts(request).delete_scheme(scheme_id)
    if not deleted:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "scheme_not_found", "message": "No such invite scheme."}},
            headers=_NO_STORE,
        )
    await _accounts(request).audit(actor=principal["user_id"], action="invite_scheme_delete", object_type="invite_scheme", object_id=scheme_id)
    return {"deleted": True}


# ---- 邀请漏斗（N004）--------------------------------------------------------


@router.get("/invite-funnel", response_model=None, response_model_exclude_none=True)
async def invite_funnel(request: Request, scheme_id: str | None = None) -> JSONResponse:
    """Per-scheme invite funnel counts (N004), aggregated from real rows.

    Responses carry counts ONLY — never invite codes, hashes or links.
    failedActivation comes from the invite_activation_failed audit
    events written by the activation boundary."""
    if await _require_admin(request) is None:
        return _forbid()
    funnel = await _accounts(request).invite_funnel(scheme_id=scheme_id or None)
    return JSONResponse(content=funnel, headers=_NO_STORE)


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
    return {
        "ready": counts.get("ready", 0),
        "held": counts.get("held", 0),
        "assigned": counts.get("assigned", 0),
        "members": members,
    }


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


# ---- P11: admin-only system diagnostics -------------------------------------
#
# GET /admin/system — server-derived, non-secret deployment diagnostics for
# the admin console 系统 panel: build provenance (health.py pattern), runtime
# uptime/memory/CPU (proc + stdlib resource; psutil is NOT a dependency and
# none is added), store row counts (control DB + the requesting admin's OWN
# user-DB projection only — never other members' content), optional-service
# availability (reuses the operations.py probes with their bounded timeouts)
# and background scheduler task states from main.py's app.state slots (no
# last-run tracking exists anywhere — the field stays honestly null).
#
# No shell exec, no Docker socket, no env dump, no secrets: every value below
# is a number, a boolean or one of the fixed status strings the operations
# surface already return.


_SYSTEM_TASK_SLOTS: tuple[tuple[str, str], ...] = (
    # (app.state attribute name, stable task name) — mirrors main.py lifespan.
    ("search_sync_task", "search_sync"),
    ("obsidian_scan_task", "obsidian_scan"),
    ("digest_scheduler_task", "digest_scheduler"),
    ("mail_imap_task", "mail_imap"),
    ("gpt_digest_scheduler_task", "gpt_digest_scheduler"),
    ("rag_idle_task", "rag_idle"),
    ("rag_index_task", "rag_index"),
)


def _task_state(task: object) -> str:
    """Honest asyncio.Task state — never guessed, never prettified."""
    import asyncio

    if task is None:
        return "off"  # slot disabled at lifespan (e.g. interval=0)
    if not isinstance(task, asyncio.Task):
        return "unknown"
    if task.cancelled():
        return "cancelled"
    if not task.done():
        return "running"
    return "failed" if task.exception() is not None else "completed"


def _uptime_seconds() -> int | None:
    """Process uptime from /proc (starttime vs /proc/uptime); honest null
    where /proc does not exist — clock-monotonic-since-boot is NOT uptime."""
    try:
        import os
        from pathlib import Path

        stat = Path("/proc/self/stat").read_text()
        fields = stat.rsplit(")", 1)[1].split()
        start_ticks = int(fields[19])  # field 22 (starttime); fields start at 3
        clk = os.sysconf("SC_CLK_TCK")
        boot_uptime = float(Path("/proc/uptime").read_text().split()[0])
        return max(0, int(boot_uptime - start_ticks / clk))
    except Exception:  # noqa: BLE001 — non-Linux or odd /proc → honest null
        return None


def _process_metrics() -> dict[str, object]:
    """RSS (current via /proc, peak via stdlib resource) + CPU seconds."""
    rss_bytes: int | None = None
    try:
        from pathlib import Path

        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                rss_bytes = int(line.split()[1]) * 1024  # kB → bytes
                break
    except Exception:  # noqa: BLE001 — non-Linux → resource fallback below
        rss_bytes = None
    peak_bytes: int | None = None
    cpu_seconds: float | None = None
    try:
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF)
        peak_bytes = int(usage.ru_maxrss) * 1024  # Linux reports kB
        cpu_seconds = round(usage.ru_utime + usage.ru_stime, 3)
    except Exception:  # noqa: BLE001 — metrics are best-effort, never fatal
        pass
    return {"rssBytes": rss_bytes, "peakRssBytes": peak_bytes, "cpuTimeS": cpu_seconds}


async def _system_counts(request: Request) -> dict[str, int]:
    """Row counts only. Control DB: identity/invite/pool/session facts.
    User scope: the requesting admin's OWN projection counts (same tables
    the sanitized diagnostics bundle exposes) — never other members' data."""
    import time

    counts = {
        "users": 0,
        "activeUsers": 0,
        "invites": 0,
        "freshrssPoolReady": 0,
        "freshrssPoolAssigned": 0,
        "sessions": 0,
        "feeds": 0,
        "entriesIndexed": 0,
        "libraryItems": 0,
    }
    control = request.app.state.control_db
    try:
        await control.migrate()
        for key, sql in (
            ("users", "SELECT COUNT(*) AS n FROM users"),
            ("activeUsers", "SELECT COUNT(*) AS n FROM users WHERE status = 'active'"),
            ("invites", "SELECT COUNT(*) AS n FROM invites"),
            ("freshrssPoolReady", "SELECT COUNT(*) AS n FROM freshrss_pool WHERE state = 'ready'"),
            ("freshrssPoolAssigned", "SELECT COUNT(*) AS n FROM freshrss_pool WHERE state = 'assigned'"),
            ("sessions", "SELECT COUNT(*) AS n FROM auth_sessions WHERE expires_at > ?"),
        ):
            params = (int(time.time()),) if key == "sessions" else ()
            row = await control.fetch_one(sql, params)
            counts[key] = int(row["n"]) if row else 0
    except Exception:  # noqa: BLE001 — unmigrated control DB → honest zeros
        pass
    # Own-scope (RoutingDatabase under the authenticated admin's context).
    db = request.app.state.db
    try:
        await db.migrate()
        for key, table in (
            ("feeds", "search_feeds"),
            ("entriesIndexed", "search_entries"),
            ("libraryItems", "library_items"),
        ):
            row = await db.fetch_one(f"SELECT COUNT(*) AS n FROM {table}", ())
            counts[key] = int(row["n"]) if row else 0
    except Exception:  # noqa: BLE001 — unmigrated user DB → honest zeros
        pass
    return counts


@router.get("/system", response_model=None)
async def system_status(request: Request) -> dict[str, object]:
    """Admin-only deployment diagnostics (P11). See the block comment above
    for the non-secret guarantee and the deliberate scoping: cross-user /
    system-wide facts live ONLY behind this gate; the per-user
    /api/v1/operations/* endpoints stay own-scope by design."""
    import asyncio
    import platform
    import time

    from lumirss.config import LumiSettings
    from lumirss.deps import _get_operations_service, _get_webdav_settings

    if await _require_admin(request) is None:
        return _forbid()
    settings = LumiSettings()
    service = _get_operations_service(request)
    sqlite_st, freshrss_st, rsshub_st = await asyncio.gather(
        service.sqlite_status(), service.freshrss_status(), service.rsshub_status()
    )

    def _presence(status: str) -> tuple[bool, str]:
        return status != "unconfigured", status

    freshrss_configured, freshrss_state = _presence(str(freshrss_st.get("status", "unknown")))
    rsshub_configured, rsshub_state = _presence(str(rsshub_st.get("status", "unknown")))

    obsidian = False
    try:
        obsidian = bool(settings.LUMIRSS_OBSIDIAN_VAULT_DIR)
    except Exception:  # noqa: BLE001 — presence probing never raises
        obsidian = False
    webdav_configured = False
    try:
        webdav_settings = _get_webdav_settings(request)
        doc = await webdav_settings.load()
        webdav_configured = webdav_settings.configured(doc)
    except Exception:  # noqa: BLE001
        webdav_configured = False
    ai_key_present = False
    try:
        ai_key_present = bool(settings.AI_API_KEY.get_secret_value())
    except Exception:  # noqa: BLE001
        ai_key_present = False
    imap_present = False
    try:
        from lumirss.secrets_store import SecretsStore

        imap_present = bool(SecretsStore(settings.secrets_path).get("mail_imap"))
    except Exception:  # noqa: BLE001
        imap_present = False

    def _bool_service(name: str, configured: bool) -> dict[str, object]:
        return {
            "name": name,
            "configured": configured,
            "status": "configured" if configured else "unconfigured",
            "latencyMs": None,
        }

    services = [
        {
            "name": "sqlite",
            "configured": True,
            "status": str(sqlite_st.get("status", "unknown")),
            "latencyMs": None,
        },
        {
            "name": "freshrss",
            "configured": freshrss_configured,
            "status": freshrss_state,
            "latencyMs": freshrss_st.get("latencyMs"),
        },
        {
            "name": "rsshub",
            "configured": rsshub_configured,
            "status": rsshub_state,
            "latencyMs": rsshub_st.get("latencyMs"),
        },
        _bool_service("obsidian", obsidian),
        _bool_service("webdav", webdav_configured),
        _bool_service("ai", ai_key_present),
        _bool_service("imap", imap_present),
    ]

    tasks = [
        {
            "name": name,
            "enabled": getattr(request.app.state, attr, None) is not None,
            "state": _task_state(getattr(request.app.state, attr, None)),
            # No scheduler tracks last-run anywhere (checked) — honest null.
            "lastRunAt": None,
        }
        for attr, name in _SYSTEM_TASK_SLOTS
    ]

    return {
        "version": settings.LUMIRSS_VERSION,
        "commit": settings.LUMIRSS_COMMIT,
        "python": platform.python_version(),
        "apiVersion": 1,
        "uptimeS": _uptime_seconds(),
        "uptimeCheckedAt": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "process": _process_metrics(),
        "counts": await _system_counts(request),
        "services": services,
        "tasks": tasks,
    }


# ---------------------------------------------------------------------------
# P0 public-registration policy: instance-level switch owned by the
# control DB (migration 0089, InstanceSettingsStore). Defaults CLOSED on
# upgrade AND on fresh install; only this endpoint changes it, and every
# change lands in the audit log. Enforcement lives in routers/auth.py —
# this endpoint never gates anything by itself.


class RegistrationPolicyRequest(BaseModel):
    """PUT /admin/registration-policy."""

    allowPublicRegistration: bool


class RegistrationPolicyResponse(BaseModel):
    """GET / PUT /admin/registration-policy (instance-level switch)."""

    allowPublicRegistration: bool
    updatedAt: str | None = None
    updatedBy: str | None = None


def _registration_policy_response(describe: dict[str, object]) -> RegistrationPolicyResponse:
    updated_at = describe.get("updatedAt")
    return RegistrationPolicyResponse(
        allowPublicRegistration=describe["value"] == "1",
        updatedAt=_iso(int(updated_at)) if isinstance(updated_at, int) else None,
        updatedBy=str(describe["updatedBy"]) if describe.get("updatedBy") else None,
    )


@router.get("/registration-policy", response_model=RegistrationPolicyResponse)
async def get_registration_policy(request: Request) -> RegistrationPolicyResponse:
    from lumirss.instance_settings import InstanceSettingsStore

    await _require_admin(request)
    describe = await InstanceSettingsStore(request.app.state.control_db).describe(
        "allow_public_registration"
    )
    return _registration_policy_response(describe)


@router.put("/registration-policy", response_model=RegistrationPolicyResponse)
async def set_registration_policy(
    body: RegistrationPolicyRequest, request: Request
) -> RegistrationPolicyResponse:
    from lumirss.instance_settings import InstanceSettingsStore

    principal = await _require_admin(request)
    store = InstanceSettingsStore(request.app.state.control_db)
    before = await store.get_bool("allow_public_registration")
    await store.set(
        "allow_public_registration",
        "1" if body.allowPublicRegistration else "0",
        updated_by=principal["user_id"],
    )
    await _accounts(request).audit(
        actor=principal["user_id"],
        action="registration_policy_change",
        object_type="instance_setting",
        object_id="allow_public_registration",
        detail=f"{before}->{body.allowPublicRegistration}",
    )
    describe = await store.describe("allow_public_registration")
    return _registration_policy_response(describe)


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
    正整数（1..上限界）才是有效设置。未知键 → 422。"""

    maxSources: int | None = Field(default=None, ge=1, le=10_000)
    aiQuotaPerDay: int | None = Field(default=None, ge=1, le=100_000)


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


# ---- N192 邀请容量仪表 ------------------------------------------------------


@router.get("/capacity", response_model=None, response_model_exclude_none=True)
async def admin_capacity(request: Request) -> JSONResponse:
    """N192：池 {ready, held, assigned} + 邀请 {pending, held} + 用户
    {active, paused} 的真实行聚合。lowCapacity（ready+held < pending）
    是唯一服务端定义——可交付的 FreshRSS 名额追不上待激活邀请时为真，
    管理台据它亮出「容量不足」警示。只读计数，绝无邀请码。"""
    if await _require_admin(request) is None:
        return _forbid()
    return JSONResponse(content=await _accounts(request).capacity(), headers=_NO_STORE)


# ---- N195 升级影响预览 / N196 升级任务进度 ---------------------------------


@router.get("/upgrade-preview", response_model=None, response_model_exclude_none=True)
async def admin_upgrade_preview(request: Request) -> JSONResponse:
    """N195：发布清单 × 当前版本 × 迁移差异的只读推演。

    LUMIRSS_RELEASE_MANIFEST 未配置/文件不可读时如实 available:false；
    不兼容（同版本/降级/库超前于目标）→ blocked:true + 原因。绝不
    触发任何升级动作——这是预览，执行权只在 ./lumirss update。"""
    if await _require_admin(request) is None:
        return _forbid()
    from lumirss.config import LumiSettings
    from lumirss.upgrade_preview import build_upgrade_preview, preview_response

    settings = LumiSettings()
    result = build_upgrade_preview(
        manifest_path=settings.LUMIRSS_RELEASE_MANIFEST,
        current_version=settings.LUMIRSS_VERSION,
        control_db=request.app.state.control_db,
    )
    return JSONResponse(content=preview_response(**result), headers=_NO_STORE)


@router.get("/deploy-status", response_model=None, response_model_exclude_none=True)
async def admin_deploy_status(request: Request) -> JSONResponse:
    """N196：./lumirss update 写入的阶段 JSON 只读透传（admin-gated）。

    未配置/尚无记录/坏文件都是诚实 available:false + 原因；内容本身
    由脚本写入（阶段名/状态/时间戳/imageTag，绝无秘密）。本端点没有
    也永远不会有执行控件——升级只由运维侧 ./lumirss update 触发。"""
    if await _require_admin(request) is None:
        return _forbid()
    from lumirss.config import LumiSettings
    from lumirss.deploy_status import read_deploy_status

    result = read_deploy_status(LumiSettings().LUMIRSS_DEPLOY_STATUS_FILE)
    return JSONResponse(content=result, headers=_NO_STORE)


@router.get("/rollback-readiness", response_model=None, response_model_exclude_none=True)
async def admin_rollback_readiness(request: Request) -> JSONResponse:
    """N197：回滚就绪检查（admin-gated，只读要素清单）。

    - previousImage：读 ./lumirss snapshot_for_rollback 写下的回滚快照
      清单（LUMIRSS_ROLLBACK_MANIFEST_FILE）——BFF 没有 Docker 访问权，
      镜像存在性只来自脚本侧的诚实记录；
    - backup：LUMIRSS_BACKUP_DIR 里最新 *.backup + N186 只读完整性校验；
    - dbDowngrade：诚实限制说明（SQLite 迁移只向前，无法降级）；
    - canRollback = 前镜像在 AND 备份可校验 AND schema 与备份一致。

    本端点只给清单，永远不给一键回滚按钮——回滚只由运维侧
    ./lumirss rollback 触发。"""
    if await _require_admin(request) is None:
        return _forbid()
    import asyncio

    from lumirss.config import LumiSettings
    from lumirss.migrations import schema_version
    from lumirss.restore import verify_backup_findings
    from lumirss.rollback_readiness import (
        build_rollback_readiness,
        latest_backup_path,
        read_rollback_manifest,
    )

    settings = LumiSettings()
    manifest = read_rollback_manifest(settings.LUMIRSS_ROLLBACK_MANIFEST_FILE)
    latest = latest_backup_path(settings.LUMIRSS_BACKUP_DIR)
    if latest is not None:
        report = await asyncio.to_thread(
            verify_backup_findings, latest, request.app.state.control_db
        )
        backup_schema = None
        manifest_block = report.get("manifest") if isinstance(report, dict) else None
        if isinstance(manifest_block, dict):
            value = manifest_block.get("lumiDbSchemaVersion")
            backup_schema = int(value) if isinstance(value, int) else None
    else:
        report = None
        backup_schema = None
    current_schema = await asyncio.to_thread(schema_version, request.app.state.control_db)
    result = build_rollback_readiness(
        manifest=manifest,
        backup_report=report,
        backup_name=latest.name if latest is not None else None,
        current_schema_version=current_schema,
        backup_schema_version=backup_schema,
        backup_dir_configured=bool(settings.LUMIRSS_BACKUP_DIR.strip()),
    )
    return JSONResponse(content=result, headers=_NO_STORE)
