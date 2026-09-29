"""NEW-252 假设登记册路由 — 假设 CRUD + 可支持/可反驳两侧材料分配。

- /projects/{id}/hypotheses（GET/POST）、/hypotheses/{id}（PATCH/DELETE）
- /hypotheses/{id}/materials（POST，side=support|refute）
- /hypothesis-materials/{id}（DELETE）

登记必须带 supportCondition 与 refuteCondition（可反驳性是门槛）。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from lumirss.new251_research import ProjectNotFound
from lumirss.new252_hypotheses import (
    HypothesisNotFound,
    HypothesisStore,
    ResearchInvalid,
)

router = APIRouter()


class HypothesisCreate(BaseModel):
    model_config = {"extra": "forbid"}

    statement: str
    supportCondition: str
    refuteCondition: str


class HypothesisPatch(BaseModel):
    model_config = {"extra": "forbid"}

    statement: str | None = None
    supportCondition: str | None = None
    refuteCondition: str | None = None
    status: str | None = None


class HypothesisMaterialCreate(BaseModel):
    model_config = {"extra": "forbid"}

    itemRef: str
    side: str
    note: str | None = None


def _store(request: Request) -> HypothesisStore:
    return HypothesisStore(request.app.state.db)


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


@router.get("/api/v1/research/projects/{project_id}/hypotheses")
async def list_hypotheses(project_id: str, request: Request) -> Response:
    try:
        return JSONResponse(await _store(request).list(project_id))
    except ProjectNotFound:
        return _error(404, "research_project_not_found", "研究项目不存在。")


@router.post("/api/v1/research/projects/{project_id}/hypotheses", status_code=201)
async def create_hypothesis(project_id: str, payload: HypothesisCreate, request: Request) -> Response:
    try:
        hypothesis = await _store(request).create(
            project_id,
            statement=payload.statement,
            support_condition=payload.supportCondition,
            refute_condition=payload.refuteCondition,
        )
    except ProjectNotFound:
        return _error(404, "research_project_not_found", "研究项目不存在。")
    except ResearchInvalid as exc:
        return _error(422, "invalid_research_payload", str(exc))
    return JSONResponse(status_code=201, content=hypothesis)


@router.patch("/api/v1/research/hypotheses/{hypothesis_id}")
async def patch_hypothesis(hypothesis_id: str, payload: HypothesisPatch, request: Request) -> Response:
    try:
        return JSONResponse(
            await _store(request).update(
                hypothesis_id,
                statement=payload.statement,
                support_condition=payload.supportCondition,
                refute_condition=payload.refuteCondition,
                status=payload.status,
            )
        )
    except HypothesisNotFound:
        return _error(404, "research_hypothesis_not_found", "假设不存在。")
    except ResearchInvalid as exc:
        return _error(422, "invalid_research_payload", str(exc))


@router.delete("/api/v1/research/hypotheses/{hypothesis_id}", status_code=204)
async def delete_hypothesis(hypothesis_id: str, request: Request) -> Response:
    try:
        await _store(request).delete(hypothesis_id)
    except HypothesisNotFound:
        return _error(404, "research_hypothesis_not_found", "假设不存在。")
    return Response(status_code=204)


@router.post("/api/v1/research/hypotheses/{hypothesis_id}/materials", status_code=201)
async def add_hypothesis_material(
    hypothesis_id: str, payload: HypothesisMaterialCreate, request: Request
) -> Response:
    try:
        result = await _store(request).add_material(
            hypothesis_id,
            item_ref=payload.itemRef,
            side=payload.side,
            note=payload.note,
        )
    except HypothesisNotFound:
        return _error(404, "research_hypothesis_not_found", "假设不存在。")
    except ResearchInvalid as exc:
        return _error(422, "invalid_research_payload", str(exc))
    status = 200 if result["outcome"] == "duplicate" else 201
    return JSONResponse(status_code=status, content=result)


@router.delete("/api/v1/research/hypothesis-materials/{material_id}", status_code=204)
async def remove_hypothesis_material(material_id: str, request: Request) -> Response:
    try:
        await _store(request).remove_material(material_id)
    except HypothesisNotFound:
        return _error(404, "research_hypothesis_material_not_found", "分配记录不存在。")
    return Response(status_code=204)
