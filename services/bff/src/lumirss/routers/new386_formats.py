"""NEW-386 保存格式对照预览路由 — 对照 / 明细 / 台账。

- POST /api/v1/preservation/format-compare   {itemIds} → 三格式逐字段
  损失对照（kept / changed / lost / na）
- GET  /api/v1/preservation/format-compare/{id}   对照明细
- GET  /api/v1/preservation/format-compare        台账
"""

from typing import Any

from fastapi import APIRouter, Request

from lumirss.new386_format_compare import (
    CompareInvalid,
    compare_items,
    get_comparison,
    list_comparisons,
    persist_comparison,
)
from lumirss.routers.preservation_gate import (
    error_response,
    no_store,
    require_preservation_user,
)

router = APIRouter()


@router.post("/api/v1/preservation/format-compare")
async def create_format_compare(payload: dict[str, Any], request: Request) -> Any:
    guard = await require_preservation_user(request)
    if guard is not None:
        return guard
    raw = payload.get("itemIds")
    ids = [str(ref) for ref in raw] if isinstance(raw, list) else []
    try:
        result = await compare_items(request.app.state.db, ids)
    except CompareInvalid as exc:
        return error_response(400, "invalid_compare_request", str(exc))
    comparison_id = await persist_comparison(
        request.app.state.db, result, ids
    )
    return no_store({**result, "comparisonId": comparison_id})


@router.get("/api/v1/preservation/format-compare/{comparison_id}")
async def get_format_compare(comparison_id: str, request: Request) -> Any:
    guard = await require_preservation_user(request)
    if guard is not None:
        return guard
    found = await get_comparison(request.app.state.db, comparison_id)
    if found is None:
        return error_response(404, "comparison_not_found", "对照记录不存在。")
    return no_store(found)


@router.get("/api/v1/preservation/format-compare")
async def list_format_compares(request: Request) -> Any:
    guard = await require_preservation_user(request)
    if guard is not None:
        return guard
    return no_store({"comparisons": await list_comparisons(request.app.state.db)})
