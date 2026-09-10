"""Session-auth endpoints (LUMIRSS_AUTH_MODE=session).

The browser flow: one password → bcrypt verification → opaque long-lived
session cookie (Secure/HttpOnly/SameSite=Strict, ``__Host-`` prefixed in
production). Logout/password-change revocation semantics live in
auth_store.py; the cookie/CSRF mechanics live in middleware.py.

Every response here is ``Cache-Control: no-store`` — nothing about the
auth state may be cached by intermediaries.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from lumirss.auth_store import AuthStore, InvalidCredentials
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


def _auth_store(request: Request) -> AuthStore:
    return AuthStore(request.app.state.db)


def _max_age_seconds() -> int:
    return LumiSettings().LUMIRSS_SESSION_MAX_AGE_DAYS * 86400


def _iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=UTC).isoformat(timespec="seconds")


@router.post(
    "/api/v1/auth/login",
    response_model=AuthStatus,
    response_model_exclude_none=True,
)
async def login(body: LoginRequest, request: Request, response: Response) -> AuthStatus:
    """Verify the password, mint a session, set the cookie.

    Failures only count toward the brute-force budget (see middleware);
    a correct password resets it, so honest retries never lock the user
    out. The wrong-password and not-initialized replies deliberately
    share the generic shape — no oracle for an attacker.
    """
    if not login_attempts_allowed(request.scope):
        retry_after = login_retry_after_s(request.scope)
        return JSONResponse(
            status_code=429,
            content=_RATE_LIMITED_BODY,
            headers={"Retry-After": str(retry_after), **_NO_STORE},
        )
    store = _auth_store(request)
    try:
        await store.verify_password(body.password)
    except InvalidCredentials:
        register_login_failure(request.scope)
        raise
    raw_token, expires_at = await store.create_session(
        LumiSettings().LUMIRSS_SESSION_MAX_AGE_DAYS,
        user_agent=request.headers.get("user-agent"),
    )
    reset_login_failures(request.scope)
    response.headers["Set-Cookie"] = build_session_cookie(raw_token, _max_age_seconds())
    response.headers["Cache-Control"] = "no-store"
    return AuthStatus(authenticated=True, expiresAt=_iso(expires_at))


@router.get(
    "/api/v1/auth/session",
    response_model=AuthStatus,
    response_model_exclude_none=True,
)
async def session_status(request: Request) -> AuthStatus:
    """Public probe: which auth layer is active, and is this browser
    holding a live session? (basic mode: authenticated reflects the
    proxy — the app never gates on it.)"""
    if LumiSettings().LUMIRSS_AUTH_MODE != "session":
        return AuthStatus(authenticated=True, mode="basic")
    raw_token = parse_session_cookie(request.headers.raw)
    if raw_token is None:
        return AuthStatus(authenticated=False)
    expires_at = await _auth_store(request).get_valid_session(raw_token)
    if expires_at is None:
        return AuthStatus(authenticated=False)
    return AuthStatus(authenticated=True, expiresAt=_iso(expires_at))


@router.post(
    "/api/v1/auth/logout",
    response_model=AuthStatus,
)
async def logout(request: Request, response: Response) -> AuthStatus:
    """Revoke the current session and expire the cookie."""
    raw_token = parse_session_cookie(request.headers.raw)
    if raw_token is not None:
        await _auth_store(request).revoke_session(raw_token)
    response.headers["Set-Cookie"] = clear_session_cookie()
    response.headers["Cache-Control"] = "no-store"
    return AuthStatus(authenticated=False)


@router.post(
    "/api/v1/auth/logout-all",
    response_model=AuthStatus,
)
async def logout_all(request: Request, response: Response) -> AuthStatus:
    """Revoke every session (all devices), including this one."""
    await _auth_store(request).revoke_all_sessions()
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
    """Change the password: verify current, replace hash, revoke ALL
    sessions, then immediately mint a fresh session for THIS device so
    the operator is not bounced to the login screen mid-action."""
    store = _auth_store(request)
    await store.verify_password(body.currentPassword)
    await store.set_password(body.newPassword)
    raw_token, expires_at = await store.create_session(
        LumiSettings().LUMIRSS_SESSION_MAX_AGE_DAYS,
        user_agent=request.headers.get("user-agent"),
    )
    response.headers["Set-Cookie"] = build_session_cookie(raw_token, _max_age_seconds())
    response.headers["Cache-Control"] = "no-store"
    return AuthStatus(authenticated=True, expiresAt=_iso(expires_at))
