"""NEW-346 设备信任期限路由。

- POST   /api/v1/me/device-trust   密码复核 → 授予/续期当前设备信任
- GET    /api/v1/me/device-trust   当前设备状态 + 全部授予清单
- DELETE /api/v1/me/device-trust   吊销当前设备（?fingerprint= 吊销任意）

硬边界（测试断言）：授予绝不创建/延长 auth_sessions —— 服务端会话
的过期时间原样不动。仅 session 模式（basic 模式无账户语义）。
"""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.new346_device_trust import (
    DeviceTrustDenied,
    DeviceTrustInvalid,
    clean_hours,
    current_grant,
    fingerprint_of_request,
    grant_trust,
    is_trusted,
    list_grants,
)

router = APIRouter()


def _reject(status: int, err_type: str, message: str, **extra: object) -> JSONResponse:
    body: dict[str, Any] = {"error": {"type": err_type, "message": message}}
    if extra:
        body["error"] = {**body["error"], **extra}  # type: ignore[assignment]
    return JSONResponse(status_code=status, content=body, headers={"Cache-Control": "no-store"})


async def _require_user(request: Request) -> str | None:
    from lumirss.config import LumiSettings
    from lumirss.routers.auth import _current_user_id

    if LumiSettings().LUMIRSS_AUTH_MODE != "session":
        return None
    return await _current_user_id(request)


class TrustBody(BaseModel):
    model_config = {"extra": "forbid"}

    password: str = Field(min_length=1, max_length=256)
    hours: int = Field(default=12, ge=1, le=720)


def _password_verifier(request: Request, user_id: str, password: str):
    """控制库密码复核回调（绝不落任何明文）。"""

    async def verify() -> bool:
        from lumirss.accounts_store import verify_password_hash

        row = await request.app.state.control_db.fetch_one(
            "SELECT password_hash FROM users WHERE id = ?", (user_id,)
        )
        if row is None:
            return False
        return verify_password_hash(password, row["password_hash"])

    return verify


@router.post("/api/v1/me/device-trust", response_model=None)
async def post_device_trust(body: TrustBody, request: Request) -> JSONResponse:
    user_id = await _require_user(request)
    if user_id is None:
        return _reject(401, "session_required", "Login required.")
    fingerprint, label = fingerprint_of_request(request)
    try:
        clean_hours(body.hours)
        result = await grant_trust(
            request.app.state.db,
            fingerprint=fingerprint,
            device_label=label,
            verify_password=_password_verifier(request, user_id, body.password),
            hours=body.hours,
        )
    except DeviceTrustDenied:
        return _reject(401, "invalid_credentials", "Incorrect password.")
    except DeviceTrustInvalid as exc:
        return _reject(422, "device_trust_invalid", str(exc))
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@router.get("/api/v1/me/device-trust", response_model=None)
async def get_device_trust(request: Request) -> JSONResponse:
    user_id = await _require_user(request)
    if user_id is None:
        return _reject(401, "session_required", "Login required.")
    fingerprint, label = fingerprint_of_request(request)
    grant = await current_grant(request.app.state.db, fingerprint)

    return JSONResponse(
        {
            "currentDevice": {
                "deviceFingerprint": fingerprint[:8],
                "deviceLabel": label,
                "trusted": is_trusted(grant),
                "trustedUntil": grant["trustedUntil"] if grant else None,
            },
            "grants": await list_grants(request.app.state.db),
            "note": "设备信任不创建也不延长服务端会话；到期后敏感操作需重新验证。",
        },
        headers={"Cache-Control": "no-store"},
    )


@router.delete("/api/v1/me/device-trust", response_model=None)
async def delete_device_trust(request: Request, fingerprint: str | None = None) -> JSONResponse:
    user_id = await _require_user(request)
    if user_id is None:
        return _reject(401, "session_required", "Login required.")
    target = fingerprint
    if target is None:
        target, _label = fingerprint_of_request(request)
    else:
        # 传入的是 8 位前缀（列表展示口径）→ 还原为全量匹配前缀删除。
        pass
    from lumirss.new346_device_trust import revoke_trust_by_prefix

    revoked = await revoke_trust_by_prefix(request.app.state.db, target)
    if not revoked:
        return _reject(404, "grant_not_found", "该设备没有信任授予。")
    return JSONResponse({"revoked": True, "fingerprint": target[:8]})
