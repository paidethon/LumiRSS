"""Passkey (WebAuthn) endpoints — N006.

Surface (all under ``/api/v1/auth``):

- ``POST /passkeys/options``          — registration begin (session auth);
- ``POST /passkeys``                  — registration finish: the browser's
  RegistrationResponse JSON is verified with python-fido2 (RP ID, origin,
  single-use challenge, attestation structure, user presence) before the
  credential is stored (session auth);
- ``GET  /passkeys``                  — own credentials, id/label/created/
  last-used ONLY — never key material (session auth);
- ``DELETE /passkeys/{id}``           — requires CURRENT PASSWORD re-entry
  (plus a valid TOTP code when two-factor is enabled); 404 for anything
  not owned by the session user (session auth);
- ``POST /passkeys/login/options``    — username → allowCredentials; unknown
  usernames get the SAME generic empty shape (no user enumeration) (public);
- ``POST /passkeys/login``            — assertion verification; on success
  the SAME session-cookie minting path as password login, inside the SAME
  brute-force budget (public).

RP ID / origin follow the deterministic rule documented in
:mod:`lumirss.passkeys` (LUMIRSS_PUBLIC_ORIGIN, else request host).
Session-mode only: single-user (basic) mode is proxy-authenticated and
never sees these endpoints (401 session_required like /auth/password).
"""

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss import passkeys as pk
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


class PasskeyOptionsRequest(BaseModel):
    """POST /auth/passkeys/options — empty body allowed (reserved fields)."""

    labelHint: str | None = Field(default=None, max_length=64)


class PasskeyRegisterRequest(BaseModel):
    """POST /auth/passkeys — label + echoed challenge + RegistrationResponse."""

    label: str = Field(min_length=1, max_length=64)
    challenge: str = Field(min_length=16, max_length=512)
    id: str = Field(min_length=8, max_length=1024)
    rawId: str = Field(min_length=8, max_length=1024)
    type: str = Field(min_length=4, max_length=32)
    response: dict[str, object] = Field(min_length=1)


class PasskeyDeleteRequest(BaseModel):
    """DELETE /auth/passkeys/{id} — password re-entry (server-enforced)."""

    currentPassword: str = Field(min_length=1, max_length=256)
    totpCode: str | None = Field(default=None, max_length=64)


class PasskeyLoginOptionsRequest(BaseModel):
    """POST /auth/passkeys/login/options — username lookup (no enumeration)."""

    username: str | None = Field(default=None, max_length=64)


class PasskeyLoginRequest(BaseModel):
    """POST /auth/passkeys/login — AuthenticationResponse + echoed challenge."""

    username: str | None = Field(default=None, max_length=64)
    challenge: str = Field(min_length=16, max_length=512)
    id: str = Field(min_length=8, max_length=1024)
    rawId: str = Field(min_length=8, max_length=1024)
    type: str = Field(min_length=4, max_length=32)
    response: dict[str, object] = Field(min_length=1)


def _store(request: Request) -> pk.PasskeyStore:
    return pk.PasskeyStore(request.app.state.control_db)


_GENERIC_LOGIN_FAIL = "通行密钥验证失败。"


# ---- credential management (session auth) ---------------------------------


@router.post("/api/v1/auth/passkeys/options", response_model=None)
async def passkey_register_options(request: Request) -> dict[str, object] | JSONResponse:
    user_id = await _current_user_id(request)
    if user_id is None:
        return _reject(401, "session_required", "Login required.")
    user = await _control(request).get_user(user_id)
    if user is None:
        return _reject(401, "session_required", "Login required.")
    store = _store(request)
    challenge = pk.new_challenge()
    payload = pk.begin_registration(
        request,
        challenge=challenge,
        user_id=user_id,
        username=str(user["username"]),
        display_name=str(user["display_name"] or user["username"]),
        exclude_ids=await store.credential_ids(user_id=user_id),
    )
    await store.put_challenge(challenge, user_id=user_id, purpose="register")
    return {**payload, "challenge": challenge}


@router.post("/api/v1/auth/passkeys", response_model=None)
async def passkey_register_finish(
    body: PasskeyRegisterRequest, request: Request
) -> dict[str, object] | JSONResponse:
    user_id = await _current_user_id(request)
    if user_id is None:
        return _reject(401, "session_required", "Login required.")
    store = _store(request)
    # Single-use, user-bound challenge — burned BEFORE verification so a
    # failed attempt can never be retried with the same challenge.
    consumed = await store.consume_challenge(
        body.challenge, purpose="register", user_id=user_id
    )
    if consumed is None:
        return _reject(400, "challenge_invalid", "挑战无效或已过期，请重新开始注册。")
    try:
        credential_id, public_key, sign_count = pk.finish_registration(
            request,
            challenge=body.challenge,
            response={
                "id": body.id,
                "rawId": body.rawId,
                "type": body.type,
                "response": body.response,
            },
        )
    except pk.VerificationFailed:
        return _reject(400, "verification_failed", "注册响应验证失败，请重试。")
    credential = await store.create_credential(
        credential_id=credential_id,
        user_id=user_id,
        label=body.label.strip(),
        public_key=public_key,
        sign_count=sign_count,
    )
    await _control(request).audit(
        actor=user_id,
        action="passkey_register",
        object_type="webauthn_credential",
        object_id=credential_id[:16],
    )
    return credential


@router.get("/api/v1/auth/passkeys", response_model=None)
async def list_passkeys(request: Request) -> list[dict[str, object]] | JSONResponse:
    user_id = await _current_user_id(request)
    if user_id is None:
        return _reject(401, "session_required", "Login required.")
    return await _store(request).list_credentials(user_id=user_id)


@router.delete("/api/v1/auth/passkeys/{credential_id}", status_code=204, response_model=None)
async def delete_passkey(
    credential_id: str, body: PasskeyDeleteRequest, request: Request
) -> Response | JSONResponse:
    user_id = await _current_user_id(request)
    if user_id is None:
        return _reject(401, "session_required", "Login required.")
    user = await _control(request).get_user(user_id)
    if user is None:
        return _reject(401, "session_required", "Login required.")
    # Server-enforced re-auth: current password (every Lumi account has one)
    # plus a valid TOTP code when two-factor is enabled.
    if not verify_password_hash(body.currentPassword, str(user["password_hash"])):
        return _reject(401, "invalid_credentials", "密码不正确。")
    status = await totp_core.check_second_factor(
        request.app.state.control_db,
        request.app.state.secrets_store,
        user_id,
        body.totpCode,
    )
    if status == "missing":
        return _reject(400, "totp_code_required", "两步验证已开启，需要验证码。")
    if status == "invalid":
        return _reject(401, "totp_code_invalid", "验证码无效。")
    deleted = await _store(request).delete_credential(credential_id, user_id=user_id)
    if not deleted:
        return _reject(404, "passkey_not_found", "通行密钥不存在。")
    await _control(request).audit(
        actor=user_id,
        action="passkey_delete",
        object_type="webauthn_credential",
        object_id=credential_id[:16],
    )
    return Response(status_code=204, headers=_NO_STORE)


# ---- passkey login (public; same brute-force budget as password login) ----


@router.post(
    "/api/v1/auth/passkeys/login/options", response_model_exclude_none=True
)
async def passkey_login_options(
    body: PasskeyLoginOptionsRequest, request: Request
) -> dict[str, object]:
    """Username → allowCredentials. Unknown usernames and users without
    passkeys get the SAME generic shape (empty allow-list,
    ``passkeyAvailable: false``) — the endpoint reveals nothing."""
    store = _store(request)
    username = (body.username or "").strip().lower()
    allowed_ids: list[str] = []
    bound_user_id: str | None = None
    if username:
        user = await _control(request).get_user_by_username(username)
        if user is not None and user.get("status") == "active":
            bound_user_id = str(user["id"])
            allowed_ids = await store.credential_ids(user_id=bound_user_id)
    challenge = pk.new_challenge()
    payload = pk.begin_login(request, challenge=challenge, allowed_ids=allowed_ids)
    await store.put_challenge(challenge, user_id=bound_user_id or "", purpose="login")
    return {**payload, "challenge": challenge, "passkeyAvailable": bool(allowed_ids)}


@router.post(
    "/api/v1/auth/passkeys/login",
    response_model=AuthStatus,
    response_model_exclude_none=True,
)
async def passkey_login(
    body: PasskeyLoginRequest, request: Request, response: Response
) -> AuthStatus | JSONResponse:
    if LumiSettings().LUMIRSS_AUTH_MODE != "session":
        return _reject(
            400, "invalid_request", "Passkey login is not available in single-user mode."
        )
    if not login_attempts_allowed(request.scope):
        return JSONResponse(
            status_code=429,
            content=_RATE_LIMITED_BODY,
            headers={"Retry-After": str(login_retry_after_s(request.scope)), **_NO_STORE},
        )
    store = _store(request)
    # Single-use challenge: unknown/expired/replayed all delete nothing.
    challenge_row = await store.consume_challenge(body.challenge, purpose="login")
    if challenge_row is None:
        register_login_failure(request.scope)
        return _reject(401, "invalid_credentials", _GENERIC_LOGIN_FAIL)
    credential = await store.get_credential(body.rawId)
    if credential is None:
        register_login_failure(request.scope)
        return _reject(401, "invalid_credentials", _GENERIC_LOGIN_FAIL)
    # When the challenge was user-bound (login-options asked for a known
    # username) the asserted credential MUST belong to that user — the
    # browser enforces allowCredentials, the server enforces it for real.
    bound_user = str(challenge_row.get("user_id") or "")
    if bound_user and bound_user != str(credential["user_id"]):
        register_login_failure(request.scope)
        return _reject(401, "invalid_credentials", _GENERIC_LOGIN_FAIL)
    user = await _control(request).get_user(str(credential["user_id"]))
    if user is None or user.get("status") != "active":
        register_login_failure(request.scope)
        return _reject(401, "invalid_credentials", _GENERIC_LOGIN_FAIL)
    try:
        new_count = pk.finish_login(
            request,
            challenge=body.challenge,
            credential_row=credential,
            response={
                "id": body.id,
                "rawId": body.rawId,
                "type": body.type,
                "response": body.response,
            },
        )
    except pk.VerificationFailed:
        register_login_failure(request.scope)
        return _reject(401, "invalid_credentials", _GENERIC_LOGIN_FAIL)
    await store.record_usage(body.rawId, sign_count=new_count)
    user_id = str(user["id"])
    reset_login_failures(request.scope)
    await _control(request).audit(
        actor=user_id, action="passkey_login", object_type="user", object_id=user_id
    )
    return await _mint_session(request, response, user_id)
