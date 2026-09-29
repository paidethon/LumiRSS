"""NEW-277 模型配置用途约束路由 — 约束 CRUD + 用途可选模型。

- PUT    /api/v1/settings/ai/profiles/{profile_id}/purpose-constraints {allowedPurposes}
- GET    /api/v1/settings/ai/profiles/{profile_id}/purpose-constraints
- DELETE /api/v1/settings/ai/profiles/{profile_id}/purpose-constraints
- GET    /api/v1/ai/purpose-options?purpose=chat → 已配置模型 × 约束的可选面
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from lumirss.new277_purpose_constraints import (
    ConstraintInvalid,
    PurposeConstraintStore,
)

router = APIRouter()


class ConstraintBody(BaseModel):
    model_config = {"extra": "forbid"}

    allowedPurposes: list[str]


def _stores(request: Request) -> tuple[PurposeConstraintStore, object]:
    from lumirss.deps import _get_ai_profile_store

    return (
        PurposeConstraintStore(request.app.state.db),
        _get_ai_profile_store(request),
    )


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


@router.put("/api/v1/settings/ai/profiles/{profile_id}/purpose-constraints")
async def put_purpose_constraint(
    profile_id: str, payload: ConstraintBody, request: Request
) -> Response:
    store, profiles = _stores(request)
    try:
        result = await store.set_constraint(
            profiles, profile_id, payload.allowedPurposes
        )
    except ConstraintInvalid as exc:
        return _error(422, "invalid_purpose_constraint", str(exc))
    except Exception as exc:  # noqa: BLE001 — profile 不存在走 404 族
        from lumirss.ai_profiles import AiProfileNotFound

        if isinstance(exc, AiProfileNotFound):
            return _error(404, "ai_profile_not_found", "AI 配置档不存在。")
        raise
    return JSONResponse(result)


@router.get("/api/v1/settings/ai/profiles/{profile_id}/purpose-constraints")
async def get_purpose_constraint(profile_id: str, request: Request) -> Response:
    store, _profiles = _stores(request)
    constraint = await store.get_constraint(profile_id)
    if constraint is None:
        return _error(404, "constraint_not_found", "该配置档没有用途约束。")
    return JSONResponse(constraint)


@router.delete("/api/v1/settings/ai/profiles/{profile_id}/purpose-constraints", status_code=204)
async def delete_purpose_constraint(profile_id: str, request: Request) -> Response:
    store, _profiles = _stores(request)
    try:
        deleted = await store.delete_constraint(profile_id)
    except ConstraintInvalid as exc:
        return _error(422, "invalid_purpose_constraint", str(exc))
    if not deleted:
        return _error(404, "constraint_not_found", "该配置档没有用途约束。")
    return Response(status_code=204)


@router.get("/api/v1/ai/purpose-options")
async def get_purpose_options(purpose: str, request: Request) -> Response:
    store, profiles = _stores(request)
    try:
        options = await store.purpose_options(profiles, purpose)
    except ConstraintInvalid as exc:
        return _error(422, "invalid_purpose_constraint", str(exc))
    return JSONResponse(options)
