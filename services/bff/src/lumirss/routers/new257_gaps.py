"""NEW-257 资料缺口任务路由 — 缺口登记 / 显式关闭（必须挂材料）/ 重开。

- /projects/{id}/gaps（GET/POST）
- /gaps/{id}/close（POST：itemRef 必填）、/gaps/{id}/reopen（POST）
- /gaps/{id}（DELETE）

已关闭再 close → 422（诚实拒绝，不做幂等假成功）。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from lumirss.new251_research import ProjectNotFound, ResearchInvalid
from lumirss.new257_gaps import GapNotFound, GapStore

router = APIRouter()


class GapCreate(BaseModel):
    model_config = {"extra": "forbid"}

    description: str
    materialType: str | None = None


class GapClose(BaseModel):
    model_config = {"extra": "forbid"}

    itemRef: str
    note: str | None = None


class GapReopen(BaseModel):
    model_config = {"extra": "forbid"}

    reason: str | None = None


def _store(request: Request) -> GapStore:
    return GapStore(request.app.state.db)


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


@router.get("/api/v1/research/projects/{project_id}/gaps")
async def list_gaps(project_id: str, request: Request) -> Response:
    try:
        return JSONResponse(await _store(request).list(project_id))
    except ProjectNotFound:
        return _error(404, "research_project_not_found", "研究项目不存在。")


@router.post("/api/v1/research/projects/{project_id}/gaps", status_code=201)
async def create_gap(project_id: str, payload: GapCreate, request: Request) -> Response:
    try:
        gap = await _store(request).create(
            project_id, description=payload.description, material_type=payload.materialType
        )
    except ProjectNotFound:
        return _error(404, "research_project_not_found", "研究项目不存在。")
    except ResearchInvalid as exc:
        return _error(422, "invalid_research_payload", str(exc))
    return JSONResponse(status_code=201, content=gap)


@router.post("/api/v1/research/gaps/{gap_id}/close")
async def close_gap(gap_id: str, payload: GapClose, request: Request) -> Response:
    try:
        return JSONResponse(
            await _store(request).close(gap_id, item_ref=payload.itemRef, note=payload.note)
        )
    except GapNotFound:
        return _error(404, "research_gap_not_found", "资料缺口不存在。")
    except ResearchInvalid as exc:
        return _error(422, "invalid_research_payload", str(exc))


@router.post("/api/v1/research/gaps/{gap_id}/reopen")
async def reopen_gap(gap_id: str, payload: GapReopen, request: Request) -> Response:
    try:
        return JSONResponse(await _store(request).reopen(gap_id, reason=payload.reason))
    except GapNotFound:
        return _error(404, "research_gap_not_found", "资料缺口不存在。")
    except ResearchInvalid as exc:
        return _error(422, "invalid_research_payload", str(exc))


@router.delete("/api/v1/research/gaps/{gap_id}", status_code=204)
async def delete_gap(gap_id: str, request: Request) -> Response:
    try:
        await _store(request).delete(gap_id)
    except GapNotFound:
        return _error(404, "research_gap_not_found", "资料缺口不存在。")
    return Response(status_code=204)
