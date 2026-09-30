"""NEW-398 错误自助处理单路由。

- GET  /api/v1/support/runbooks                        注册表（错误码 → 步骤）
- POST /api/v1/support/runbooks/{code}/sessions        开单
- GET  /api/v1/support/runbooks/sessions               本人处理单清单
- GET  /api/v1/support/runbooks/sessions/{id}          明细（含逐步结果与材料）
- POST /api/v1/support/runbooks/sessions/{id}/steps    记录一步效果（覆盖式）
- POST /api/v1/support/runbooks/sessions/{id}/resolve  已解决
- POST /api/v1/support/runbooks/sessions/{id}/escalate 升级并生成脱敏求助材料
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.new398_runbooks import (
    RunbookUnknown,
    SessionNotFound,
    StepInvalid,
    escalate_session,
    get_session,
    list_runbooks,
    list_sessions,
    open_session,
    record_step,
    resolve_session,
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


class StepBody(BaseModel):
    model_config = {"extra": "forbid"}

    stepIndex: int
    outcome: str = Field(min_length=1, max_length=16)
    note: str | None = Field(default=None, max_length=500)


class EscalateBody(BaseModel):
    model_config = {"extra": "forbid"}

    note: str = Field(min_length=1, max_length=500)


@router.get("/api/v1/support/runbooks", response_model=None)
async def get_runbooks(request: Request) -> JSONResponse:
    try:
        _user()
    except Exception:  # noqa: BLE001
        return _error(401, "session_required", "请先登录。")
    return JSONResponse(list_runbooks(), headers=_NO_STORE)


@router.post("/api/v1/support/runbooks/{code}/sessions", response_model=None)
async def post_session(code: str, request: Request) -> JSONResponse:
    try:
        user_id = _user()
    except Exception:  # noqa: BLE001
        return _error(401, "session_required", "请先登录。")
    try:
        result = await open_session(request.app.state.control_db, user_id, code=code)
    except RunbookUnknown:
        return _error(404, "runbook_not_found", "该错误码没有处理单。")
    return JSONResponse(result, status_code=201, headers=_NO_STORE)


@router.get("/api/v1/support/runbooks/sessions", response_model=None)
async def get_sessions(request: Request) -> JSONResponse:
    try:
        user_id = _user()
    except Exception:  # noqa: BLE001
        return _error(401, "session_required", "请先登录。")
    return JSONResponse(
        await list_sessions(request.app.state.control_db, user_id), headers=_NO_STORE
    )


@router.get("/api/v1/support/runbooks/sessions/{session_id}", response_model=None)
async def get_session_route(session_id: str, request: Request) -> JSONResponse:
    try:
        user_id = _user()
    except Exception:  # noqa: BLE001
        return _error(401, "session_required", "请先登录。")
    try:
        return JSONResponse(
            await get_session(request.app.state.control_db, user_id, session_id),
            headers=_NO_STORE,
        )
    except SessionNotFound:
        return _error(404, "session_not_found", "没有这张处理单。")


@router.post("/api/v1/support/runbooks/sessions/{session_id}/steps", response_model=None)
async def post_step(
    session_id: str, payload: StepBody, request: Request
) -> JSONResponse:
    try:
        user_id = _user()
    except Exception:  # noqa: BLE001
        return _error(401, "session_required", "请先登录。")
    try:
        result = await record_step(
            request.app.state.control_db,
            user_id,
            session_id=session_id,
            step_index=payload.stepIndex,
            outcome=payload.outcome,
            note=payload.note or "",
        )
    except SessionNotFound:
        return _error(404, "session_not_found", "没有这张处理单。")
    except StepInvalid as exc:
        return _error(422, "invalid_step", str(exc))
    return JSONResponse(result, headers=_NO_STORE)


@router.post("/api/v1/support/runbooks/sessions/{session_id}/resolve", response_model=None)
async def post_resolve(session_id: str, request: Request) -> JSONResponse:
    try:
        user_id = _user()
    except Exception:  # noqa: BLE001
        return _error(401, "session_required", "请先登录。")
    try:
        return JSONResponse(
            await resolve_session(request.app.state.control_db, user_id, session_id),
            headers=_NO_STORE,
        )
    except SessionNotFound:
        return _error(404, "session_not_found", "没有这张处理单。")


@router.post("/api/v1/support/runbooks/sessions/{session_id}/escalate", response_model=None)
async def post_escalate(
    session_id: str, payload: EscalateBody, request: Request
) -> JSONResponse:
    try:
        user_id = _user()
    except Exception:  # noqa: BLE001
        return _error(401, "session_required", "请先登录。")
    try:
        return JSONResponse(
            await escalate_session(
                request.app.state.control_db, user_id, session_id, note=payload.note
            ),
            headers=_NO_STORE,
        )
    except SessionNotFound:
        return _error(404, "session_not_found", "没有这张处理单。")
    except Exception as exc:  # noqa: BLE001 — StepInvalid（空备注）→ 422
        return _error(422, "invalid_escalation", str(exc))
