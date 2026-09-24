"""N074 阅读问题清单路由 — CRUD + 按链接过滤。

- POST 创建（question 必填；entryRef/annotationId/workspaceId 可选链接）；
- GET 列表（status / entryRef / annotationId 可选过滤；status 缺省 =
  open+done 全部，诚实呈现清单全貌）；
- PATCH 改文本或 open↔done（完成 / 重新打开同一路径）；
- DELETE 204。问题与来源解耦：原文删除只影响展示层定位。
"""

from typing import Any

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse

from lumirss.models import (
    ReadingQuestionCreate,
    ReadingQuestionList,
    ReadingQuestionPatch,
)
from lumirss.reading_questions import QuestionInvalid, delete, list_questions, update

router = APIRouter()


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


@router.post("/api/v1/reading-questions", status_code=201)
async def create_reading_question(payload: ReadingQuestionCreate, request: Request) -> Response:
    from lumirss.reading_questions import create

    db = request.app.state.db
    try:
        item = await create(
            db,
            question=payload.question,
            entry_ref=payload.entryRef,
            annotation_id=payload.annotationId,
            workspace_id=payload.workspaceId,
        )
    except QuestionInvalid as exc:
        return _error(422, "invalid_question", str(exc))
    return JSONResponse(status_code=201, content=item)


@router.get("/api/v1/reading-questions", response_model=ReadingQuestionList)
async def list_reading_questions(
    request: Request,
    status: str | None = Query(None),
    entryRef: str | None = Query(None),
    annotationId: str | None = Query(None),
) -> Response:
    db = request.app.state.db
    try:
        items = await list_questions(
            db, status=status, entry_ref=entryRef, annotation_id=annotationId
        )
    except QuestionInvalid as exc:
        return _error(422, "invalid_request", str(exc))
    return JSONResponse(ReadingQuestionList(items=items).model_dump())


@router.patch("/api/v1/reading-questions/{question_id}")
async def patch_reading_question(
    question_id: str, payload: ReadingQuestionPatch, request: Request
) -> Response:
    db: Any = request.app.state.db
    try:
        item = await update(
            db, question_id, question=payload.question, status=payload.status
        )
    except QuestionInvalid as exc:
        return _error(422, "invalid_question", str(exc))
    if item is None:
        return _error(404, "question_not_found", "问题不存在。")
    return JSONResponse(item)


@router.delete("/api/v1/reading-questions/{question_id}", status_code=204)
async def delete_reading_question(question_id: str, request: Request) -> Response:
    deleted = await delete(request.app.state.db, question_id)
    if not deleted:
        return _error(404, "question_not_found", "问题不存在。")
    return Response(status_code=204)
