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
