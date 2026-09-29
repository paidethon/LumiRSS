"""NEW-304 Webhook 密钥轮换路由（管理员；受控秘密通道）。

- POST /api/v1/admin/webhook-keys/rotate {windowMinutes?}
      admin guard + step-up（op=webhook_key_rotation，target=本人）
      → 明文钥仅在本次响应出现一次；
- GET  /api/v1/admin/webhook-keys  切换结果（状态/窗口/验证计数）。
      任何响应都不含密钥材料。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.new304_webhook_keys import (
    KeyRotationInvalid,
    SigningKeyStore,
    clean_window_minutes,
)
from lumirss.routers.admin import _NO_STORE, _require_admin
from lumirss.step_up import require_step_up

router = APIRouter(prefix="/api/v1/admin/webhook-keys")

STEP_UP_OPERATION = "webhook_key_rotation"


class RotateBody(BaseModel):
    model_config = {"extra": "forbid"}

    windowMinutes: int | None = Field(default=None, ge=1, le=60)


@router.post("/rotate", response_model=None, response_model_exclude_none=True)
async def rotate_webhook_key(
    payload: RotateBody | None = None, request: Request = None
) -> JSONResponse:
    principal = await _require_admin(request)
    if principal is None:
        return JSONResponse(
            status_code=403,
            content={"error": {"type": "forbidden", "message": "需要管理员角色。"}},
            headers=_NO_STORE,
        )
    denial = await require_step_up(
        request, principal, STEP_UP_OPERATION, principal["user_id"]
    )
    if denial is not None:
        return denial
    window = payload.windowMinutes if payload is not None else None
    try:
        window = clean_window_minutes(window if window is not None else 10)
    except KeyRotationInvalid as exc:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "invalid_rotation_payload", "message": str(exc)}},
            headers=_NO_STORE,
        )
    result = await SigningKeyStore(request.app.state.control_db).rotate(window)
    from lumirss.accounts_store import AccountsStore

    await AccountsStore(request.app.state.control_db).audit(
        actor=principal["user_id"],
        action="webhook_key_rotated",
        object_type="webhook_signing_key",
        object_id=result["keyId"],
        outcome="ok",
    )
    return JSONResponse(result, headers=_NO_STORE)


@router.get("", response_model=None, response_model_exclude_none=True)
async def webhook_keys_snapshot(request: Request) -> JSONResponse:
    principal = await _require_admin(request)
    if principal is None:
        return JSONResponse(
            status_code=403,
            content={"error": {"type": "forbidden", "message": "需要管理员角色。"}},
            headers=_NO_STORE,
        )
    snapshot = await SigningKeyStore(request.app.state.control_db).snapshot()
    return JSONResponse(snapshot, headers=_NO_STORE)
