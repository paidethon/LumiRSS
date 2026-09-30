"""NEW-367 搜索会话回溯路由。

- POST   /api/v1/search/sessions                       新建研究会话
- GET    /api/v1/search/sessions                       本人会话列表
- GET    /api/v1/search/sessions/{id}                  详情（步骤 + resume）
- POST   /api/v1/search/sessions/{id}/steps            追加一步
- POST   /api/v1/search/sessions/{id}/selections       设置当前步选中结果
- POST   /api/v1/search/sessions/{id}/reopen           重新打开（接续最后一步）
- DELETE /api/v1/search/sessions/{id}                  删除

全部 per-user；他人会话与缺失同 404。
"""

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.new367_sessions import (
    SessionCap,
    SessionNotFound,
    append_step,
    create_session,
    delete_session,
    list_sessions,
    reopen_session,
    session_detail,
    set_step_selections,
)

router = APIRouter()


def _error(status: int, err_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": err_type, "message": message}},
        headers={"Cache-Control": "no-store"},
    )


def _not_found() -> JSONResponse:
    return _error(404, "session_not_found", "会话不存在。")


class SessionBody(BaseModel):
    model_config = {"extra": "forbid"}

    title: str = Field(min_length=1, max_length=120)


class StepBody(BaseModel):
    model_config = {"extra": "forbid"}

    query: str = Field(min_length=1, max_length=200)
    filters: dict[str, object] | None = None


class SelectionBody(BaseModel):
    model_config = {"extra": "forbid"}

    refs: list[str] = Field(max_length=100)
    step: int | None = Field(default=None, ge=0)


@router.post("/api/v1/search/sessions", response_model=None)
async def post_session(payload: SessionBody, request: Request) -> JSONResponse:
    try:
        result = await create_session(
            request.app.state.db, title=payload.title
        )
    except SessionCap as exc:
        return _error(409, "session_cap", str(exc))
    return JSONResponse(result, status_code=201)


@router.get("/api/v1/search/sessions", response_model=None)
async def get_sessions(
    request: Request, limit: int = Query(default=50, ge=1, le=100)
) -> JSONResponse:
    result = await list_sessions(request.app.state.db, limit=limit)
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@router.get("/api/v1/search/sessions/{session_id}", response_model=None)
async def get_session_detail(session_id: str, request: Request) -> JSONResponse:
    try:
        result = await session_detail(request.app.state.db, session_id=session_id)
    except SessionNotFound:
        return _not_found()
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@router.post("/api/v1/search/sessions/{session_id}/steps", response_model=None)
async def post_session_step(
    session_id: str, payload: StepBody, request: Request
) -> JSONResponse:
    try:
        result = await append_step(
            request.app.state.db,
            session_id=session_id,
            query=payload.query,
            filters=payload.filters,
        )
    except SessionNotFound:
        return _not_found()
    except SessionCap as exc:
        return _error(409, "session_step_cap", str(exc))
    return JSONResponse(result, status_code=201)


@router.post("/api/v1/search/sessions/{session_id}/selections", response_model=None)
async def post_session_selections(
    session_id: str, payload: SelectionBody, request: Request
) -> JSONResponse:
    try:
        result = await set_step_selections(
            request.app.state.db,
            session_id=session_id,
            refs=payload.refs,
            step=payload.step,
        )
    except SessionNotFound:
        return _not_found()
    except SessionCap as exc:
        return _error(409, "session_step_invalid", str(exc))
    return JSONResponse(result)


@router.post("/api/v1/search/sessions/{session_id}/reopen", response_model=None)
async def post_reopen_session(session_id: str, request: Request) -> JSONResponse:
    try:
        result = await reopen_session(request.app.state.db, session_id=session_id)
    except SessionNotFound:
        return _not_found()
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@router.delete("/api/v1/search/sessions/{session_id}", response_model=None)
async def delete_one_session(session_id: str, request: Request) -> JSONResponse:
    if not await delete_session(request.app.state.db, session_id=session_id):
        return _not_found()
    return JSONResponse(status_code=204)
