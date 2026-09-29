"""NEW-287 简报人工精选标记路由 — 编辑来源翻转 + 规则推荐（确定性）。

- GET   /api/v1/briefings/suggestions?from&to&rule&feedUrl → 推荐摘要卡
          （provenance 恒为 'rule'；规则 = starred/recent/feed，零 AI）
- PATCH /api/v1/briefings/{issue_id}/items/{item_id}/provenance →
          manual ↔ rule 翻转（仅草稿；已确认期次 409——读者已按确认稿
          阅读，编辑来源不得静默改写）。

注意：静态 /suggestions 路径必须先于 new281 的 /{issue_id} 注册。
"""

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from lumirss.new281_briefings import (
    BriefingInvalid,
    BriefingNotFound,
    BriefingStateConflict,
    BriefingStore,
)

router = APIRouter()


class ProvenanceBody(BaseModel):
    model_config = {"extra": "forbid"}

    provenance: str


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


@router.get("/api/v1/briefings/suggestions")
async def get_suggestions(
    request: Request,
    range_from: str = Query("", alias="from"),
    to: str = "",
    rule: str = "recent",
    feedUrl: str = "",
) -> Response:
    try:
        cards = await BriefingStore(request.app.state.db).suggestions(
            range_from,
            to,
            rule=rule,
            feed_url=feedUrl or None,
        )
    except BriefingInvalid as exc:
        return _error(422, "invalid_briefing_payload", str(exc))
    return JSONResponse(
        {"suggestions": cards, "count": len(cards), "rule": rule}
    )


@router.patch("/api/v1/briefings/{issue_id}/items/{item_id}/provenance")
async def patch_provenance(
    issue_id: str, item_id: str, payload: ProvenanceBody, request: Request
) -> Response:
    try:
        issue = await BriefingStore(request.app.state.db).flip_provenance(
            issue_id, item_id, payload.provenance
        )
    except BriefingStateConflict as exc:
        return _error(409, "briefing_confirmed", str(exc))
    except BriefingInvalid as exc:
        return _error(422, "invalid_briefing_payload", str(exc))
    except BriefingNotFound as exc:
        return _error(404, "briefing_not_found", str(exc))
    return JSONResponse(issue)
