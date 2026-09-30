"""NEW-392 通知聚合规则路由。

- POST   /api/v1/notifications/aggregation-rules          创建规则
- GET    /api/v1/notifications/aggregation-rules          规则清单
- POST   /api/v1/notifications/aggregation-rules/{id}/enabled  启用/停用
- DELETE /api/v1/notifications/aggregation-rules/{id}     删除（回到平铺）
- GET    /api/v1/notifications/grouped                    聚合摘要（可展开原始事件）
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.new392_aggregation import (
    RuleConflict,
    RuleNotFound,
    create_rule,
    delete_rule,
    grouped_view,
    list_rules,
    set_rule_enabled,
)
from lumirss.user_scope import require_user_id

router = APIRouter()

_NO_STORE = {"Cache-Control": "no-store"}


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
        headers=_NO_STORE,
    )


def _user() -> str:
    return require_user_id()


class RuleBody(BaseModel):
    model_config = {"extra": "forbid"}

    kind: str = Field(min_length=1, max_length=40)
    source: str = Field(min_length=1, max_length=120)
    label: str | None = Field(default=None, max_length=120)


class EnabledBody(BaseModel):
    model_config = {"extra": "forbid"}

    enabled: bool


@router.post("/api/v1/notifications/aggregation-rules", response_model=None)
async def post_rule(payload: RuleBody, request: Request) -> JSONResponse:
    try:
        user_id = _user()
    except Exception:  # noqa: BLE001
        return _error(401, "session_required", "请先登录。")
    try:
        result = await create_rule(
            request.app.state.control_db,
            user_id,
            kind=payload.kind,
            source=payload.source,
            label=payload.label or "",
        )
    except RuleConflict:
        return _error(409, "rule_conflict", "同一来源同类型已有规则。")
    except Exception as exc:  # noqa: BLE001 — NotificationInvalid → 422
        return _error(422, "invalid_rule", str(exc))
    return JSONResponse(result, status_code=201, headers=_NO_STORE)


@router.get("/api/v1/notifications/aggregation-rules", response_model=None)
async def get_rules(request: Request) -> JSONResponse:
    try:
        user_id = _user()
    except Exception:  # noqa: BLE001
        return _error(401, "session_required", "请先登录。")
    return JSONResponse(
        await list_rules(request.app.state.control_db, user_id), headers=_NO_STORE
    )


@router.post(
    "/api/v1/notifications/aggregation-rules/{rule_id}/enabled", response_model=None
)
async def post_rule_enabled(
    rule_id: str, payload: EnabledBody, request: Request
) -> JSONResponse:
    try:
        user_id = _user()
    except Exception:  # noqa: BLE001
        return _error(401, "session_required", "请先登录。")
    try:
        result = await set_rule_enabled(
            request.app.state.control_db, user_id, rule_id, enabled=payload.enabled
        )
    except RuleNotFound:
        return _error(404, "rule_not_found", "没有这条规则。")
    if result is None:
        return _error(404, "rule_not_found", "没有这条规则。")
    return JSONResponse(result, headers=_NO_STORE)


@router.delete(
    "/api/v1/notifications/aggregation-rules/{rule_id}", response_model=None
)
async def delete_rule_route(rule_id: str, request: Request) -> JSONResponse:
    try:
        user_id = _user()
    except Exception:  # noqa: BLE001
        return _error(401, "session_required", "请先登录。")
    try:
        removed = await delete_rule(request.app.state.control_db, user_id, rule_id)
    except RuleNotFound:
        return _error(404, "rule_not_found", "没有这条规则。")
    if not removed:
        return _error(404, "rule_not_found", "没有这条规则。")
    return JSONResponse({"deleted": True}, headers=_NO_STORE)


@router.get("/api/v1/notifications/grouped", response_model=None)
async def get_grouped(request: Request) -> JSONResponse:
    try:
        user_id = _user()
    except Exception:  # noqa: BLE001
        return _error(401, "session_required", "请先登录。")
    return JSONResponse(
        await grouped_view(request.app.state.control_db, user_id), headers=_NO_STORE
    )
