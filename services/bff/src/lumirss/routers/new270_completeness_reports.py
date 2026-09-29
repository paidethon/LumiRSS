"""NEW-270 翻译完整性报告路由 — 逐段完成/缺失/无法翻译台账 + 显式补译。

- POST /api/v1/entries/{ref}/translation/completeness/report  body {blocks}
      只读分类 + 保存快照（translated/failed/missing/skipped 段索引清单）。
- POST /api/v1/entries/{ref}/translation/completeness/fill    body {blocks}
      显式补译：只发 missing+failed 段（已有结果零 provider 调用），
      返回补译后的新快照（filled = 本次补成功段数）。
- GET  /api/v1/entries/{ref}/translation/completeness/reports  快照历史。

空块集合 → 422。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.ai_translation_segments import SegmentInput
from lumirss.deps import _get_segment_service
from lumirss.entryref import decode_entry_ref
from lumirss.new270_completeness_reports import (
    CompletenessInvalid,
    build_report,
    fill_missing,
    list_reports,
)

router = APIRouter()


class CompletenessBlockIn(BaseModel):
    index: int = Field(ge=0, le=63)
    text: str = Field(min_length=1, max_length=20000)


class CompletenessBody(BaseModel):
    model_config = {"extra": "forbid"}

    blocks: list[CompletenessBlockIn] = Field(min_length=1, max_length=64)


def _invalid(exc: CompletenessInvalid) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": {"type": "completeness_invalid", "message": str(exc)}},
    )


def _blocks(payload: CompletenessBody):
    return [
        SegmentInput(index=b.index, text=b.text) for b in payload.blocks
    ]


def _service(request: Request):
    return _get_segment_service(request)


@router.post(
    "/api/v1/entries/{entry_ref}/translation/completeness/report",
    response_model=None,
)
async def post_completeness_report(
    entry_ref: str, payload: CompletenessBody, request: Request
) -> dict[str, object] | JSONResponse:
    """按原文段落分类当前完整性并保存快照（只读预检 + 台账）。"""
    decode_entry_ref(entry_ref)
    service = _service(request)
    try:
        counts = await build_report(
            request.app.state.db, service, entry_ref, _blocks(payload)
        )
    except CompletenessInvalid as exc:
        return _invalid(exc)
    return await _save(request, entry_ref, counts, 0)


async def _save(request: Request, entry_ref: str, counts, filled: int):
    from lumirss.new270_completeness_reports import save_report

    return await save_report(request.app.state.db, entry_ref, counts, filled)


@router.post(
    "/api/v1/entries/{entry_ref}/translation/completeness/fill",
    response_model=None,
)
async def post_completeness_fill(
    entry_ref: str, payload: CompletenessBody, request: Request
) -> dict[str, object] | JSONResponse:
    """显式补译缺失/失败段；translated/revised/skipped 段零 provider 调用。"""
    decode_entry_ref(entry_ref)
    service = _service(request)
    try:
        return await fill_missing(
            request.app.state.db, service, entry_ref, _blocks(payload)
        )
    except CompletenessInvalid as exc:
        return _invalid(exc)


@router.get("/api/v1/entries/{entry_ref}/translation/completeness/reports")
async def get_completeness_reports(
    entry_ref: str, request: Request, limit: int = 20
) -> dict[str, object]:
    """快照历史（新→旧）—— 回看「哪里缺、补了多少」。"""
    decode_entry_ref(entry_ref)
    items = await list_reports(request.app.state.db, entry_ref, limit)
    return {"reports": items}
