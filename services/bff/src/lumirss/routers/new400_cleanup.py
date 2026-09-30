"""NEW-400 个人功能使用清理路由。

- GET  /api/v1/settings/module-cleanup                清单（实时计数 + 留痕）
- POST /api/v1/settings/module-cleanup/{key}/close    本人关闭 + 数据去留
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.new400_cleanup import (
    CleanupInvalid,
    ModuleUnknown,
    close_module,
    module_cleanup,
)
from lumirss.user_scope import require_user_id

router = APIRouter()

_NO_STORE = {"Cache-Control": "no-store"}


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
        headers=_NO_STORE,
    )


class CloseBody(BaseModel):
    model_config = {"extra": "forbid"}

    retention: str = Field(min_length=1, max_length=8)


@router.get("/api/v1/settings/module-cleanup", response_model=None)
async def get_cleanup(request: Request) -> JSONResponse:
    try:
        user_id = require_user_id()
    except Exception:  # noqa: BLE001
        return _error(401, "session_required", "请先登录。")
    return JSONResponse(
        await module_cleanup(request.app.state.control_db, user_id),
        headers=_NO_STORE,
    )


@router.post("/api/v1/settings/module-cleanup/{module_key}/close", response_model=None)
async def post_close(
    module_key: str, payload: CloseBody, request: Request
) -> JSONResponse:
    try:
        user_id = require_user_id()
    except Exception:  # noqa: BLE001
        return _error(401, "session_required", "请先登录。")
    try:
        return JSONResponse(
            await close_module(
                request.app.state.control_db,
                user_id,
                module_id=module_key,
                retention=payload.retention,
            ),
            headers=_NO_STORE,
        )
    except ModuleUnknown:
        return _error(404, "module_not_found", "模块不存在。")
    except CleanupInvalid as exc:
        return _error(422, "invalid_cleanup", str(exc))
