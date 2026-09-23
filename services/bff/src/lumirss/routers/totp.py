"""TOTP two-factor endpoints — N007.

Surface (all under ``/api/v1/auth``):

- ``GET  /auth/totp``         — status: enabled flag + remaining recovery
  codes (counts only, never the codes or the secret) (session auth);
- ``POST /auth/totp/setup``   — generate + store the shared secret (per-user
  secrets file, 0600), return secret + otpauth:// URI ONCE (session auth);
- ``POST /auth/totp/enable``  — verify one code against the pending secret,
  flip enabled, generate 8 recovery codes — plaintext returned ONCE, stored
  only as salted SHA-256 (session auth);
- ``POST /auth/totp/disable`` — server-enforced: current password AND a
  valid TOTP/recovery code (session auth);
- ``POST /auth/totp/verify``  — two-step login completion: pendingToken
  (from ``totpRequired`` login response) + code → real session via the
  SAME minting path as password login, inside the SAME brute-force budget
  (public; the pending token alone grants nothing).

Login integration lives in ``routers/auth.py`` (password login returns
``{totpRequired, pendingToken}`` when the account has TOTP enabled).
Session-mode only, like the rest of the multi-account auth surface.
"""

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss import totp as totp_core
from lumirss.accounts_store import verify_password_hash
from lumirss.config import LumiSettings
from lumirss.middleware import (
    login_attempts_allowed,
    login_retry_after_s,
    register_login_failure,
    reset_login_failures,
)
from lumirss.models import AuthStatus
from lumirss.routers.auth import (
    _NO_STORE,
    _RATE_LIMITED_BODY,
    _control,
    _current_user_id,
    _mint_session,
    _reject,
)

router = APIRouter()


class TotpSetupResponse(BaseModel):
    """Secret + provisioning URI — shown to the user exactly once."""

    secret: str
    otpauthUri: str


class TotpEnableRequest(BaseModel):
    code: str = Field(min_length=6, max_length=16)


class TotpEnableResponse(BaseModel):
    """Plaintext recovery codes — returned exactly once, stored hashed."""

    recoveryCodes: list[str]


class TotpDisableRequest(BaseModel):
    code: str = Field(min_length=1, max_length=64)
    currentPassword: str = Field(min_length=1, max_length=256)


class TotpVerifyRequest(BaseModel):
    """POST /auth/totp/verify — pending token + TOTP/recovery code."""

    pendingToken: str = Field(min_length=16, max_length=256)
    code: str = Field(min_length=1, max_length=64)


def _store(request: Request) -> totp_core.TotpStore:
    return totp_core.TotpStore(request.app.state.control_db)


def _secrets(request: Request):
    return request.app.state.secrets_store


def _remaining_codes(row: dict[str, object]) -> list[str]:
    import json as _json

    try:
        return list(_json.loads(str(row.get("recovery_codes") or "[]")))
    except ValueError:  # corrupt row counts as zero
        return []


@router.get("/api/v1/auth/totp", response_model=None)
async def totp_status(request: Request) -> dict[str, object] | JSONResponse:
    user_id = await _current_user_id(request)
    if user_id is None:
        return _reject(401, "session_required", "Login required.")
    row = await _store(request).get_settings(user_id)
    return {
        "enabled": bool(int(row["enabled"])),
        "recoveryCodesRemaining": len(_remaining_codes(row)),
    }


@router.post("/api/v1/auth/totp/setup", response_model=None)
async def totp_setup(request: Request) -> dict[str, object] | JSONResponse:
    user_id = await _current_user_id(request)
    if user_id is None:
        return _reject(401, "session_required", "Login required.")
    user = await _control(request).get_user(user_id)
    if user is None:
        return _reject(401, "session_required", "Login required.")
    store = _store(request)
    if await store.is_enabled(user_id):
        return _reject(400, "totp_enabled", "两步验证已开启；请先关闭再重新设置。")
    secret = totp_core.new_secret()
    # Per-user secrets file (0600) — never SQLite, never the browser twice:
    # the response below is the only time the secret is visible.
    totp_core.write_secret(_secrets(request), secret)
    await _control(request).audit(actor=user_id, action="totp_setup", object_type="user", object_id=user_id)
    return {
        "secret": secret,
        "otpauthUri": totp_core.provisioning_uri(secret, username=str(user["username"])),
    }


@router.post("/api/v1/auth/totp/enable", response_model=None)
async def totp_enable(
    body: TotpEnableRequest, request: Request
) -> dict[str, object] | JSONResponse:
    user_id = await _current_user_id(request)
    if user_id is None:
        return _reject(401, "session_required", "Login required.")
    store = _store(request)
    if await store.is_enabled(user_id):
        return _reject(400, "totp_enabled", "两步验证已开启；请先关闭再重新设置。")
    secret = totp_core.read_secret(_secrets(request))
    if not secret:
        return _reject(400, "totp_not_setup", "请先获取验证密钥（setup）。")
    code = body.code.strip()
    if not code.isdigit() or len(code) != 6:
        return _reject(400, "totp_code_invalid", "验证码格式不正确。")
    slice_value = totp_core.match_timeslice(secret, code)
    if slice_value is None:
        return _reject(401, "totp_code_invalid", "验证码无效。")
    salt, codes = totp_core.new_recovery_codes()
    await store.save_settings(
        {
            "user_id": user_id,
            "enabled": 1,
            "recovery_salt": salt,
            "recovery_codes": totp_core.hash_recovery_codes(salt, codes),
            "last_used_timeslice": slice_value,
        }
    )
    await _control(request).audit(actor=user_id, action="totp_enable", object_type="user", object_id=user_id)
    return {"recoveryCodes": codes}


@router.post("/api/v1/auth/totp/disable", response_model=None)
async def totp_disable(
    body: TotpDisableRequest, request: Request
) -> dict[str, object] | JSONResponse:
    user_id = await _current_user_id(request)
    if user_id is None:
        return _reject(401, "session_required", "Login required.")
    user = await _control(request).get_user(user_id)
    if user is None:
        return _reject(401, "session_required", "Login required.")
    if not await _store(request).is_enabled(user_id):
        return _reject(400, "totp_not_enabled", "两步验证未开启。")
    # Server-enforced: password AND a live second factor.
    if not verify_password_hash(body.currentPassword, str(user["password_hash"])):
        return _reject(401, "invalid_credentials", "密码不正确。")
    status = await totp_core.check_second_factor(
        request.app.state.control_db, _secrets(request), user_id, body.code
    )
    if status == "missing":
        return _reject(400, "totp_code_required", "需要提供验证码或恢复码。")
    if status != "ok":
        return _reject(401, "totp_code_invalid", "验证码无效。")
    await _store(request).disable(user_id)
    totp_core.delete_secret(_secrets(request))
    await _store(request).purge_pending_for(user_id)
    await _control(request).audit(actor=user_id, action="totp_disable", object_type="user", object_id=user_id)
    return {"disabled": True}


@router.post(
    "/api/v1/auth/totp/verify",
    response_model=AuthStatus,
    response_model_exclude_none=True,
)
async def totp_verify(
    body: TotpVerifyRequest, request: Request, response: Response
) -> AuthStatus | JSONResponse:
    if LumiSettings().LUMIRSS_AUTH_MODE != "session":
        return _reject(400, "invalid_request", "Two-step login is not available in single-user mode.")
    if not login_attempts_allowed(request.scope):
        return JSONResponse(
            status_code=429,
            content=_RATE_LIMITED_BODY,
            headers={"Retry-After": str(login_retry_after_s(request.scope)), **_NO_STORE},
        )
    store = _store(request)
    # One attempt per pending token: burned before the code is judged, so
    # a wrong code requires a fresh password login (and fresh token).
    user_id = await store.consume_pending_login(body.pendingToken)
    if user_id is None:
        register_login_failure(request.scope)
        return _reject(401, "pending_token_invalid", "登录请求已过期，请重新登录。")
    status = await totp_core.check_second_factor(
        request.app.state.control_db, _secrets(request), user_id, body.code
    )
    if status == "missing":
        return _reject(400, "totp_code_required", "需要提供验证码或恢复码。")
    if status != "ok":
        register_login_failure(request.scope)
        return _reject(401, "totp_code_invalid", "验证码无效。")
    reset_login_failures(request.scope)
    await _control(request).audit(actor=user_id, action="totp_login", object_type="user", object_id=user_id)
    return await _mint_session(request, response, user_id)
