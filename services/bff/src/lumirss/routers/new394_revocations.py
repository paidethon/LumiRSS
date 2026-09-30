"""NEW-394 通知动作撤销提示路由。

- POST /api/v1/notifications/{id}/revocation {reason}   登记撤销事实
- GET  /api/v1/notifications/{id}/revocation            查看登记

登记只由显式撤销动作触发（上游撤销流程 / 本人收回原事件）；读取侧
生效在 NEW-391 列表与 0392 聚合的联判里——撤销后 actionable 强制为
假并返回失效原因，绝不提供不可执行按钮。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.new391_notifications import NotificationNotFound
from lumirss.new394_revocations import (
    RevocationInvalid,
    get_revocation,
    register_revocation,
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


def _user() -> str:
    return require_user_id()


class RevocationBody(BaseModel):
    model_config = {"extra": "forbid"}

    reason: str = Field(min_length=1, max_length=300)


@router.post(
    "/api/v1/notifications/{notification_id}/revocation", response_model=None
)
async def post_revocation(
    notification_id: str, payload: RevocationBody, request: Request
) -> JSONResponse:
    try:
        user_id = _user()
    except Exception:  # noqa: BLE001
        return _error(401, "session_required", "请先登录。")
    try:
        result = await register_revocation(
            request.app.state.control_db,
            notification_id=notification_id,
            user_id=user_id,
            reason=payload.reason,
        )
    except NotificationNotFound:
        return _error(404, "notification_not_found", "没有这条通知。")
    except RevocationInvalid as exc:
        return _error(422, "invalid_revocation", str(exc))
    return JSONResponse(result, headers=_NO_STORE)


@router.get(
    "/api/v1/notifications/{notification_id}/revocation", response_model=None
)
async def get_revocation_route(
    notification_id: str, request: Request
) -> JSONResponse:
    try:
        user_id = _user()
    except Exception:  # noqa: BLE001
        return _error(401, "session_required", "请先登录。")
    found = await get_revocation(
        request.app.state.control_db,
        notification_id=notification_id,
        user_id=user_id,
    )
    if found is None:
        return _error(404, "revocation_not_found", "这条通知没有撤销登记。")
    return JSONResponse(found, headers=_NO_STORE)
