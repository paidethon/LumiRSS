"""NEW-259 结论变更记录路由 — 当前结论 + 变更台账（只追加）。

- /api/v1/research/projects/{id}/conclusion（GET 当前 / PUT 登记新结论）
- /api/v1/research/projects/{id}/conclusion/history（GET 台账）

诚实边界：登记新结论永远先写台账（首次登记 old_text=null），
旧结论不覆盖、可回看；本路由无任何删除/改写台账的路径。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from lumirss.new251_research import ProjectNotFound, ResearchInvalid
from lumirss.new259_conclusion_history import ConclusionStore

router = APIRouter()


class ConclusionSet(BaseModel):
    model_config = {"extra": "forbid"}

    text: str
    triggerRefs: list[str] | None = None
    reason: str | None = None


def _store(request: Request) -> ConclusionStore:
    return ConclusionStore(request.app.state.db)


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


def _not_found() -> JSONResponse:
    return _error(404, "research_project_not_found", "研究项目不存在。")


@router.get("/api/v1/research/projects/{project_id}/conclusion")
async def get_conclusion(project_id: str, request: Request) -> Response:
    try:
        return JSONResponse(await _store(request).get(project_id))
    except ProjectNotFound:
        return _not_found()


@router.put("/api/v1/research/projects/{project_id}/conclusion")
async def set_conclusion(project_id: str, payload: ConclusionSet, request: Request) -> Response:
    try:
        result = await _store(request).set_conclusion(
            project_id,
            text=payload.text,
            trigger_refs=payload.triggerRefs,
            reason=payload.reason,
        )
    except ProjectNotFound:
        return _not_found()
    except ResearchInvalid as exc:
        return _error(422, "invalid_research_payload", str(exc))
    return JSONResponse(result)


@router.get("/api/v1/research/projects/{project_id}/conclusion/history")
async def get_history(project_id: str, request: Request) -> Response:
    try:
        return JSONResponse(await _store(request).history(project_id))
    except ProjectNotFound:
        return _not_found()
