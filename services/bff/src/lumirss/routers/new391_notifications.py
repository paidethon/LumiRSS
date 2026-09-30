"""NEW-391 应用内通知收件箱路由。

- GET    /api/v1/notifications?kind=&unreadOnly=&limit=   本人通知（按类型过滤）
- POST   /api/v1/notifications/{id}/read                  标记已读（幂等集合语义）
- POST   /api/v1/notifications/read-all                   全部已读（可选 kind 过滤）
- DELETE /api/v1/notifications/{id}                       本人删除（保留清理动作）

通知只来自真实事件（写入口 lumirss.new391_notifications.record_event，
由发生事件的域在收尾时调用——本组内 NEW-399 的修订回复）；本路由没有
任何「造一条通知」的入口。私人事件只给本人：所有路径先取会话身份，
非本人的 id 一律 404 同形。
"""

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.new391_notifications import (
    KINDS,
    NotificationInvalid,
    NotificationNotFound,
    dismiss,
    list_notifications,
    mark_all_read,
    mark_read,
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


class ReadAllBody(BaseModel):
    model_config = {"extra": "forbid"}

    kind: str | None = Field(default=None)


@router.get("/api/v1/notifications", response_model=None)
async def get_notifications(
    request: Request,
    kind: str | None = Query(default=None),
    unreadOnly: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=100),
) -> JSONResponse:
    try:
        user_id = require_user_id()
    except Exception:  # noqa: BLE001 — 未认证上下文统一 401 同形
        return _error(401, "session_required", "请先登录。")
    try:
        payload = await list_notifications(
            request.app.state.control_db,
            user_id,
            kind=kind,
            unread_only=unreadOnly,
            limit=limit,
        )
    except NotificationInvalid as exc:
        return _error(422, "invalid_notification_query", str(exc))
    return JSONResponse(payload, headers=_NO_STORE)


@router.post("/api/v1/notifications/{notification_id}/read", response_model=None)
async def post_notification_read(
    notification_id: str, request: Request
) -> JSONResponse:
    try:
        user_id = require_user_id()
    except Exception:  # noqa: BLE001
        return _error(401, "session_required", "请先登录。")
    try:
        result = await mark_read(request.app.state.control_db, user_id, notification_id)
    except NotificationNotFound:
        return _error(404, "notification_not_found", "没有这条通知。")
    return JSONResponse(result, headers=_NO_STORE)


@router.post("/api/v1/notifications/read-all", response_model=None)
async def post_notifications_read_all(
    payload: ReadAllBody, request: Request
) -> JSONResponse:
    try:
        user_id = require_user_id()
    except Exception:  # noqa: BLE001
        return _error(401, "session_required", "请先登录。")
    try:
        result = await mark_all_read(
            request.app.state.control_db, user_id, kind=payload.kind
        )
    except NotificationInvalid as exc:
        return _error(422, "invalid_notification_kind", str(exc))
    return JSONResponse(result, headers=_NO_STORE)


@router.delete("/api/v1/notifications/{notification_id}", response_model=None)
async def delete_notification(notification_id: str, request: Request) -> JSONResponse:
    try:
        user_id = require_user_id()
    except Exception:  # noqa: BLE001
        return _error(401, "session_required", "请先登录。")
    try:
        removed = await dismiss(
            request.app.state.control_db, user_id, notification_id
        )
    except NotificationNotFound:
        return _error(404, "notification_not_found", "没有这条通知。")
    if not removed:
        return _error(404, "notification_not_found", "没有这条通知。")
    return JSONResponse({"dismissed": True}, headers=_NO_STORE)


@router.get("/api/v1/notifications/kinds", response_model=None)
async def get_notification_kinds(request: Request) -> JSONResponse:
    """类型词表（前端下拉与 392 规则面共用；无身份要求之外的暴露）。"""
    try:
        require_user_id()
    except Exception:  # noqa: BLE001
        return _error(401, "session_required", "请先登录。")
    return JSONResponse({"kinds": list(KINDS)}, headers=_NO_STORE)
