"""NEW-233 标注汇总阅读页路由 — GET /api/v1/annotations/summary。

- ?entryRef= 收窄单篇；缺省跨篇（有界 100 篇，超出 truncated=true）。
- 可选 q=（与既有批注检索同一 LIKE 口径）收窄。
- 响应只含标注上下文与回原文定位，绝不含正文（无第二份不可追溯
  正文）。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from lumirss.annotation_store import AnnotationStore
from lumirss.new233_annotation_summary import build_summary

router = APIRouter()


@router.get("/api/v1/annotations/summary")
async def annotations_summary(
    request: Request,
    entryRef: str | None = None,
    q: str | None = None,
) -> Response:
    """本人标注的按文章结构汇总（必要上下文 + 回原段 deep link）。"""
    store = AnnotationStore(request.app.state.db)
    if entryRef is not None:
        annotations = await store.list_for_entry(entryRef)
    else:
        annotations, _ = await store.search(q, None)
    result = await build_summary(request.app.state.db, annotations)
    return JSONResponse(result)
