"""NEW-341 个人数据访问记录路由。

- GET /api/v1/privacy/access-log?limit=  本人被共享入口访问的最小事件
  + 记录范围 + 「无法记录」边界的如实说明。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from lumirss.new341_access_log import list_access_events

router = APIRouter()


async def _require_user(request: Request) -> str | None:
    from lumirss.config import LumiSettings
    from lumirss.routers.auth import _current_user_id

    if LumiSettings().LUMIRSS_AUTH_MODE != "session":
        return None
    return await _current_user_id(request)


@router.get("/api/v1/privacy/access-log", response_model=None)
async def get_access_log(request: Request, limit: int = 50) -> JSONResponse:
    user_id = await _require_user(request)
    if user_id is None:
        return JSONResponse(
            status_code=401,
            content={
                "error": {"type": "session_required", "message": "Login required."}
            },
            headers={"Cache-Control": "no-store"},
        )
    payload = await list_access_events(request.app.state.db, limit)
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})
