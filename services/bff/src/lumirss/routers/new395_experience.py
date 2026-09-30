"""NEW-395 版本功能体验清单路由。

- GET  /api/v1/whats-new/experience                    实际上线清单 + 本人标记
- POST /api/v1/whats-new/experience/{featureId}/mark   了解 / 暂不使用
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.new395_experience import (
    ExperienceInvalid,
    FeatureUnknown,
    experience_list,
    mark_feature,
)
from lumirss.user_scope import principal_of, require_user_id

router = APIRouter()

_NO_STORE = {"Cache-Control": "no-store"}


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
        headers=_NO_STORE,
    )


class MarkBody(BaseModel):
    model_config = {"extra": "forbid"}

    status: str = Field(min_length=1, max_length=16)


@router.get("/api/v1/whats-new/experience", response_model=None)
async def get_experience(request: Request) -> JSONResponse:
    try:
        user_id = require_user_id()
    except Exception:  # noqa: BLE001
        return _error(401, "session_required", "请先登录。")
    principal = principal_of(request.scope)
    role = str(principal.get("role")) if principal else None
    return JSONResponse(
        await experience_list(
            request.app.state.control_db, user_id, role=role
        ),
        headers=_NO_STORE,
    )


@router.post("/api/v1/whats-new/experience/{feature_id}/mark", response_model=None)
async def post_mark(feature_id: str, payload: MarkBody, request: Request) -> JSONResponse:
    try:
        user_id = require_user_id()
    except Exception:  # noqa: BLE001
        return _error(401, "session_required", "请先登录。")
    principal = principal_of(request.scope)
    role = str(principal.get("role")) if principal else None
    try:
        result = await mark_feature(
            request.app.state.control_db,
            user_id,
            feature_id=feature_id,
            status=payload.status,
            role=role,
        )
    except FeatureUnknown:
        return _error(404, "feature_not_found", "该功能不在当前发布清单里。")
    except ExperienceInvalid as exc:
        return _error(422, "invalid_mark", str(exc))
    return JSONResponse(result, headers=_NO_STORE)
