"""NEW-268 译文引用导出路由 — 附原文/来源/机器人工标记的引用导出。

- POST /api/v1/entries/{ref}/translation/segments/{index}/quote-export
      body {blockText, format: 'markdown'|'text', confirmed: true}
      → 渲染好的引用 + 台账留档。confirmed=false → 422（不给
      「确认译文」的引用形态）；无成功缓存译文 → 422。
- GET  /api/v1/entries/{ref}/translation/quote-exports  导出台账（新→旧）。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.deps import _get_segment_service
from lumirss.entryref import decode_entry_ref
from lumirss.new268_quote_exports import (
    QuoteNotConfirmed,
    QuoteUnavailable,
    export_quote,
    list_exports,
)

router = APIRouter()


class QuoteExportBody(BaseModel):
    model_config = {"extra": "forbid"}

    blockText: str = Field(min_length=1, max_length=20000)
    format: str = Field(default="markdown", max_length=10)
    confirmed: bool


def _invalid(exc: Exception, type_name: str) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": {"type": type_name, "message": str(exc)}},
    )


@router.post(
    "/api/v1/entries/{entry_ref}/translation/segments/{block_index}/quote-export",
    response_model=None,
)
async def post_quote_export(
    entry_ref: str,
    block_index: int,
    payload: QuoteExportBody,
    request: Request,
) -> dict[str, object] | JSONResponse:
    """显式确认并导出一段译文（附原文/来源/机器人工标记）。"""
    decode_entry_ref(entry_ref)
    if not 0 <= block_index <= 63:
        return _invalid(
            Exception("block_index 必须在 0..63 之间。"), "invalid_segment_index"
        )
    service = _get_segment_service(request)
    try:
        return await export_quote(
            request.app.state.db,
            service,
            entry_ref,
            block_index,
            payload.blockText,
            payload.format,
            payload.confirmed,
        )
    except QuoteNotConfirmed as exc:
        return _invalid(exc, "quote_not_confirmed")
    except QuoteUnavailable as exc:
        return _invalid(exc, "quote_unavailable")


@router.get("/api/v1/entries/{entry_ref}/translation/quote-exports")
async def get_quote_exports(
    entry_ref: str, request: Request, limit: int = 20
) -> dict[str, object]:
    """某篇的导出台账（新→旧；不含渲染文本，回看用字段视图）。"""
    decode_entry_ref(entry_ref)
    items = await list_exports(request.app.state.db, entry_ref, limit)
    return {"exports": items}
