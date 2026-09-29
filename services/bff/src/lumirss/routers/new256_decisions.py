"""NEW-256 研究决策记录路由 — 决策登记 / 依据材料 / 只追加 followups。

- /projects/{id}/decisions（GET/POST，创建可带 itemRefs）
- /decisions/{id}/followups（POST，kind=outcome|revision；无 UPDATE/DELETE）
- /decisions/{id}/materials（POST）

决策行登记后不可改写（decision/basis 无 PATCH）——错了就追加 revision。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from lumirss.new251_research import ProjectNotFound, ResearchInvalid
from lumirss.new256_decisions import DecisionNotFound, DecisionStore

router = APIRouter()


class DecisionCreate(BaseModel):
    model_config = {"extra": "forbid"}

    decision: str
    basis: str | None = None
    itemRefs: list[str] | None = None


class FollowupCreate(BaseModel):
    model_config = {"extra": "forbid"}

    kind: str
    text: str


class DecisionMaterialCreate(BaseModel):
    model_config = {"extra": "forbid"}

    itemRef: str


def _store(request: Request) -> DecisionStore:
    return DecisionStore(request.app.state.db)


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


@router.get("/api/v1/research/projects/{project_id}/decisions")
async def list_decisions(project_id: str, request: Request) -> Response:
    try:
        return JSONResponse(await _store(request).list(project_id))
    except ProjectNotFound:
        return _error(404, "research_project_not_found", "研究项目不存在。")


@router.post("/api/v1/research/projects/{project_id}/decisions", status_code=201)
async def create_decision(project_id: str, payload: DecisionCreate, request: Request) -> Response:
    try:
        decision = await _store(request).create(
            project_id, decision=payload.decision, basis=payload.basis, item_refs=payload.itemRefs
        )
    except ProjectNotFound:
        return _error(404, "research_project_not_found", "研究项目不存在。")
    except ResearchInvalid as exc:
        return _error(422, "invalid_research_payload", str(exc))
    return JSONResponse(status_code=201, content=decision)


@router.post("/api/v1/research/decisions/{decision_id}/followups", status_code=201)
async def add_followup(decision_id: str, payload: FollowupCreate, request: Request) -> Response:
    try:
        followup = await _store(request).add_followup(
            decision_id, kind=payload.kind, text=payload.text
        )
    except DecisionNotFound:
        return _error(404, "research_decision_not_found", "决策记录不存在。")
    except ResearchInvalid as exc:
        return _error(422, "invalid_research_payload", str(exc))
    return JSONResponse(status_code=201, content=followup)


@router.post("/api/v1/research/decisions/{decision_id}/materials", status_code=201)
async def add_decision_material(
    decision_id: str, payload: DecisionMaterialCreate, request: Request
) -> Response:
    try:
        result = await _store(request).add_material(decision_id, item_ref=payload.itemRef)
    except DecisionNotFound:
        return _error(404, "research_decision_not_found", "决策记录不存在。")
    except ResearchInvalid as exc:
        return _error(422, "invalid_research_payload", str(exc))
    status = 200 if result["outcome"] == "duplicate" else 201
    return JSONResponse(status_code=status, content=result)
