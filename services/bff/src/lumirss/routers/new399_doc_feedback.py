"""NEW-399 帮助文档反馈路由。

用户侧：
- POST /api/v1/help/feedback      提交段落问题（版本 + 锚点自动定位）
- GET  /api/v1/help/feedback      本人反馈与处理结果

管理员侧：
- GET  /api/v1/admin/help/feedback               队列（可按 status 过滤）
- POST /api/v1/admin/help/feedback/{id}/resolve  修订 + 回复（终态，含通知）
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.new399_doc_feedback import (
    FeedbackInvalid,
    FeedbackNotFound,
    create_feedback,
    list_all_feedback,
    list_own_feedback,
    resolve_feedback,
)
from lumirss.routers.admin import _NO_STORE, _require_admin
from lumirss.user_scope import require_user_id

router = APIRouter()


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
        headers=_NO_STORE,
    )


class FeedbackBody(BaseModel):
    model_config = {"extra": "forbid"}

    docPath: str = Field(min_length=1, max_length=200)
    anchor: str | None = Field(default=None, max_length=200)
    question: str = Field(min_length=1, max_length=1000)


class ResolveBody(BaseModel):
    model_config = {"extra": "forbid"}

    revisionNote: str = Field(min_length=1, max_length=1000)
    reply: str = Field(min_length=1, max_length=1000)


@router.post("/api/v1/help/feedback", response_model=None)
async def post_feedback(payload: FeedbackBody, request: Request) -> JSONResponse:
    try:
        user_id = require_user_id()
    except Exception:  # noqa: BLE001
        return _error(401, "session_required", "请先登录。")
    try:
        result = await create_feedback(
            request.app.state.control_db,
            user_id,
            doc_path=payload.docPath,
            anchor=payload.anchor or "",
            question=payload.question,
        )
    except FeedbackInvalid as exc:
        return _error(400, "invalid_feedback", str(exc))
    return JSONResponse(result, status_code=201, headers=_NO_STORE)


@router.get("/api/v1/help/feedback", response_model=None)
async def get_own_feedback(request: Request) -> JSONResponse:
    try:
        user_id = require_user_id()
    except Exception:  # noqa: BLE001
        return _error(401, "session_required", "请先登录。")
    return JSONResponse(
        await list_own_feedback(request.app.state.control_db, user_id),
        headers=_NO_STORE,
    )


@router.get("/api/v1/admin/help/feedback", response_model=None)
async def get_admin_feedback(request: Request, status: str | None = None) -> JSONResponse:
    principal = await _require_admin(request)
    if principal is None:
        return _error(403, "forbidden", "需要管理员角色。")
    return JSONResponse(
        await list_all_feedback(request.app.state.control_db, status=status),
        headers=_NO_STORE,
    )


@router.post("/api/v1/admin/help/feedback/{feedback_id}/resolve", response_model=None)
async def post_resolve(
    feedback_id: str, payload: ResolveBody, request: Request
) -> JSONResponse:
    principal = await _require_admin(request)
    if principal is None:
        return _error(403, "forbidden", "需要管理员角色。")
    try:
        return JSONResponse(
            await resolve_feedback(
                request.app.state.control_db,
                feedback_id=feedback_id,
                revision_note=payload.revisionNote,
                reply=payload.reply,
            ),
            headers=_NO_STORE,
        )
    except FeedbackNotFound:
        return _error(404, "feedback_not_found", "没有这条反馈。")
    except FeedbackInvalid as exc:
        return _error(422, "invalid_resolve", str(exc))
