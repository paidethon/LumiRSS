"""NEW-396 新功能回退偏好路由。

- GET /api/v1/interaction-modes                 注册面清单 + 本人当前选择
- PUT /api/v1/interaction-modes/{surface}       new / classic（classic 带期限）
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.new396_modes import ModeInvalid, SurfaceUnknown, list_modes, set_mode
from lumirss.user_scope import require_user_id

router = APIRouter()

_NO_STORE = {"Cache-Control": "no-store"}


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
        headers=_NO_STORE,
    )


class ModeBody(BaseModel):
    model_config = {"extra": "forbid"}

    mode: str = Field(min_length=1, max_length=16)


@router.get("/api/v1/interaction-modes", response_model=None)
async def get_modes(request: Request) -> JSONResponse:
    try:
        user_id = require_user_id()
    except Exception:  # noqa: BLE001
        return _error(401, "session_required", "请先登录。")
    return JSONResponse(
        await list_modes(request.app.state.control_db, user_id), headers=_NO_STORE
    )


@router.put("/api/v1/interaction-modes/{surface}", response_model=None)
async def put_mode(surface: str, payload: ModeBody, request: Request) -> JSONResponse:
    try:
        user_id = require_user_id()
    except Exception:  # noqa: BLE001
        return _error(401, "session_required", "请先登录。")
    try:
        result = await set_mode(
            request.app.state.control_db, user_id, surface=surface, mode=payload.mode
        )
    except SurfaceUnknown:
        return _error(404, "surface_not_found", "交互面不存在。")
    except ModeInvalid as exc:
        return _error(422, "invalid_mode", str(exc))
    return JSONResponse(result, headers=_NO_STORE)
