"""NEW-218 资料引用关系检查路由 —— 检查 / 重关联 / 保留（解除）失效标记。

POST /api/v1/references/check（候选有界、诚实截断标志）、
POST /api/v1/references/relink（新目标必须可解析；目标占用 → 409）、
POST /api/v1/references/keep-stale、DELETE /api/v1/references/keep-stale/{id}。
422 invalid_reference_check / 409 reference_check_conflict。
"""

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.deps import _get_source_registry
from lumirss.new218_reference_check import (
    ReferenceCheckConflict,
    ReferenceCheckInvalid,
    ReferenceCheckStore,
    check_references,
)

router = APIRouter()


class ReferenceCheckRequest(BaseModel):
    model_config = {"extra": "forbid"}

    surfaces: list[str] = Field(
        default_factory=lambda: ["workspaces", "relations", "notes"],
        min_length=1,
        max_length=3,
    )


class ReferenceRelinkRequest(BaseModel):
    model_config = {"extra": "forbid"}

    surface: str = Field(min_length=1, max_length=20)
    locator: str = Field(min_length=1, max_length=100)
    oldRef: str = Field(min_length=1, max_length=200)
    newRef: str = Field(min_length=1, max_length=200)


class ReferenceKeepStaleRequest(BaseModel):
    model_config = {"extra": "forbid"}

    surface: str = Field(min_length=1, max_length=20)
    locator: str = Field(min_length=1, max_length=100)
    ref: str = Field(min_length=1, max_length=200)


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


def _store(request: Request) -> ReferenceCheckStore:
    return ReferenceCheckStore(request.app.state.db)


@router.post("/api/v1/references/check")
async def references_check(payload: ReferenceCheckRequest, request: Request) -> Response:
    surfaces = [s for s in payload.surfaces if s in ("workspaces", "relations", "notes")]
    if not surfaces:
        return _error(422, "invalid_reference_check", "检查面词表为空或不合法。")
    try:
        result = await check_references(
            request.app.state.db, _get_source_registry(request), surfaces
        )
    except ReferenceCheckInvalid as exc:
        return _error(422, "invalid_reference_check", str(exc))
    return JSONResponse(result)


@router.post("/api/v1/references/relink")
async def references_relink(payload: ReferenceRelinkRequest, request: Request) -> Response:
    """重关联前先确认新目标真实存在（ensure_resolvable → 422）。"""
    from lumirss.new218_reference_check import ReferenceCheckInvalid as _Invalid
    from lumirss.sources import ItemRefUnresolvable, ensure_resolvable

    try:
        await ensure_resolvable(_get_source_registry(request), payload.newRef)
    except ItemRefUnresolvable as exc:
        _ = exc
        return _error(422, "invalid_reference_check", "新目标不可解析，拒绝重关联。")
    except ValueError as exc:
        _ = exc
        return _error(422, "invalid_reference_check", "新目标引用形状非法。")
    try:
        await _store(request).relink(payload.surface, payload.locator, payload.oldRef, payload.newRef)
    except _Invalid as exc:
        return _error(422, "invalid_reference_check", str(exc))
    except ReferenceCheckConflict as exc:
        return _error(409, "reference_check_conflict", str(exc))
    return JSONResponse({"relinked": True})


@router.post("/api/v1/references/keep-stale")
async def references_keep_stale(payload: ReferenceKeepStaleRequest, request: Request) -> Response:
    try:
        result = await _store(request).keep_stale(payload.surface, payload.locator, payload.ref)
    except ReferenceCheckInvalid as exc:
        return _error(422, "invalid_reference_check", str(exc))
    return JSONResponse(result)


@router.delete("/api/v1/references/keep-stale/{keep_id}", status_code=204)
async def references_unkeep_stale(keep_id: int, request: Request) -> Response:
    removed = await _store(request).unkeep_stale(keep_id)
    if not removed:
        return _error(404, "reference_keep_not_found", "保留标记不存在。")
    return Response(status_code=204)
