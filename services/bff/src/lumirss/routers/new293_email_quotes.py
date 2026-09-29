"""NEW-293 邮件引用折叠路由 — 分段视图 + 逐段核对标记。

- GET  /api/v1/email-materials/{id}/quote-segments
      → own/quoted 分段（quoted 段前端默认折叠，逐段展开核对）
- POST /api/v1/email-materials/{id}/quote-reviews {segmentIndex}
      → 标记该引用段已核对（只对真实引用段有效）
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.new293_email_quotes import (
    EmailQuoteStore,
    SegmentNotFound,
    SegmentNotQuoted,
)

router = APIRouter()


class QuoteReviewBody(BaseModel):
    model_config = {"extra": "forbid"}

    segmentIndex: int = Field(ge=0, le=100000)


@router.get("/api/v1/email-materials/{material_id}/quote-segments")
async def get_quote_segments(material_id: str, request: Request) -> Response:
    view = await EmailQuoteStore(request.app.state.db).segments_view(material_id)
    if view is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "type": "email_material_not_found",
                    "message": "没有这条邮件资料条目。",
                }
            },
        )
    return JSONResponse(view)


@router.post("/api/v1/email-materials/{material_id}/quote-reviews")
async def post_quote_review(
    material_id: str, payload: QuoteReviewBody, request: Request
) -> Response:
    store = EmailQuoteStore(request.app.state.db)
    try:
        view = await store.mark_reviewed(material_id, payload.segmentIndex)
    except SegmentNotFound as exc:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "quote_segment_not_found", "message": str(exc)}},
        )
    except SegmentNotQuoted as exc:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "quote_segment_not_quoted", "message": str(exc)}},
        )
    return JSONResponse(view)
