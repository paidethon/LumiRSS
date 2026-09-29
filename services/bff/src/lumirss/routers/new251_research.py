"""NEW-251 研究问题拆分路由 — 研究项目主线 + 父问题/子问题/材料。

- /api/v1/research/projects（GET/POST）、/projects/{id}（GET/PATCH/DELETE）
- /projects/{id}/questions（GET/POST）、/questions/{id}（DELETE）
- /questions/{id}/subquestions（POST）、/subquestions/{id}（PATCH/DELETE）
- /subquestions/{id}/materials（GET/POST）、/question-materials/{id}（DELETE）

结论草稿与 open/resolved 状态都是用户显式输入；无任何自动判定。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from lumirss.new251_research import (
    ProjectNotFound,
    QuestionNotFound,
    ResearchInvalid,
    ResearchProjectStore,
    ResearchQuestionStore,
)

router = APIRouter()


class ProjectCreate(BaseModel):
    model_config = {"extra": "forbid"}

    title: str
    description: str | None = None


class ProjectPatch(BaseModel):
    model_config = {"extra": "forbid"}

    title: str | None = None
    description: str | None = None


class QuestionCreate(BaseModel):
    model_config = {"extra": "forbid"}

    question: str


class SubquestionCreate(BaseModel):
    model_config = {"extra": "forbid"}

    text: str


class SubquestionPatch(BaseModel):
    model_config = {"extra": "forbid"}

    text: str | None = None
    conclusion: str | None = None
    status: str | None = None


class MaterialCreate(BaseModel):
    model_config = {"extra": "forbid"}

    itemRef: str


def _project_store(request: Request) -> ResearchProjectStore:
    return ResearchProjectStore(request.app.state.db)


def _question_store(request: Request) -> ResearchQuestionStore:
    return ResearchQuestionStore(request.app.state.db)


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


def _not_found(kind: str) -> JSONResponse:
    return _error(404, f"research_{kind}_not_found", "研究项目或问题不存在。")


@router.get("/api/v1/research/projects")
async def list_projects(request: Request) -> Response:
    return JSONResponse(await _project_store(request).list())


@router.post("/api/v1/research/projects", status_code=201)
async def create_project(payload: ProjectCreate, request: Request) -> Response:
    try:
        project = await _project_store(request).create(
            title=payload.title, description=payload.description
        )
    except ResearchInvalid as exc:
        return _error(422, "invalid_research_payload", str(exc))
    return JSONResponse(status_code=201, content=project)


@router.get("/api/v1/research/projects/{project_id}")
async def get_project(project_id: str, request: Request) -> Response:
    try:
        return JSONResponse(await _project_store(request).get(project_id))
    except ProjectNotFound:
        return _not_found("project")


@router.patch("/api/v1/research/projects/{project_id}")
async def patch_project(project_id: str, payload: ProjectPatch, request: Request) -> Response:
    try:
        return JSONResponse(
            await _project_store(request).update(
                project_id, title=payload.title, description=payload.description
            )
        )
    except ProjectNotFound:
        return _not_found("project")
    except ResearchInvalid as exc:
        return _error(422, "invalid_research_payload", str(exc))


@router.delete("/api/v1/research/projects/{project_id}", status_code=204)
async def delete_project(project_id: str, request: Request) -> Response:
    try:
        await _project_store(request).delete(project_id)
    except ProjectNotFound:
        return _not_found("project")
    return Response(status_code=204)


@router.get("/api/v1/research/projects/{project_id}/questions")
async def list_questions(project_id: str, request: Request) -> Response:
    try:
        return JSONResponse(await _question_store(request).list_questions(project_id))
    except ProjectNotFound:
        return _not_found("project")


@router.post("/api/v1/research/projects/{project_id}/questions", status_code=201)
async def add_question(project_id: str, payload: QuestionCreate, request: Request) -> Response:
    try:
        question = await _question_store(request).add_question(project_id, question=payload.question)
    except ProjectNotFound:
        return _not_found("project")
    except ResearchInvalid as exc:
        return _error(422, "invalid_research_payload", str(exc))
    return JSONResponse(status_code=201, content=question)


@router.delete("/api/v1/research/questions/{question_id}", status_code=204)
async def delete_question(question_id: str, request: Request) -> Response:
    try:
        await _question_store(request).delete_question(question_id)
    except QuestionNotFound:
        return _not_found("question")
    return Response(status_code=204)


@router.post("/api/v1/research/questions/{question_id}/subquestions", status_code=201)
async def add_subquestion(question_id: str, payload: SubquestionCreate, request: Request) -> Response:
    try:
        sub = await _question_store(request).add_subquestion(question_id, text=payload.text)
    except QuestionNotFound:
        return _not_found("question")
    except ResearchInvalid as exc:
        return _error(422, "invalid_research_payload", str(exc))
    return JSONResponse(status_code=201, content=sub)


@router.patch("/api/v1/research/subquestions/{subquestion_id}")
async def patch_subquestion(
    subquestion_id: str, payload: SubquestionPatch, request: Request
) -> Response:
    try:
        return JSONResponse(
            await _question_store(request).update_subquestion(
                subquestion_id,
                text=payload.text,
                conclusion=payload.conclusion,
                status=payload.status,
            )
        )
    except QuestionNotFound:
        return _not_found("question")
    except ResearchInvalid as exc:
        return _error(422, "invalid_research_payload", str(exc))


@router.delete("/api/v1/research/subquestions/{subquestion_id}", status_code=204)
async def delete_subquestion(subquestion_id: str, request: Request) -> Response:
    try:
        await _question_store(request).delete_subquestion(subquestion_id)
    except QuestionNotFound:
        return _not_found("question")
    return Response(status_code=204)


@router.get("/api/v1/research/subquestions/{subquestion_id}/materials")
async def list_materials(subquestion_id: str, request: Request) -> Response:
    try:
        return JSONResponse(await _question_store(request).list_materials(subquestion_id))
    except QuestionNotFound:
        return _not_found("question")


@router.post("/api/v1/research/subquestions/{subquestion_id}/materials", status_code=201)
async def add_material(subquestion_id: str, payload: MaterialCreate, request: Request) -> Response:
    try:
        result = await _question_store(request).add_material(subquestion_id, item_ref=payload.itemRef)
    except QuestionNotFound:
        return _not_found("question")
    except ResearchInvalid as exc:
        return _error(422, "invalid_research_payload", str(exc))
    status = 200 if result["outcome"] == "duplicate" else 201
    return JSONResponse(status_code=status, content=result)


@router.delete("/api/v1/research/question-materials/{material_id}", status_code=204)
async def remove_material(material_id: str, request: Request) -> Response:
    try:
        await _question_store(request).remove_material(material_id)
    except QuestionNotFound:
        return _not_found("question")
    return Response(status_code=204)
