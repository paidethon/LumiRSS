"""NEW-347 单项授权撤销中心路由。

- GET  /api/v1/privacy/authorizations                      凭据面清单（无令牌材料）
- POST /api/v1/privacy/authorizations/{kind}/{ref}/revoke  逐项真实撤销
- GET  /api/v1/privacy/authorizations/events               撤销留痕
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from lumirss.new347_authorization_center import (
    AuthorizationCenter,
    list_revoke_events,
)

router = APIRouter()


def _center(request: Request) -> AuthorizationCenter:
    return AuthorizationCenter(request.app.state.db, request.app.state.secrets_store)


async def _require_user(request: Request) -> str | None:
    from lumirss.config import LumiSettings
    from lumirss.routers.auth import _current_user_id

    if LumiSettings().LUMIRSS_AUTH_MODE != "session":
        return None
    return await _current_user_id(request)


@router.get("/api/v1/privacy/authorizations", response_model=None)
async def list_authorizations(request: Request) -> JSONResponse:
    user_id = await _require_user(request)
    if user_id is None:
        return JSONResponse(
            status_code=401,
            content={
                "error": {"type": "session_required", "message": "Login required."}
            },
        )
    payload = await _center(request).inventory()
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


@router.get("/api/v1/privacy/authorizations/events", response_model=None)
async def authorization_events(request: Request, limit: int = 50) -> JSONResponse:
    user_id = await _require_user(request)
    if user_id is None:
        return JSONResponse(
            status_code=401,
            content={
                "error": {"type": "session_required", "message": "Login required."}
            },
        )
    return JSONResponse(
        {"items": await list_revoke_events(request.app.state.db, limit)},
        headers={"Cache-Control": "no-store"},
    )


@router.post("/api/v1/privacy/authorizations/{kind}/{ref}/revoke", response_model=None)
async def revoke_authorization(kind: str, ref: str, request: Request) -> JSONResponse:
    user_id = await _require_user(request)
    if user_id is None:
        return JSONResponse(
            status_code=401,
            content={
                "error": {"type": "session_required", "message": "Login required."}
            },
        )
    result = await _center(request).revoke(kind, ref)
    if result is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "type": "authorization_not_found",
                    "message": "未知凭据面或对象不存在/已撤销。",
                }
            },
        )
    return JSONResponse(result, headers={"Cache-Control": "no-store"})
