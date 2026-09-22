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
    USERNAME_RE,
    AccountError,
    AccountsStore,
    InviteInvalid,
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
from lumirss.models import AuthStatus, LoginRequest, PasswordChangeRequest

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


async def _mint_session(request: Request, response: Response, user_id: str) -> AuthStatus:
    raw_token, expires_at = await _sessions(request).create_session(
        LumiSettings().LUMIRSS_SESSION_MAX_AGE_DAYS,
        user_agent=request.headers.get("user-agent"),
        user_id=user_id,
    )
    response.headers["Set-Cookie"] = build_session_cookie(raw_token, _max_age_seconds())
    response.headers["Cache-Control"] = "no-store"
    return AuthStatus(authenticated=True, expiresAt=_iso(expires_at))


async def _current_user_id(request: Request) -> str | None:
    raw_token = parse_session_cookie(request.headers.raw)
    if raw_token is None:
        return None
    resolved = await _sessions(request).get_valid_session_user(raw_token)
    return resolved[0] if resolved else None


@router.post(
    "/api/v1/auth/login",
    response_model=AuthStatus,
    response_model_exclude_none=True,
)
async def login(body: LoginRequest, request: Request, response: Response) -> AuthStatus:
    """Verify credentials, mint a per-user session.

    Wrong-password and unknown-username share the generic failure shape
    and the same brute-force budget (no account oracle).
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
    reset_login_failures(request.scope)
    await _control(request).audit(actor=str(user["id"]), action="login", object_type="user", object_id=str(user["id"]))
    return await _mint_session(request, response, str(user["id"]))


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
) -> AuthStatus:
    """Change own password: verify current, replace hash, revoke ALL of
    this user's sessions, then mint a fresh session for THIS device."""
    user_id = await _current_user_id(request)
    if user_id is None:
        return _reject(401, "session_required", "Login required.")
    user = await _control(request).get_user(user_id)
    if user is None:
        return _reject(401, "session_required", "Login required.")
    if not verify_password_hash(body.currentPassword, str(user["password_hash"])):
        return _reject(401, "invalid_credentials", "Incorrect current password.")
    if len(body.newPassword) < MIN_PASSWORD_LENGTH:
        return _reject(400, "weak_password", f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    await _control(request).set_password_hash(user_id, hash_password(body.newPassword))
    await _sessions(request).revoke_all_sessions(user_id=user_id)
    await _control(request).audit(actor=user_id, action="password_change", object_type="user", object_id=user_id)
    return await _mint_session(request, response, user_id)


@router.get("/api/v1/auth/activation-preview", response_model_exclude_none=True)
async def activation_preview(request: Request, token: str) -> dict[str, object]:
    """Honest activation screen state: is the invite usable, is a
    FreshRSS account ready? Reveals nothing beyond yes/no — no labels,
    no emails, no pool usernames."""
    accounts = _control(request)
    token_hash = hash_token(token)
    row = await accounts._db.fetch_one("SELECT expires_at, used_at, revoked_at, kind FROM invites WHERE token_hash = ?", (token_hash,))
    now = datetime.now(UTC).timestamp()
    valid = bool(row) and row["used_at"] is None and row["revoked_at"] is None and int(row["expires_at"]) > now
    pool = await accounts.pool_status()
    return {
        "valid": valid,
        "kind": str(row["kind"]) if (valid and row) else None,
        "freshrssReady": bool(valid and pool.get("ready", 0) > 0),
    }


@router.post(
    "/api/v1/auth/activate",
    response_model=AuthStatus,
    response_model_exclude_none=True,
)
async def activate_account(body: ActivateAccountRequest, request: Request, response: Response) -> AuthStatus:
    """Redeem a signup invite: create the independent account, bind an
    own FreshRSS account from the pool, mint a session.

    Pool-empty is an explicit pending-binding state — the account is
    usable and the UI shows "RSS source binding pending"; the server
    never falls back to shared credentials.
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
    except InviteInvalid:
        return _reject(400, "invite_invalid", "Invitation is invalid, expired or already used.")
    if str(invite.get("kind") or "signup") != "signup":
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
        await accounts._db.execute("UPDATE invites SET used_at = NULL, used_by = NULL WHERE token_hash = ?", (token_hash,))
        return _reject(400, "invalid_username", str(exc))
    user_id = str(user["id"])
    await accounts._db.execute("UPDATE invites SET used_by = ? WHERE token_hash = ?", (user_id, token_hash))
    # FreshRSS binding from the pool — atomic assignment, honest pending.
    assigned = await accounts.pool_assign(user_id)
    if assigned is not None:
        from lumirss.control_resources import bind_freshrss_account

        await bind_freshrss_account(request.app.state, user_id, str(assigned["freshrss_username"]), str(assigned["base_url"]))
    await accounts.audit(actor=user_id, action="account_activate", object_type="user", object_id=user_id, detail="pool_assigned" if assigned else "binding_pending")
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
