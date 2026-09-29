"""NEW-232 失效标注重定位路由 — 手动重锚 + 旧位置历史。

- POST /api/v1/annotations/{id}/re-anchor        {anchor, excerpt?}
- GET  /api/v1/annotations/{id}/re-anchor-history 旧引文/旧位置台账
  （append-only，永不覆盖）。

404 未知批注；422 锚点非法；409 新锚点与他条冲突。无网络依赖。
"""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.annotation_store import MAX_EXCERPT
from lumirss.new232_annotation_reanchor import (
    AnchorReanchorConflict,
    AnchorReanchorInvalid,
    AnnotationReanchorStore,
)

router = APIRouter()


class ReanchorRequest(BaseModel):
    """POST /api/v1/annotations/{id}/re-anchor body。"""

    model_config = {"extra": "forbid"}

    anchor: dict[str, object]
    excerpt: str | None = Field(default=None, max_length=MAX_EXCERPT)


def _store(request: Request) -> AnnotationReanchorStore:
    return AnnotationReanchorStore(request.app.state.db)


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


@router.post("/api/v1/annotations/{annotation_id}/re-anchor")
async def reanchor_annotation(
    annotation_id: str, payload: ReanchorRequest, request: Request
) -> Response:
    """用户手动把批注重锚到新段落；旧锚点/旧引文先进历史台账。"""
    try:
        item = await _store(request).reanchor(
            annotation_id, anchor=payload.anchor, excerpt=payload.excerpt
        )
    except AnchorReanchorInvalid as exc:
        return _error(422, "invalid_reanchor", str(exc))
    except AnchorReanchorConflict as exc:
        return _error(409, "anchor_conflict", str(exc))
    if item is None:
        return _error(404, "annotation_not_found", "批注不存在。")
    return JSONResponse(item)


@router.get("/api/v1/annotations/{annotation_id}/re-anchor-history")
async def reanchor_history(annotation_id: str, request: Request) -> Response:
    """重锚历史（旧引文与旧位置永久保留）。批注本体不存在 → 404；
    存在但从未重锚 → 空 items（诚实空，不是错误）。"""
    store = _store(request)
    from lumirss.annotation_store import AnnotationStore

    current = await AnnotationStore(request.app.state.db).get(annotation_id)
    if current is None:
        return _error(404, "annotation_not_found", "批注不存在。")
    items: list[dict[str, Any]] = await store.history(annotation_id)
    return JSONResponse({"annotationId": annotation_id, "items": items})
