"""Admin invites responsibility slice (FIX-161): invitation lifecycle,
invite schemes (N001), the invite funnel (N004), the FreshRSS account
pool (O155/N003) and the capacity gauge (N192). Routes moved verbatim
from the former ``routers/admin.py`` monolith.
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.accounts_store import (
    INVITE_TTL_HOURS_DEFAULT,
    AccountError,
    PoolEmpty,
)
from lumirss.routers.admin._common import (
    _NO_STORE,
    _accounts,
    _forbid,
    _parse_iso_epoch,
    _require_admin,
)

router = APIRouter()


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
    # FIX-047：secrets 键使用池行的规范化用户名（trim 后）——绑定读取
    # （bind_freshrss_account）按池行用户名逐字取密，键错位会让成员
    # 激活后认证失败。
    request.app.state.control_secrets.set(f"freshrss_pool:{row['freshrss_username']}", body.apiPassword)
    await accounts.audit(actor=principal["user_id"], action="pool_add", object_type="freshrss_pool", object_id=str(row.get("id")))
    return row


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
