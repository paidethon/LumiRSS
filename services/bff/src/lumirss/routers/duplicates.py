"""F071 疑似重复审核路由 — 扫描 / 队列 / 三动作。

- POST /api/v1/library/duplicates/scan：全量扫描（幂等；从不自动删除
  或合并任何条目——只产「疑似」对）；
- GET /api/v1/library/duplicates?status=pending：审核队列；
- POST .../{id}/confirm：置 confirmed 并创建 item_relations
  kind='duplicate' 关联（幂等：RelationDuplicate/已存在不报错）；
- POST .../{id}/ignore | whitelist：置对应状态（whitelisted 后该对
  永不重现）。
"""

import contextlib
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

from lumirss import duplicate_pairs

router = APIRouter()


@router.post("/api/v1/library/duplicates/scan")
async def scan_duplicates(request: Request) -> dict[str, Any]:
    return await duplicate_pairs.scan(request.app.state.db)


@router.get("/api/v1/library/duplicates")
async def list_duplicates(
    request: Request, status: str | None = Query(default="pending")
) -> dict[str, Any]:
    return {"items": await duplicate_pairs.list_pairs(request.app.state.db, status)}


@router.post("/api/v1/library/duplicates/{pair_id}/confirm")
async def confirm_duplicate(pair_id: str, request: Request) -> Any:
    pair = await duplicate_pairs.get_pair(request.app.state.db, pair_id)
    if pair is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "duplicate_pair_not_found", "message": "疑似重复对不存在。"}},
        )
    # 创建 duplicate 关联（幂等：已存在同向关系不报错）
    from lumirss.item_relations import ItemRelationStore, RelationDuplicate

    # 已存在反向/异注关联：仍完成状态确认
    with contextlib.suppress(RelationDuplicate):
        await ItemRelationStore(request.app.state.db).create(
            pair["aRef"], pair["bRef"], "疑似重复（确认）", kind="duplicate"
        )
    updated = await duplicate_pairs.set_status(request.app.state.db, pair_id, "confirmed")
    return updated


@router.post("/api/v1/library/duplicates/{pair_id}/ignore")
async def ignore_duplicate(pair_id: str, request: Request) -> Any:
    updated = await duplicate_pairs.set_status(request.app.state.db, pair_id, "ignored")
    if updated is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "duplicate_pair_not_found", "message": "疑似重复对不存在。"}},
        )
    return updated


@router.post("/api/v1/library/duplicates/{pair_id}/whitelist")
async def whitelist_duplicate(pair_id: str, request: Request) -> Any:
    updated = await duplicate_pairs.set_status(request.app.state.db, pair_id, "whitelisted")
    if updated is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "duplicate_pair_not_found", "message": "疑似重复对不存在。"}},
        )
    return updated
