"""NEW-292 邮件会话串联路由 — 按真实字段自动成串 + 手动关联兜底。

- POST /api/v1/email-materials/{id}/thread-link {targetId}
      → 手动关联（并入目标会话；两边都无会话则新建），返回会话视图
- GET  /api/v1/email-threads/{threadId}
      → 会话成员（按导入先后排序；自动/手动来源如实标注）
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.new292_email_threads import (
    ThreadLinkError,
    ThreadTargetNotFound,
    link_manually,
    thread_view,
)

router = APIRouter()


class ThreadLinkBody(BaseModel):
    model_config = {"extra": "forbid"}

    targetId: str = Field(min_length=1, max_length=64)


@router.post("/api/v1/email-materials/{material_id}/thread-link")
async def post_thread_link(
    material_id: str, payload: ThreadLinkBody, request: Request
) -> Response:
    try:
        view = await link_manually(
            request.app.state.db, material_id, payload.targetId
        )
    except ThreadTargetNotFound as exc:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "email_material_not_found", "message": str(exc)}},
        )
    except ThreadLinkError as exc:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "thread_link_invalid", "message": str(exc)}},
        )
    return JSONResponse(view)


@router.get("/api/v1/email-threads/{thread_id}")
async def get_email_thread(thread_id: str, request: Request) -> Response:
    view = await thread_view(request.app.state.db, thread_id)
    if view is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "type": "email_thread_not_found",
                    "message": "没有这个邮件会话。",
                }
            },
        )
    return JSONResponse(view)
