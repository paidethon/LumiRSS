"""NEW-263 译文质量反馈路由 — 段级漏译/误译/格式问题标记与待复核队列。

- POST   /api/v1/entries/{ref}/translation/segments/{index}/feedback
      body {issueKind, note?} → 创建反馈（创建时刻快照 原文/机器译文/
      人工修订 三段文本，关联原文；源文后续更新不移动已建反馈）。
- GET    /api/v1/entries/{ref}/translation/feedback        某篇反馈（新→旧）。
- GET    /api/v1/translation/feedback/queue                本人待复核队列
      （全部 open，跨条目；per-user 库天然隔离）。
- POST   /api/v1/translation/feedback/{id}/resolve         复核完成（显式出队）。
- DELETE /api/v1/translation/feedback/{id}                 删除（显式出队）。

未知段 / 非法问题类型 / 空注释越界 → 422；重复 resolve / 未知 id → 404。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from lumirss.entryref import decode_entry_ref
from lumirss.new263_quality_feedback import (
    FeedbackInvalid,
    FeedbackNotFound,
    create_feedback,
    delete_feedback,
    list_feedback,
    queue,
    resolve_feedback,
)

router = APIRouter()


class FeedbackBody(BaseModel):
    model_config = {"extra": "forbid"}

    issueKind: str = Field(min_length=1, max_length=20)
    note: str = Field(default="", max_length=500)

    @field_validator("note")
    @classmethod
    def note_not_blank_required(cls, value: str) -> str:
        # note 允许为空（问题类型本身已表意）；只拒绝全空白的长文本
        if value.strip() == "" and value != "":
            return ""
        return value


def _invalid(exc: FeedbackInvalid) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": {"type": "feedback_invalid", "message": str(exc)}},
    )


def _not_found(exc: FeedbackNotFound) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"error": {"type": "feedback_not_found", "message": str(exc)}},
    )


def _invalid_index(block_index: int) -> JSONResponse | None:
    if not 0 <= block_index <= 63:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "type": "invalid_segment_index",
                    "message": "block_index 必须在 0..63 之间。",
                }
            },
        )
    return None


@router.post(
    "/api/v1/entries/{entry_ref}/translation/segments/{block_index}/feedback",
    response_model=None,
)
async def post_segment_feedback(
    entry_ref: str, block_index: int, payload: FeedbackBody, request: Request
) -> dict[str, object] | JSONResponse:
    """对具体段落标记质量问题（快照三段文本，进入本人待复核队列）。"""
    decode_entry_ref(entry_ref)
    invalid = _invalid_index(block_index)
    if invalid is not None:
        return invalid
    try:
        return await create_feedback(
            request.app.state.db,
            entry_ref,
            block_index,
            payload.issueKind,
            payload.note,
        )
    except FeedbackInvalid as exc:
        return _invalid(exc)


@router.get("/api/v1/entries/{entry_ref}/translation/feedback")
async def get_entry_feedback(entry_ref: str, request: Request) -> dict[str, object]:
    """某篇的反馈清单（新→旧）。"""
    decode_entry_ref(entry_ref)
    items = await list_feedback(request.app.state.db, entry_ref)
    return {"feedback": items}


@router.get("/api/v1/translation/feedback/queue")
async def get_feedback_queue(
    request: Request, limit: int = 100
) -> dict[str, object]:
    """本人待复核队列（open，跨条目，新→旧）。"""
    items = await queue(request.app.state.db, limit)
    return {"queue": items}


@router.post("/api/v1/translation/feedback/{feedback_id}/resolve", response_model=None)
async def post_feedback_resolve(
    feedback_id: str, request: Request
) -> dict[str, object] | JSONResponse:
    """复核完成 → resolved（显式出队）。未知 / 已解决 → 404。"""
    try:
        return await resolve_feedback(request.app.state.db, feedback_id)
    except FeedbackNotFound as exc:
        return _not_found(exc)


@router.delete("/api/v1/translation/feedback/{feedback_id}", response_model=None)
async def delete_segment_feedback(
    feedback_id: str, request: Request
) -> JSONResponse:
    """删除一条反馈（显式出队）。未知 → 404。"""
    removed = await delete_feedback(request.app.state.db, feedback_id)
    if not removed:
        return _not_found(FeedbackNotFound("反馈不存在。"))
    return JSONResponse(status_code=200, content={"removed": True})
