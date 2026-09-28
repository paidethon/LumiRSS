"""NEW-220 个人收件箱处理记录路由 —— 台账写入 / 按日期追踪 / 删除。

POST /api/v1/triage-journal（记一次整理：从哪里移到哪里 + 原因）、
GET /api/v1/triage-journal?date=YYYY-MM-DD&location=包含词（按日分组）、
DELETE /api/v1/triage-journal/{id}。
422 invalid_triage_journal / 404 triage_journal_not_found。
"""

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.new220_triage_journal import (
    TriageJournalInvalid,
    TriageJournalStore,
)

router = APIRouter()


class TriageJournalCreate(BaseModel):
    model_config = {"extra": "forbid"}

    fromLocation: str = Field(min_length=1, max_length=60)
    toLocation: str = Field(min_length=1, max_length=60)
    refs: list[str] = Field(min_length=1, max_length=200)
    reason: str = ""


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


def _store(request: Request) -> TriageJournalStore:
    return TriageJournalStore(request.app.state.db)


@router.post("/api/v1/triage-journal", status_code=201)
async def create_triage_entry(payload: TriageJournalCreate, request: Request) -> Response:
    try:
        result = await _store(request).create(
            from_location=payload.fromLocation,
            to_location=payload.toLocation,
            refs=payload.refs,
            reason=payload.reason,
        )
    except TriageJournalInvalid as exc:
        return _error(422, "invalid_triage_journal", str(exc))
    return JSONResponse(status_code=201, content=result)


@router.get("/api/v1/triage-journal")
async def list_triage_entries(
    request: Request, date: str | None = None, location: str | None = None
) -> Response:
    try:
        result = await _store(request).list_entries(date=date, location=location)
    except TriageJournalInvalid as exc:
        return _error(422, "invalid_triage_journal", str(exc))
    return JSONResponse(result)


@router.delete("/api/v1/triage-journal/{entry_id}", status_code=204)
async def delete_triage_entry(entry_id: str, request: Request) -> Response:
    deleted = await _store(request).delete(entry_id)
    if not deleted:
        return _error(404, "triage_journal_not_found", "记录不存在。")
    return Response(status_code=204)
