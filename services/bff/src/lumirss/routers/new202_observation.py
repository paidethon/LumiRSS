"""NEW-202 订阅停更观察路由（观察期 + 到期复核事实面）。"""

from typing import Any, Literal

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.new202_observation import (
    ObservationExists,
    ObservationNotFound,
    ObservationStore,
    build_facts,
)
from lumirss.util import utc_now

router = APIRouter()


def _store(request: Request) -> ObservationStore:
    return ObservationStore(request.app.state.db)


def _invalid(message: str) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": {"type": "invalid_observation", "message": message}},
    )


def _not_found() -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={
            "error": {"type": "observation_not_found", "message": "观察不存在。"}
        },
    )


class ObservationCreate(BaseModel):
    """POST /api/v1/new202/observations body。"""

    model_config = {"extra": "forbid"}

    feedUrl: str = Field(min_length=1)
    days: int = Field(ge=7, le=180)
    """观察期天数（到期复核日 = today + days）。"""
    note: str | None = Field(default=None, max_length=200)


class ObservationExtend(BaseModel):
    """POST /api/v1/new202/observations/{id}/extend body。"""

    model_config = {"extra": "forbid"}

    days: int = Field(ge=7, le=180)


class ObservationClose(BaseModel):
    """POST /api/v1/new202/observations/{id}/close body。"""

    model_config = {"extra": "forbid"}

    resolution: Literal["continue", "unsubscribed"]
    """continue = 保留订阅、结束本期；unsubscribed = 用户决定停订
    （实际退订走既有退订端点，本端点只记录决定）。"""


class ObservationView(BaseModel):
    id: str
    feedUrl: str
    note: str | None
    startedAt: str
    endsAt: str
    status: str
    resolution: str | None
    closedAt: str | None
    createdAt: str
    # 事实面（读取时聚合）
    lastPostAt: str | None = None
    postsSinceStart: int = 0
    projectionRows: int = 0
    fetchHealth: str | None = None
    verdict: str | None = None
    fetchPaused: bool = False
    expired: bool = False
    basis: str | None = None
    noteFromServer: str | None = None


class ObservationList(BaseModel):
    items: list[ObservationView]
    serverTime: str


async def _view(request: Request, observation: dict[str, Any]) -> ObservationView:
    facts = await build_facts(request.app.state.db, observation)
    merged = {**observation, **facts}
    merged["noteFromServer"] = facts.pop("note")
    return ObservationView(**merged)


@router.post(
    "/api/v1/new202/observations", response_model=ObservationView, status_code=201
)
async def create_observation(payload: ObservationCreate, request: Request) -> Any:
    """为来源设置停更观察期（同一来源同时至多一条 active → 409）。"""
    try:
        observation = await _store(request).create(
            feed_url=payload.feedUrl, days=payload.days, note=payload.note
        )
    except ObservationExists:
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "type": "observation_exists",
                    "message": "该来源已有一条进行中的观察。",
                }
            },
        )
    return await _view(request, observation)


@router.get("/api/v1/new202/observations", response_model=ObservationList)
async def list_observations(
    request: Request, status: str = Query(default="active", pattern="^(active|closed|all)$")
) -> ObservationList:
    """观察列表（默认 active；带事实面与 expired 标注）。"""
    items = await _store(request).list_observations(status=status)
    views = [await _view(request, item) for item in items]
    return ObservationList(items=views, serverTime=utc_now())


@router.post(
    "/api/v1/new202/observations/{observation_id}/extend",
    response_model=ObservationView,
)
async def extend_observation(
    observation_id: str, payload: ObservationExtend, request: Request
) -> Any:
    """继续观察：到期日 = max(now, endsAt) + days。"""
    try:
        observation = await _store(request).extend(observation_id, payload.days)
    except ObservationNotFound:
        return _not_found()
    return await _view(request, observation)


@router.post(
    "/api/v1/new202/observations/{observation_id}/close", response_model=ObservationView
)
async def close_observation(
    observation_id: str, payload: ObservationClose, request: Request
) -> Any:
    """到期复核收尾：continue（保留订阅）或 unsubscribed（决定停订；
    实际退订走既有退订端点，本端点只记录决定）。"""
    if payload.resolution not in ("continue", "unsubscribed"):
        return _invalid("resolution 必须是 continue 或 unsubscribed。")
    try:
        observation = await _store(request).close(observation_id, payload.resolution)
    except ObservationNotFound:
        return _not_found()
    except ObservationExists:
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "type": "observation_already_closed",
                    "message": "该观察已收尾，请刷新后重试。",
                }
            },
        )
    return await _view(request, observation)
