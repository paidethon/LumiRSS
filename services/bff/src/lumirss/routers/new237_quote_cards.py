"""NEW-237 引用卡片路由 — 预览 / 导出（同一构建，导出加下载头）。

- POST /api/v1/annotation-cards/preview {annotationIds, includeNotes, title?}
  → JSON 预览（markdown 文本 + 来源索引）；不落盘不下载。
- POST /api/v1/annotation-cards/export  同体 → text/markdown 附件。

未知批注 id honest skipped（unknownIds 回显）；0 条可引用 → 422。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.annotation_store import AnnotationStore
from lumirss.new237_quote_cards import (
    MAX_CARD_ITEMS,
    QuoteCardInvalid,
    build_quote_card,
    dedupe,
)

router = APIRouter()


class QuoteCardRequest(BaseModel):
    model_config = {"extra": "forbid"}

    annotationIds: list[str] = Field(min_length=1)
    includeNotes: bool = True
    title: str | None = Field(default=None, max_length=200)


async def _resolve_and_build(payload: QuoteCardRequest, request: Request) -> tuple[dict, list[str]]:
    """解析 id → 本人批注（未知 honest skipped），构建卡片。返回
    (卡片, unknownIds)。"""
    store = AnnotationStore(request.app.state.db)
    ordered_ids = dedupe(payload.annotationIds)
    if len(ordered_ids) > MAX_CARD_ITEMS:
        raise QuoteCardInvalid(f"一张卡最多 {MAX_CARD_ITEMS} 条引文。")
    found: list[dict] = []
    unknown: list[str] = []
    for annotation_id in ordered_ids:
        item = await store.get(annotation_id)
        if item is None:
            unknown.append(annotation_id)
            continue
        found.append(item)
    card = await build_quote_card(
        request.app.state.db, found, include_notes=payload.includeNotes, title=payload.title
    )
    return card, unknown


@router.post("/api/v1/annotation-cards/preview")
async def preview_quote_card(payload: QuoteCardRequest, request: Request) -> Response:
    """导出前预览（JSON；含 markdown 全文与来源索引）。"""
    try:
        card, unknown = await _resolve_and_build(payload, request)
    except QuoteCardInvalid as exc:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "invalid_quote_card", "message": str(exc)}},
        )
    return JSONResponse({**card, "unknownIds": unknown})


@router.post("/api/v1/annotation-cards/export")
async def export_quote_card(payload: QuoteCardRequest, request: Request) -> Response:
    """导出文字卡（Markdown 附件）。未知 id 存在 → 422（导出前用户
    已在预览里看到 unknownIds；带未知 id 导出视为误操作，诚实拒绝）。"""
    try:
        card, unknown = await _resolve_and_build(payload, request)
    except QuoteCardInvalid as exc:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "invalid_quote_card", "message": str(exc)}},
        )
    if unknown:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "type": "invalid_quote_card",
                    "message": f"存在无法引用的批注 id：{', '.join(unknown)}。",
                }
            },
        )
    return Response(
        content=card["markdown"],
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="lumi-quote-card.md"'},
    )
