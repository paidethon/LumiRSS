"""NEW-298 邮件重复识别复核路由 — 冲突队列 + 用户选择保留版本。

- GET  /api/v1/email-duplicates        → 冲突队列（pending 带来件预览）
- POST /api/v1/email-duplicates/{id}/resolve {choice} → 复核决定
（导入路径在 routers/new291：skipped/conflicts 如实随导入结果返回）
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from lumirss.new298_email_duplicates import (
    DuplicateConflictNotFound,
    DuplicateResolveError,
    list_conflicts,
    resolve_conflict,
)

router = APIRouter()


class ResolveBody(BaseModel):
    model_config = {"extra": "forbid"}

    choice: str


@router.get("/api/v1/email-duplicates")
async def get_email_duplicates(request: Request) -> Response:
    return JSONResponse(await list_conflicts(request.app.state.db))


@router.post("/api/v1/email-duplicates/{conflict_id}/resolve")
async def post_duplicate_resolve(
    conflict_id: str, payload: ResolveBody, request: Request
) -> Response:
    try:
        result = await resolve_conflict(
            request.app.state.db, conflict_id, payload.choice
        )
    except DuplicateConflictNotFound as exc:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "conflict_not_found", "message": str(exc)}},
        )
    except DuplicateResolveError as exc:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "conflict_choice_invalid", "message": str(exc)}},
        )
    return JSONResponse(result)
