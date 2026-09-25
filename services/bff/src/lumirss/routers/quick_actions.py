"""N199 自定义多步快捷操作路由 — 具名 2-3 步 SAFE 动作序列的 CRUD。

定义存储在 BFF（per-user）；执行永远在 Web 端逐步调用各动作的
NORMAL 端点（每步都过它原本的鉴权/确认路径，无服务端旁路——本
路由绝不代执行任何动作）。步骤词表/形状校验见 quick_actions.py。
"""

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.quick_actions import (
    MAX_NAME,
    MAX_STEPS,
    MIN_STEPS,
    QuickActionInvalid,
    QuickActionStore,
)

router = APIRouter()


class QuickActionStep(BaseModel):
    """一步：白名单动作 + 允许键的 params（形状校验在 store 层）。"""

    model_config = {"extra": "forbid"}

    action: str = Field(min_length=1, max_length=40)
    params: dict[str, object] = Field(default_factory=dict)


class QuickActionCreate(BaseModel):
    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1, max_length=MAX_NAME)
    steps: list[QuickActionStep] = Field(min_length=MIN_STEPS, max_length=MAX_STEPS)


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


@router.post("/api/v1/quick-actions", status_code=201)
async def create_quick_action(payload: QuickActionCreate, request: Request) -> Response:
    store = QuickActionStore(request.app.state.db)
    try:
        action = await store.create(
            name=payload.name,
            steps=[step.model_dump() for step in payload.steps],
        )
    except QuickActionInvalid as exc:
        return _error(422, "invalid_quick_action", str(exc))
    return JSONResponse(status_code=201, content=action)


@router.get("/api/v1/quick-actions")
async def list_quick_actions(request: Request) -> JSONResponse:
    store = QuickActionStore(request.app.state.db)
    return JSONResponse({"items": await store.list_actions()})


@router.delete("/api/v1/quick-actions/{action_id}", status_code=204)
async def delete_quick_action(action_id: str, request: Request) -> Response:
    store = QuickActionStore(request.app.state.db)
    deleted = await store.delete(action_id)
    if not deleted:
        return _error(404, "quick_action_not_found", "快捷操作不存在。")
    return Response(status_code=204)
