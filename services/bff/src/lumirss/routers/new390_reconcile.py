"""NEW-390 迁移结果逐项对账路由 — 创建 / 明细 / 逐条确认 / 台账。

- POST /api/v1/preservation/reconciliations   {expectedItemIds, results,
  source?} → 对账单（missing 自动判定）
- GET  /api/v1/preservation/reconciliations            台账
- GET  /api/v1/preservation/reconciliations/{id}       明细
- POST /api/v1/preservation/reconciliations/{id}/confirm
  {externalIds} → 逐条确认（无一键全收；pending → 0 即完成）
"""

from typing import Any

from fastapi import APIRouter, Request

from lumirss.new390_reconcile import (
    ReconcileInvalid,
    ReconcileNotFound,
    confirm_items,
    create_reconciliation,
    get_reconciliation,
    list_reconciliations,
)
from lumirss.routers.preservation_gate import (
    error_response,
    no_store,
    require_preservation_user,
)

router = APIRouter()


@router.post("/api/v1/preservation/reconciliations", status_code=201)
async def create_reconciliation_route(payload: dict[str, Any], request: Request) -> Any:
    guard = await require_preservation_user(request)
    if guard is not None:
        return guard
    raw_expected = payload.get("expectedItemIds")
    expected = [str(ref) for ref in raw_expected] if isinstance(raw_expected, list) else []
    raw_results = payload.get("results")
    results = [dict(item) for item in raw_results if isinstance(item, dict)] if isinstance(
        raw_results, list
    ) else []
    try:
        return no_store(
            await create_reconciliation(
                request.app.state.db,
                expected,
                results,
                source=str(payload.get("source") or "manual"),
            ),
            201,
        )
    except ReconcileInvalid as exc:
        return error_response(400, "invalid_reconciliation", str(exc))


@router.get("/api/v1/preservation/reconciliations")
async def list_reconciliations_route(request: Request) -> Any:
    guard = await require_preservation_user(request)
    if guard is not None:
        return guard
    return no_store({"reconciliations": await list_reconciliations(request.app.state.db)})


@router.get("/api/v1/preservation/reconciliations/{reconciliation_id}")
async def get_reconciliation_route(reconciliation_id: str, request: Request) -> Any:
    guard = await require_preservation_user(request)
    if guard is not None:
        return guard
    found = await get_reconciliation(request.app.state.db, reconciliation_id)
    if found is None:
        return error_response(404, "reconciliation_not_found", "对账单不存在。")
    return no_store(found)


@router.post("/api/v1/preservation/reconciliations/{reconciliation_id}/confirm")
async def confirm_reconciliation_route(
    reconciliation_id: str, payload: dict[str, Any], request: Request
) -> Any:
    guard = await require_preservation_user(request)
    if guard is not None:
        return guard
    raw_ids = payload.get("externalIds")
    ids = [str(ref) for ref in raw_ids] if isinstance(raw_ids, list) else []
    try:
        return no_store(
            await confirm_items(request.app.state.db, reconciliation_id, ids)
        )
    except ReconcileNotFound:
        return error_response(404, "reconciliation_not_found", "对账单不存在。")
