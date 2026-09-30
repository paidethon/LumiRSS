"""NEW-397 实例服务状态页路由（已登录用户）。

- GET  /api/v1/status/services          台账最新状态 + 每面最近历史
- POST /api/v1/status/services/check    立即执行本地检测并落台账
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from lumirss.new397_status import run_checks, status_page
from lumirss.user_scope import require_user_id

router = APIRouter()

_NO_STORE = {"Cache-Control": "no-store"}


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
        headers=_NO_STORE,
    )


@router.get("/api/v1/status/services", response_model=None)
async def get_services(request: Request) -> JSONResponse:
    try:
        require_user_id()
    except Exception:  # noqa: BLE001
        return _error(401, "session_required", "请先登录。")
    return JSONResponse(
        await status_page(request.app.state.control_db), headers=_NO_STORE
    )


@router.post("/api/v1/status/services/check", response_model=None)
async def post_check(request: Request) -> JSONResponse:
    try:
        require_user_id()
    except Exception:  # noqa: BLE001
        return _error(401, "session_required", "请先登录。")
    return JSONResponse(
        await run_checks(request.app.state.control_db), headers=_NO_STORE
    )
