"""NEW-271 AI 任务输入预览路由 — 摘要/问答发送前的输入构成预览。

- POST /api/v1/entries/{entry_ref}/ai-input-preview
      {purpose: summary|conversation, maxChars?, note?, question?}
      → 分段构成（与真实发送共用组装；绝不调用 provider，零费用）。
      NEW-278 的隐私排除清单在此生效（所见即所发）。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.ai_conversation import MAX_QUESTION_CHARS
from lumirss.entryref import decode_entry_ref
from lumirss.new271_input_preview import (
    build_conversation_preview,
    build_summary_preview,
)
from lumirss.new278_privacy_filters import PrivacyFilterStore

router = APIRouter()

_MAX_PREVIEW_NOTE = 2000
_MAX_PREVIEW_CHARS = 50000


class InputPreviewBody(BaseModel):
    model_config = {"extra": "forbid"}

    purpose: str
    maxChars: int | None = Field(default=None, ge=512, le=_MAX_PREVIEW_CHARS)
    note: str | None = Field(default=None, max_length=_MAX_PREVIEW_NOTE)
    question: str | None = Field(default=None, max_length=MAX_QUESTION_CHARS)


@router.post("/api/v1/entries/{entry_ref}/ai-input-preview")
async def preview_ai_input(
    entry_ref: str, payload: InputPreviewBody, request: Request
) -> Response:
    """展示将发送的输入构成（预览零费用；发送路径见既有摘要/问答端点）。

    非法 purpose → 422 invalid_preview_purpose；文章不存在/无正文 →
    既有稳定错误族（400/404/422），与真实发送一致。"""
    decode_entry_ref(entry_ref)
    if payload.purpose not in ("summary", "conversation"):
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "type": "invalid_preview_purpose",
                    "message": "purpose 必须是 summary 或 conversation。",
                }
            },
        )
    from lumirss.deps import _get_conversation_service, _get_summary_service

    if payload.purpose == "summary":
        service = _get_summary_service(request)
        # 与发送路径同一解析（公开同一 _resolve；文章变化 → 预览如实变化）。
        normalized, _identity = await service._resolve(entry_ref)
        preview = build_summary_preview(
            content=normalized, max_chars=payload.maxChars
        )
        return JSONResponse(preview.to_json())

    exclusions = await PrivacyFilterStore(request.app.state.db).exclusion_set()
    service = _get_conversation_service(request)
    inputs = await service.preview_inputs(
        entry_ref,
        question=payload.question or "",
        max_chars=payload.maxChars,
        note=payload.note,
        exclude=exclusions,
    )
    return JSONResponse(build_conversation_preview(inputs).to_json())
