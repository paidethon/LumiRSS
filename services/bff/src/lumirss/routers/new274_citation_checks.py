"""NEW-274 AI 结果引用核验路由 — 逐条定位 / 台账 / 显式确认已核对。

- POST /api/v1/ai/citation-checks {answerText, citations:[{index,entryRef,claim}]}
- GET  /api/v1/ai/citation-checks                → 台账
- GET  /api/v1/ai/citation-checks/{id}           → 单次核验（逐条定位结果）
- POST /api/v1/ai/citation-checks/{id}/mark-checked {confirmMissing?}
      → 存在未定位引用且未确认 → 422 citation_confirmation_required
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.new274_citation_checks import (
    CitationCheckNotFound,
    CitationCheckStore,
    CitationConfirmationRequired,
    CitationInvalid,
)

router = APIRouter()


class CitationBody(BaseModel):
    index: int = Field(ge=0, le=9999)
    entryRef: str = Field(min_length=1, max_length=200)
    claim: str = Field(min_length=1, max_length=300)


class CitationCheckBody(BaseModel):
    model_config = {"extra": "forbid"}

    answerText: str = Field(min_length=1, max_length=20000)
    citations: list[CitationBody] = Field(min_length=1, max_length=20)


class MarkCheckedBody(BaseModel):
    model_config = {"extra": "forbid"}

    confirmMissing: bool = False


def _store(request: Request) -> CitationCheckStore:
    from lumirss.deps import _get_adapter

    return CitationCheckStore(request.app.state.db, _get_adapter(request))


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


@router.post("/api/v1/ai/citation-checks")
async def run_citation_check(
    payload: CitationCheckBody, request: Request
) -> Response:
    try:
        check = await _store(request).run_check(
            payload.answerText,
            [item.model_dump() for item in payload.citations],
        )
    except CitationInvalid as exc:
        return _error(422, "invalid_citation_request", str(exc))
    return JSONResponse(check, status_code=201)


@router.get("/api/v1/ai/citation-checks")
async def list_citation_checks(request: Request) -> Response:
    checks = await _store(request).list_checks()
    return JSONResponse({"items": checks, "total": len(checks)})


@router.get("/api/v1/ai/citation-checks/{check_id}")
async def get_citation_check(check_id: str, request: Request) -> Response:
    try:
        check = await _store(request).get_check(check_id)
    except CitationCheckNotFound:
        return _error(404, "citation_check_not_found", "核验记录不存在。")
    return JSONResponse(check)


@router.post("/api/v1/ai/citation-checks/{check_id}/mark-checked")
async def mark_citation_check(
    check_id: str, payload: MarkCheckedBody, request: Request
) -> Response:
    try:
        check = await _store(request).mark_checked(
            check_id, confirm_missing=payload.confirmMissing
        )
    except CitationCheckNotFound:
        return _error(404, "citation_check_not_found", "核验记录不存在。")
    except CitationConfirmationRequired as exc:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "type": "citation_confirmation_required",
                    "message": (
                        f"{exc.missing} 条引用未能定位；确认接受缺失后"
                        "才能标为已核对（confirmMissing=true）。"
                    ),
                    "missingCount": exc.missing,
                }
            },
        )
    return JSONResponse(check)
