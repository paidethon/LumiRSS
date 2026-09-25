"""Auth endpoints — multi-account session flow (0067).

Browser surface:
- ``POST /auth/login`` — username + password (basic mode keeps the
  legacy password-only contract for the reverse-proxy deployment).
- ``POST /auth/activate`` — redeem a signup invite: choose username and
  personal password, get an independent FreshRSS binding from the pool
  (honest "not ready" state when the pool is empty — never a shared
  credential fallback).
- ``GET  /auth/activation-preview`` — invite validity + pool readiness
  for the activation screen (no secret material, no token burn).
- ``POST /auth/recover`` — redeem an admin-issued recovery invite.
- ``GET  /auth/session`` — probe + current identity.
- ``POST /auth/password`` — change own password (re-auth required).
- ``GET/DELETE /auth/sessions`` — own sessions only (F038).

Every response is ``Cache-Control: no-store`` — nothing about auth state
may be cached by intermediaries. Failure replies share generic shapes;
no username-existence oracle (O171).
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.accounts_store import (
    MAX_PASSWORD_BYTES,
    USERNAME_RE,
    AccountError,
    AccountsStore,
    InviteInvalid,
    InviteNotActive,
    UsernameTaken,
    hash_password,
    hash_token,
    verify_password_hash,
)
from lumirss.auth_store import MIN_PASSWORD_LENGTH, AuthStore
from lumirss.config import LumiSettings
from lumirss.middleware import (
    build_session_cookie,
    clear_session_cookie,
    login_attempts_allowed,
    login_retry_after_s,
    parse_session_cookie,
    register_login_failure,
    reset_login_failures,
)
from lumirss.models import (
    ActivationSourceResult,
    AuthStatus,
    LoginChallenge,
    LoginRequest,
    PasswordChangeRequest,
)
from lumirss.totp import TotpStore, check_second_factor

router = APIRouter()

_NO_STORE = {"Cache-Control": "no-store"}

_RATE_LIMITED_BODY = {
    "error": {"type": "rate_limited", "message": "Too many attempts; wait a minute."}
}


def _control(request: Request) -> AccountsStore:
    return AccountsStore(request.app.state.control_db)


def _sessions(request: Request) -> AuthStore:
    return AuthStore(request.app.state.control_db)


def _max_age_seconds() -> int:
    return LumiSettings().LUMIRSS_SESSION_MAX_AGE_DAYS * 86400


def _iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=UTC).isoformat(timespec="seconds")


class ActivateAccountRequest(BaseModel):
    """POST /auth/activate — signup invite redemption."""

    token: str = Field(min_length=16, max_length=256)
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=1, max_length=256)
    displayName: str | None = Field(default=None, max_length=64)


class RecoverPasswordRequest(BaseModel):
    """POST /auth/recover — recovery invite redemption."""

    token: str = Field(min_length=16, max_length=256)
    newPassword: str = Field(min_length=1, max_length=256)


def _reject(status: int, err_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": err_type, "message": message}},
        headers=_NO_STORE,
    )


async def _mint_session(
    request: Request,
    response: Response,
    user_id: str,
    *,
    login_event: bool = True,
) -> AuthStatus:
    """Mint a session cookie for a verified identity.

    N008: credential-bearing login paths also record a login event — the
    first sighting of a device fingerprint (UA family + platform) becomes
    a ``new_device`` event the 安全页 surfaces; known devices only get a
    ``login`` event (no re-notify). ``login_event=False`` is for session
    mints that are NOT logins (password change keeps the user's device).
    """
    user_agent = request.headers.get("user-agent")
    raw_token, expires_at = await _sessions(request).create_session(
        LumiSettings().LUMIRSS_SESSION_MAX_AGE_DAYS,
        user_agent=user_agent,
        user_id=user_id,
    )
    response.headers["Set-Cookie"] = build_session_cookie(raw_token, _max_age_seconds())
    response.headers["Cache-Control"] = "no-store"
    status = AuthStatus(authenticated=True, expiresAt=_iso(expires_at))
    if login_event:
        kind = await _sessions(request).record_login_event(
            user_id=user_id, user_agent=user_agent
        )
        if kind == "new_device":
            status.newDevice = True
    return status


async def _current_user_id(request: Request) -> str | None:
    raw_token = parse_session_cookie(request.headers.raw)
    if raw_token is None:
        return None
    resolved = await _sessions(request).get_valid_session_user(raw_token)
    return resolved[0] if resolved else None


@router.post(
    "/api/v1/auth/login",
    response_model=AuthStatus | LoginChallenge,
    response_model_exclude_none=True,
)
async def login(
    body: LoginRequest, request: Request, response: Response
) -> AuthStatus | LoginChallenge | JSONResponse:
    """Verify credentials, mint a per-user session.

    Wrong-password and unknown-username share the generic failure shape
    and the same brute-force budget (no account oracle).

    N007: when the account has TOTP enabled, a correct password does NOT
    mint a session — the response is ``{totpRequired, pendingToken}`` and
    the real session is issued by ``POST /auth/totp/verify`` (same
    brute-force budget, one attempt per pending token).
    """
    if LumiSettings().LUMIRSS_AUTH_MODE != "session":
        # Legacy single-user mode: the reverse proxy owns credentials.
        return AuthStatus(authenticated=True, mode="basic")
    if not login_attempts_allowed(request.scope):
        retry_after = login_retry_after_s(request.scope)
        return JSONResponse(
            status_code=429,
            content=_RATE_LIMITED_BODY,
            headers={"Retry-After": str(retry_after), **_NO_STORE},
        )
    username = (getattr(body, "username", None) or "").strip().lower()
    if not username:
        return _reject(400, "invalid_request", "Username is required.")
    user = await _control(request).verify_login(username, body.password)
    if user is None:
        register_login_failure(request.scope)
        return _reject(401, "invalid_credentials", "Incorrect username or password.")
    user_id = str(user["id"])
    # N007: TOTP-enabled accounts take the two-step path. The pending
    # token is short-lived, single-use, hash-stored — not a session.
    # NOTE: the brute-force budget is only reset when a session is
    # actually minted — a correct password with pending second step does
    # NOT clear accumulated failures (each verify attempt counts).
    totp_store = TotpStore(request.app.state.control_db)
    if await totp_store.is_enabled(user_id):
        pending_token = await totp_store.create_pending_login(user_id)
        await _control(request).audit(
            actor=user_id, action="login_totp_pending", object_type="user", object_id=user_id
        )
        return LoginChallenge(totpRequired=True, pendingToken=pending_token)
    reset_login_failures(request.scope)
    await _control(request).audit(actor=user_id, action="login", object_type="user", object_id=user_id)
    return await _mint_session(request, response, user_id)


@router.get(
    "/api/v1/auth/session",
    response_model=AuthStatus,
    response_model_exclude_none=True,
)
async def session_status(request: Request) -> AuthStatus:
    """Public probe: which auth layer is active, and is this browser
    holding a live session? Includes the server-verified identity (never
    from the request body) so the UI can render the account menu."""
    if LumiSettings().LUMIRSS_AUTH_MODE != "session":
        return AuthStatus(authenticated=True, mode="basic")
    raw_token = parse_session_cookie(request.headers.raw)
    if raw_token is None:
        return AuthStatus(authenticated=False)
    resolved = await _sessions(request).get_valid_session_user(raw_token)
    if resolved is None:
        return AuthStatus(authenticated=False)
    user_id, expires_at = resolved
    user = await _control(request).get_user(user_id)
    if user is None or user.get("status") != "active":
        return AuthStatus(authenticated=False)
    return AuthStatus(
        authenticated=True,
        expiresAt=_iso(expires_at),
        userId=str(user["id"]),
        username=str(user["username"]),
        role=str(user["role"]),
    )


@router.post("/api/v1/auth/logout", response_model=AuthStatus)
async def logout(request: Request, response: Response) -> AuthStatus:
    """Revoke the current session and expire the cookie."""
    raw_token = parse_session_cookie(request.headers.raw)
    if raw_token is not None:
        await _sessions(request).revoke_session(raw_token)
    response.headers["Set-Cookie"] = clear_session_cookie()
    response.headers["Cache-Control"] = "no-store"
    return AuthStatus(authenticated=False)


@router.post("/api/v1/auth/logout-all", response_model=AuthStatus)
async def logout_all(request: Request, response: Response) -> AuthStatus:
    """Revoke THIS user's sessions on all devices, including this one."""
    user_id = await _current_user_id(request)
    if user_id is not None:
        await _sessions(request).revoke_all_sessions(user_id=user_id)
    response.headers["Set-Cookie"] = clear_session_cookie()
    response.headers["Cache-Control"] = "no-store"
    return AuthStatus(authenticated=False)


@router.post(
    "/api/v1/auth/password",
    response_model=AuthStatus,
    response_model_exclude_none=True,
)
async def change_password(
    body: PasswordChangeRequest, request: Request, response: Response
) -> AuthStatus | JSONResponse:
    """Change own password: verify current, replace hash, revoke ALL of
    this user's sessions, then mint a fresh session for THIS device.

    N007: when the account has TOTP enabled, a valid second factor
    (``totpCode``) is REQUIRED — server-enforced, not front-end."""
    user_id = await _current_user_id(request)
    if user_id is None:
        return _reject(401, "session_required", "Login required.")
    user = await _control(request).get_user(user_id)
    if user is None:
        return _reject(401, "session_required", "Login required.")
    if not verify_password_hash(body.currentPassword, str(user["password_hash"])):
        return _reject(401, "invalid_credentials", "Incorrect current password.")
    second = await check_second_factor(
        request.app.state.control_db, request.app.state.secrets_store, user_id, body.totpCode
    )
    if second == "missing":
        return _reject(400, "totp_code_required", "两步验证已开启，需要验证码。")
    if second == "invalid":
        return _reject(401, "totp_code_invalid", "验证码无效。")
    if len(body.newPassword) < MIN_PASSWORD_LENGTH:
        return _reject(400, "weak_password", f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if len(body.newPassword.encode("utf-8")) > MAX_PASSWORD_BYTES:
        # bcrypt refuses input beyond 72 bytes; reject at the boundary
        # with a stable 400 instead of a 500 at hash time.
        return _reject(400, "weak_password", f"Password must be at most {MAX_PASSWORD_BYTES} bytes (multi-byte scripts count every byte).")
    await _control(request).set_password_hash(user_id, hash_password(body.newPassword))
    await _sessions(request).revoke_all_sessions(user_id=user_id)
    await _control(request).audit(actor=user_id, action="password_change", object_type="user", object_id=user_id)
    # N008: 换密后的会话换发不是一次「登录」——不记登录事件。
    return await _mint_session(request, response, user_id, login_event=False)


@router.get("/api/v1/auth/activation-preview", response_model_exclude_none=True)
async def activation_preview(request: Request, token: str) -> dict[str, object]:
    """Honest activation screen state: is the invite usable, is a
    FreshRSS account ready? Reveals nothing beyond yes/no for a broken
    link — for a scheduled invite (N002) it additionally echoes the
    server clock (the ONLY clock the boundary consults) as serverTime
    and the notBefore instant, so the UI can render 等待生效. No labels,
    no emails, no pool usernames."""
    accounts = _control(request)
    token_hash = hash_token(token)
    row = await accounts.get_invite_state_by_token(token_hash)
    now_epoch = int(datetime.now(UTC).timestamp())
    base_valid = bool(row) and row["used_at"] is None and row["revoked_at"] is None and int(row["expires_at"]) > now_epoch
    not_before = int(row["not_before"]) if (row is not None and row["not_before"] is not None) else None
    waiting = bool(base_valid and not_before is not None and not_before > now_epoch)
    valid = bool(base_valid and not waiting)
    pool = await accounts.pool_status()
    return {
        "valid": valid,
        "kind": str(row["kind"]) if (valid and row) else None,
        "freshrssReady": bool(valid and pool.get("ready", 0) > 0),
        "notBefore": _iso(not_before) if (waiting and not_before is not None) else None,
        "serverTime": _iso(now_epoch),
    }


@router.post(
    "/api/v1/auth/activate",
    response_model=AuthStatus,
    response_model_exclude_none=True,
)
async def activate_account(body: ActivateAccountRequest, request: Request, response: Response) -> AuthStatus | JSONResponse:
    """Redeem a signup invite: create the independent account, bind an
    own FreshRSS account from the pool, mint a session.

    Pool-empty is an explicit pending-binding state — the account is
    usable and the UI shows "RSS source binding pending"; the server
    never falls back to shared credentials.

    N001: a scheme-stamped invite records the scheme on the account and
    subscribes the scheme's initial sources best-effort — failures are
    listed per URL in ``initialSources`` and never block activation.
    N002: a scheduled invite (not_before in the future by the SERVER
    clock) is rejected with the stable 403 invite_not_active carrying
    serverTime + notBefore; the token is not burned.
    """
    if LumiSettings().LUMIRSS_AUTH_MODE != "session":
        return _reject(400, "invalid_request", "Activation is not available in single-user mode.")
    username = body.username.strip().lower()
    if not USERNAME_RE.match(username):
        return _reject(400, "invalid_username", "Username must be 3-32 chars: lowercase letters, digits, '-', '_', starting with a letter or digit.")
    if len(body.password) < MIN_PASSWORD_LENGTH:
        return _reject(400, "weak_password", f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    accounts = _control(request)
    token_hash = hash_token(body.token)
    try:
        invite = await accounts.redeem_invite(body.token)
    except InviteNotActive as exc:
        await accounts.audit(actor="anonymous", action="invite_activation_failed", object_type="invite", object_id=exc.invite_id, detail="not_active")
        return JSONResponse(
            status_code=403,
            content={"error": {"type": "invite_not_active", "message": "This invitation is not active yet.", "serverTime": _iso(exc.now), "notBefore": _iso(exc.not_before)}},
            headers=_NO_STORE,
        )
    except InviteInvalid as exc:
        await accounts.audit(actor="anonymous", action="invite_activation_failed", object_type="invite", object_id=exc.invite_id, detail="invite_invalid")
        return _reject(400, "invite_invalid", "Invitation is invalid, expired or already used.")
    if str(invite.get("kind") or "signup") != "signup":
        await accounts.audit(actor="anonymous", action="invite_activation_failed", object_type="invite", object_id=str(invite.get("id")), detail="kind_not_signup")
        return _reject(400, "invite_invalid", "This invitation is not a signup invite.")
    try:
        user = await accounts.create_user(
            username=username,
            password_hash=hash_password(body.password),
            role="member",
            display_name=body.displayName,
        )
    except AccountError as exc:
        # Restore the invite: a failed signup (name taken, weak password)
        # must not burn the one-time token.
        await accounts.restore_unused_invite(token_hash)
        await accounts.audit(actor="anonymous", action="invite_activation_failed", object_type="invite", object_id=str(invite.get("id")), detail="account_create_rejected")
        return _reject(400, "invalid_username", str(exc))
    user_id = str(user["id"])
    await accounts.mark_invite_used_by(token_hash, user_id)
    # FreshRSS binding from the pool — atomic assignment, honest pending.
    # A held pool account (N003) is converted assigned for THIS user.
    assigned = await accounts.pool_assign(user_id, held_freshrss_username=(str(invite["held_pool_account"]) if invite.get("held_pool_account") else None))
    if assigned is not None:
        from lumirss.control_resources import bind_freshrss_account

        await bind_freshrss_account(request.app.state, user_id, str(assigned["freshrss_username"]), str(assigned["base_url"]))
    # Scheme bookkeeping (N001): record scheme on the account row, then
    # best-effort subscribe of the scheme's initial sources.
    initial_sources: list[ActivationSourceResult] | None = None
    scheme_id = str(invite["scheme_id"]) if invite.get("scheme_id") else None
    if scheme_id:
        scheme = await accounts.get_scheme(scheme_id)
        if scheme is not None:
            await accounts.set_user_scheme(user_id, scheme_id)
            urls = [str(u) for u in scheme.get("initial_source_urls") or []]
            if urls:
                from lumirss.control_resources import apply_scheme_initial_sources

                results = await apply_scheme_initial_sources(request.app.state, user_id, urls)
                initial_sources = [ActivationSourceResult(**result) for result in results]
    await accounts.audit(actor=user_id, action="account_activate", object_type="user", object_id=user_id, detail="pool_assigned" if assigned else "binding_pending")
    status = await _mint_session(request, response, user_id)
    status.initialSources = initial_sources
    return status


class RegisterRequest(BaseModel):
    """POST /auth/register (P0 public registration)."""

    username: str = Field(max_length=32)
    password: str = Field(max_length=MAX_PASSWORD_BYTES)
    displayName: str | None = Field(default=None, max_length=64)


@router.post(
    "/api/v1/auth/register",
    response_model=AuthStatus,
    response_model_exclude_none=True,
)
async def register(body: RegisterRequest, request: Request, response: Response) -> AuthStatus | JSONResponse:
    """Open registration (P0): self-serve MEMBER account, gated by the
    instance-level ``allow_public_registration`` policy (control DB,
    default OFF — upgraded instances and fresh installs alike stay
    closed until the operator flips /admin/registration-policy).

    Deliberately mirrors /auth/activate without an invite: role is
    hardcoded ``member`` (the client can never request a role), the
    FreshRSS pool assigns atomically or the account starts with an
    honest pending binding, and the server derives every identity.
    Enforcement here is the only gate — a hidden frontend button is
    not trusted.
    """
    if LumiSettings().LUMIRSS_AUTH_MODE != "session":
        return _reject(400, "invalid_request", "Registration is not available in single-user mode.")
    accounts = _control(request)
    from lumirss.instance_settings import InstanceSettingsStore

    allowed = await InstanceSettingsStore(request.app.state.control_db).get_bool(
        "allow_public_registration"
    )
    if not allowed:
        # Uniform rejection regardless of username validity/existence —
        # a closed instance must not become a username oracle.
        await accounts.audit(
            actor="anonymous",
            action="register_rejected",
            object_type="user",
            object_id="policy_closed",
        )
        return _reject(403, "registration_disabled", "Registration is disabled on this instance.")
    username = body.username.strip().lower()
    if not USERNAME_RE.match(username):
        return _reject(400, "invalid_username", "Username must be 3-32 chars: lowercase letters, digits, '-', '_', starting with a letter or digit.")
    if len(body.password) < MIN_PASSWORD_LENGTH:
        return _reject(400, "weak_password", f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if await accounts.get_user_by_username(username) is not None:
        return _reject(409, "username_taken", "That username is already in use.")
    try:
        user = await accounts.create_user(
            username=username,
            password_hash=hash_password(body.password),
            role="member",
            display_name=body.displayName,
        )
    except UsernameTaken as exc:
        return _reject(409, "username_taken", str(exc))
    except AccountError as exc:
        return _reject(400, "invalid_username", str(exc))
    user_id = str(user["id"])
    # FreshRSS binding from the pool — atomic assignment, honest pending.
    assigned = await accounts.pool_assign(user_id)
    if assigned is not None:
        from lumirss.control_resources import bind_freshrss_account

        await bind_freshrss_account(request.app.state, user_id, str(assigned["freshrss_username"]), str(assigned["base_url"]))
    await accounts.audit(
        actor=user_id,
        action="account_register",
        object_type="user",
        object_id=user_id,
        detail="pool_assigned" if assigned else "binding_pending",
    )
    return await _mint_session(request, response, user_id)


@router.post(
    "/api/v1/auth/recover",
    response_model=AuthStatus,
    response_model_exclude_none=True,
)
async def recover_password(body: RecoverPasswordRequest, request: Request, response: Response) -> AuthStatus:
    """Redeem an admin-issued recovery invite: set a new password,
    revoke all of that user's sessions (O150 — no email service, nothing
    is pretended to be sent)."""
    accounts = _control(request)
    if len(body.newPassword) < MIN_PASSWORD_LENGTH:
        return _reject(400, "weak_password", f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    try:
        invite = await accounts.redeem_invite(body.token)
    except InviteInvalid:
        return _reject(400, "invite_invalid", "Recovery link is invalid, expired or already used.")
    if str(invite.get("kind") or "") != "recovery" or not invite.get("target_user"):
        return _reject(400, "invite_invalid", "This link is not a recovery link.")
    target = str(invite["target_user"])
    user = await accounts.get_user(target)
    if user is None:
        return _reject(400, "invite_invalid", "This account no longer exists.")
    await accounts.set_password_hash(target, hash_password(body.newPassword))
    await _sessions(request).revoke_all_sessions(user_id=target)
    await accounts.audit(actor=target, action="password_recover", object_type="user", object_id=target)
    return await _mint_session(request, response, target)


@router.get("/api/v1/auth/first-run", response_model_exclude_none=True)
async def first_run_status(request: Request) -> dict[str, object]:
    """Setup probe for the operator UI: does the owner password still
    need to be set? (No account details; safe pre-login.)"""
    accounts = _control(request)
    owner_id = getattr(request.app.state, "owner_id", None)
    if not owner_id:
        return {"needsSetup": False, "authMode": LumiSettings().LUMIRSS_AUTH_MODE}
    owner = await accounts.get_user(str(owner_id))
    needs_setup = bool(owner) and owner.get("password_updated_at") is None
    return {"needsSetup": bool(needs_setup), "authMode": LumiSettings().LUMIRSS_AUTH_MODE}


# -- F038 会话管理界面（多账户：只看得到自己的会话） ----------------------------


@router.get("/api/v1/auth/sessions", response_model=None, response_model_exclude_none=True)
async def list_auth_sessions(request: Request) -> list[dict[str, object]] | JSONResponse:
    """活跃会话（当前标记「本机」）；响应绝不含 token/hash 字段。"""
    if LumiSettings().LUMIRSS_AUTH_MODE != "session":
        raw_token = parse_session_cookie(request.headers.raw)
        return await _sessions(request).list_sessions(current_token=raw_token)
    user_id = await _current_user_id(request)
    if user_id is None:
        return _reject(401, "session_required", "Login required.")
    raw_token = parse_session_cookie(request.headers.raw)
    return await _sessions(request).list_sessions(current_token=raw_token, user_id=user_id)


@router.delete("/api/v1/auth/sessions/{session_id}", status_code=204)
async def revoke_auth_session(session_id: str, request: Request) -> Response:
    """撤销自己的一个会话；撤销当前会话 = 登出语义（清 cookie）。404 = 不存在。"""
    import hashlib as _hashlib

    user_id = await _current_user_id(request)
    if user_id is None:
        return JSONResponse(
            status_code=401,
            content={"error": {"type": "session_required", "message": "Login required."}},
            headers=_NO_STORE,
        )
    store = _sessions(request)
    deleted = await store.revoke_session_by_id(session_id, user_id=user_id)
    if not deleted:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "session_not_found", "message": "会话不存在或已过期。"}},
        )
    raw_token = parse_session_cookie(request.headers.raw)
    headers: dict[str, str] = {"Cache-Control": "no-store"}
    if raw_token is not None and _hashlib.sha256(raw_token.encode()).hexdigest()[:8] == session_id:
        # 撤销的是当前会话：等价登出，把 cookie 一并作废。
        headers["Set-Cookie"] = clear_session_cookie()
    return Response(status_code=204, headers=headers)


# -- N008 登录事件（最近登录 / 新设备提醒） ------------------------------------


class LoginEventsSeenBody(BaseModel):
    """POST /auth/login-events/seen — 批量标记已读（省略 ids = 全部）。"""

    ids: list[int] | None = Field(default=None, max_length=100)


@router.get("/api/v1/auth/login-events", response_model=None, response_model_exclude_none=True)
async def list_login_events(request: Request, limit: int = 20) -> list[dict[str, object]] | JSONResponse:
    """本人最近登录事件（cap 20；kind=new_device 未读即「待确认的新设备」）。

    响应绝不含设备指纹哈希或任何 token 材料；每条都带 Cache-Control:
    no-store。basic 模式没有账户会话语义 → 401。"""
    if LumiSettings().LUMIRSS_AUTH_MODE != "session":
        return _reject(401, "session_required", "Login required.")
    user_id = await _current_user_id(request)
    if user_id is None:
        return _reject(401, "session_required", "Login required.")
    return JSONResponse(
        content={"items": await _sessions(request).list_login_events(user_id=user_id, limit=limit)},
        headers=_NO_STORE,
    )


@router.post("/api/v1/auth/login-events/seen", response_model=None)
async def mark_login_events_seen(
    request: Request, body: LoginEventsSeenBody | None = None
) -> JSONResponse:
    """批量标记已读（信任确认）：body 缺省/ids 缺省 = 全部未读事件。"""
    if LumiSettings().LUMIRSS_AUTH_MODE != "session":
        return _reject(401, "session_required", "Login required.")
    user_id = await _current_user_id(request)
    if user_id is None:
        return _reject(401, "session_required", "Login required.")
    ids = body.ids if body is not None else None
    marked = await _sessions(request).mark_login_events_seen(user_id=user_id, event_ids=ids)
    return JSONResponse(content={"marked": marked}, headers=_NO_STORE)
