"""NEW-253 反例收集视图路由 — 冲突证据收集 / 显式处理 / 出处后补。

- /projects/{id}/counterexamples（GET，?status= 过滤；POST）
- /counterexamples/{id}/resolve（POST：conclusionAdjusted + resolutionNote 必填）
- /counterexamples/{id}/source（POST：itemRef 出处后补）
- /counterexamples/{id}（DELETE）

本模块只记账「反例被处理过、处理时怎么说的」；真正的结论调整走
NEW-259 结论变更记录——绝不代用户改结论。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from lumirss.new251_research import ProjectNotFound, ResearchInvalid
from lumirss.new253_counterexamples import CounterexampleNotFound, CounterexampleStore

router = APIRouter()


class CounterexampleCreate(BaseModel):
    model_config = {"extra": "forbid"}

    excerpt: str
    itemRef: str | None = None
    note: str | None = None


class CounterexampleResolve(BaseModel):
    model_config = {"extra": "forbid"}

    conclusionAdjusted: bool
    resolutionNote: str


class CounterexampleSource(BaseModel):
    model_config = {"extra": "forbid"}

    itemRef: str


def _store(request: Request) -> CounterexampleStore:
    return CounterexampleStore(request.app.state.db)


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


@router.get("/api/v1/research/projects/{project_id}/counterexamples")
async def list_counterexamples(project_id: str, request: Request, status: str | None = None) -> Response:
    try:
        return JSONResponse(await _store(request).list(project_id, status=status))
    except ProjectNotFound:
        return _error(404, "research_project_not_found", "研究项目不存在。")
    except ResearchInvalid as exc:
        return _error(422, "invalid_research_payload", str(exc))


@router.post("/api/v1/research/projects/{project_id}/counterexamples", status_code=201)
async def create_counterexample(
    project_id: str, payload: CounterexampleCreate, request: Request
) -> Response:
    try:
        row = await _store(request).create(
            project_id, excerpt=payload.excerpt, item_ref=payload.itemRef, note=payload.note
        )
    except ProjectNotFound:
        return _error(404, "research_project_not_found", "研究项目不存在。")
    except ResearchInvalid as exc:
        return _error(422, "invalid_research_payload", str(exc))
    return JSONResponse(status_code=201, content=row)


@router.post("/api/v1/research/counterexamples/{counterexample_id}/resolve")
async def resolve_counterexample(
    counterexample_id: str, payload: CounterexampleResolve, request: Request
) -> Response:
    try:
        return JSONResponse(
            await _store(request).resolve(
                counterexample_id,
                conclusion_adjusted=payload.conclusionAdjusted,
                resolution_note=payload.resolutionNote,
            )
        )
    except CounterexampleNotFound:
        return _error(404, "research_counterexample_not_found", "反例不存在。")
    except ResearchInvalid as exc:
        return _error(422, "invalid_research_payload", str(exc))


@router.post("/api/v1/research/counterexamples/{counterexample_id}/source")
async def attach_source(counterexample_id: str, payload: CounterexampleSource, request: Request) -> Response:
    try:
        return JSONResponse(
            await _store(request).attach_source(counterexample_id, item_ref=payload.itemRef)
        )
    except CounterexampleNotFound:
        return _error(404, "research_counterexample_not_found", "反例不存在。")
    except ResearchInvalid as exc:
        return _error(422, "invalid_research_payload", str(exc))


@router.delete("/api/v1/research/counterexamples/{counterexample_id}", status_code=204)
async def delete_counterexample(counterexample_id: str, request: Request) -> Response:
    try:
        await _store(request).delete(counterexample_id)
    except CounterexampleNotFound:
        return _error(404, "research_counterexample_not_found", "反例不存在。")
    return Response(status_code=204)
