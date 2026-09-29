"""NEW-337 空间活动摘要路由。

- GET /api/v1/spaces/{sid}/activity?from=ISO&to=ISO   用户选时间段查看共享面变化

只汇总空间共享面事件；私人阅读记录不在任何空间视图内（模块级注释）。
"""

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response

from lumirss.new337_activity import ActivitySummary
from lumirss.space_core import SpaceArchived, SpaceInvalid, SpaceNotFound, SpaceStore
from lumirss.user_scope import require_user_id

router = APIRouter()


def _summary(request: Request) -> ActivitySummary:
    return ActivitySummary(
        request.app.state.control_db, SpaceStore(request.app.state.control_db)
    )


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


@router.get("/api/v1/spaces/{space_id}/activity")
async def space_activity(
    space_id: str,
    request: Request,
    frm: str | None = Query(default=None, alias="from"),
    to: str | None = Query(default=None),
) -> Response:
    user_id = require_user_id()
    try:
        view = await _summary(request).summarize(
            space_id, actor_user_id=user_id, from_raw=frm, to_raw=to
        )
    except SpaceNotFound:
        return _error(404, "space_not_found", "空间不存在。")
    except SpaceArchived:
        return _error(409, "space_archived", "空间已归档。")
    except SpaceInvalid as exc:
        return _error(422, "invalid_space", str(exc))
    return JSONResponse(view)
