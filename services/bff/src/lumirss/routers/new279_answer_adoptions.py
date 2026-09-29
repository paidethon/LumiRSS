"""NEW-279 问答结论采纳路由 — 采纳 / 改写 / 删除 / 台账。

- POST   /api/v1/ai/answer-adoptions
      {conclusion, citations?, model?, entryRef?, noteUuid? | newTitle?}
- PATCH  /api/v1/ai/answer-adoptions/{id} {conclusion}
      → 笔记被直接编辑过 → 409 note_diverged（附现状，绝不静默覆盖）
- DELETE /api/v1/ai/answer-adoptions/{id} → 204（笔记内容不动）
- GET    /api/v1/ai/answer-adoptions      → 台账
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.new279_answer_adoptions import (
    AdoptionInvalid,
    AdoptionNotFound,
    AnswerAdoptionStore,
    NoteDiverged,
)

router = APIRouter()


class AdoptionCitation(BaseModel):
    index: int = Field(ge=0, le=9999, default=0)
    entryRef: str = Field(default="", max_length=200)


class AdoptionCreateBody(BaseModel):
    model_config = {"extra": "forbid"}

    conclusion: str = Field(min_length=1, max_length=6000)
    citations: list[AdoptionCitation] = Field(default_factory=list, max_length=20)
    model: str = Field(default="", max_length=120)
    entryRef: str | None = Field(default=None, max_length=200)
    noteUuid: str | None = Field(default=None, max_length=64)
    newTitle: str | None = Field(default=None, max_length=200)


class AdoptionReviseBody(BaseModel):
    model_config = {"extra": "forbid"}

    conclusion: str = Field(min_length=1, max_length=6000)


def _store(request: Request) -> AnswerAdoptionStore:
    return AnswerAdoptionStore(request.app.state.db)


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


@router.post("/api/v1/ai/answer-adoptions")
async def create_adoption(
    payload: AdoptionCreateBody, request: Request
) -> Response:
    try:
        adoption = await _store(request).adopt(
            conclusion=payload.conclusion,
            citations=[c.model_dump() for c in payload.citations],
            model=payload.model,
            entry_ref=payload.entryRef,
            note_uuid=payload.noteUuid,
            new_title=payload.newTitle,
        )
    except AdoptionInvalid as exc:
        return _error(422, "invalid_adoption_request", str(exc))
    return JSONResponse(adoption, status_code=201)


@router.patch("/api/v1/ai/answer-adoptions/{adoption_id}")
async def revise_adoption(
    adoption_id: str, payload: AdoptionReviseBody, request: Request
) -> Response:
    try:
        adoption = await _store(request).revise(
            adoption_id, conclusion=payload.conclusion
        )
    except AdoptionNotFound:
        return _error(404, "adoption_not_found", "采纳记录不存在。")
    except AdoptionInvalid as exc:
        return _error(422, "invalid_adoption_request", str(exc))
    except NoteDiverged as exc:
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "type": "note_diverged",
                    "message": (
                        "笔记已被直接修改；采纳改写未应用。"
                        "请基于现状重试（笔记内容随响应给出）。"
                    ),
                    "noteUuid": exc.note_uuid,
                    "noteUpdatedAt": exc.note_updated_at,
                    "noteContentMd": exc.content_md,
                }
            },
        )
    return JSONResponse(adoption)


@router.delete("/api/v1/ai/answer-adoptions/{adoption_id}", status_code=204)
async def delete_adoption(adoption_id: str, request: Request) -> Response:
    deleted = await _store(request).delete_adoption(adoption_id)
    if not deleted:
        return _error(404, "adoption_not_found", "采纳记录不存在。")
    return Response(status_code=204)


@router.get("/api/v1/ai/answer-adoptions")
async def list_adoptions(request: Request) -> Response:
    adoptions = await _store(request).list_adoptions()
    return JSONResponse({"items": adoptions, "total": len(adoptions)})
