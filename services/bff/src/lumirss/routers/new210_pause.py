"""NEW-210 来源抓取停机计划路由（per-feed 暂停区间，可取消）。"""

from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.new210_pause import (
    PausePlanAlreadyCancelled,
    PausePlanInvalid,
    PausePlanNotFound,
    PausePlanStore,
    validate_plan_input,
)
from lumirss.util import utc_now

router = APIRouter()


def _store(request: Request) -> PausePlanStore:
    return PausePlanStore(request.app.state.db)


def _invalid(message: str) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": {"type": "invalid_pause_plan", "message": message}},
    )


class PausePlanCreate(BaseModel):
    """POST /api/v1/new210/pauses body。"""

    model_config = {"extra": "forbid"}

    feedUrl: str = Field(min_length=1)
    startAt: str | None = None
    """RFC3339 时刻；缺席 = 立即开始。"""
    endAt: str | None = None
    """恢复时间（RFC3339）；与 openEnded 二选一。"""
    openEnded: bool = False
    """true = 开放式暂停（直到显式取消）。"""
    reason: str | None = None


class PausePlanView(BaseModel):
    id: str
    feedUrl: str
    reason: str | None
    startAt: str
    endAt: str | None
    status: str
    cancelledAt: str | None
    createdAt: str
    activeNow: bool = False


class PausePlanList(BaseModel):
    items: list[PausePlanView]
    note: str


class PauseActiveList(BaseModel):
    feedUrls: list[str]
    checkedAt: str
    note: str


_PLAN_NOTE = (
    "诚实边界：FreshRSS 的抓取调度粒度由实例 CRON_MIN 决定，Lumi 无法"
    "逐源暂停上游抓取；停机计划在 Lumi 侧生效（本组表面如实标注暂停中"
    "的来源），逐源调度需在 FreshRSS 原生界面调整。"
)


@router.post("/api/v1/new210/pauses", response_model=PausePlanView, status_code=201)
async def create_pause_plan(payload: PausePlanCreate, request: Request) -> Any:
    """为来源设置停机计划（立即或定时开始；恢复时间 / 开放式二选一）。"""
    try:
        plan = validate_plan_input(
            feed_url=payload.feedUrl,
            reason=payload.reason,
            start_at=payload.startAt,
            end_at=payload.endAt,
            open_ended=payload.openEnded,
        )
    except PausePlanInvalid as exc:
        return _invalid(str(exc))
    created = await _store(request).create(plan)
    from lumirss.new210_pause import is_active

    created["activeNow"] = is_active(created)
    return PausePlanView(**created)


@router.get("/api/v1/new210/pauses", response_model=PausePlanList)
async def list_pause_plans(request: Request) -> PausePlanList:
    """计划列表（新→旧，≤200；含 activeNow 判定）。"""
    plans = await _store(request).list_plans()
    return PausePlanList(items=[PausePlanView(**plan) for plan in plans], note=_PLAN_NOTE)


@router.get("/api/v1/new210/pauses/active", response_model=PauseActiveList)
async def list_active_pauses(request: Request) -> PauseActiveList:
    """当前生效的暂停来源（去重 URL 列表；机器可读消费点）。"""
    urls = await _store(request).paused_feed_urls()
    return PauseActiveList(feedUrls=urls, checkedAt=utc_now(), note=_PLAN_NOTE)


@router.post("/api/v1/new210/pauses/{plan_id}/cancel", response_model=PausePlanView)
async def cancel_pause_plan(plan_id: str, request: Request) -> Any:
    """取消计划（set 语义 active → cancelled；绝不删除行）。"""
    try:
        plan = await _store(request).cancel(plan_id)
    except PausePlanNotFound:
        return JSONResponse(
            status_code=404,
            content={
                "error": {"type": "pause_plan_not_found", "message": "停机计划不存在。"}
            },
        )
    except PausePlanAlreadyCancelled:
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "type": "pause_plan_already_cancelled",
                    "message": "该计划已取消，请刷新后重试。",
                }
            },
        )
    plan["activeNow"] = False
    return PausePlanView(**plan)


@router.delete("/api/v1/new210/pauses/{plan_id}", status_code=204)
async def delete_pause_plan(plan_id: str, request: Request) -> Response:
    """删除一条（任意状态的）计划行（housekeeping；默认路径是取消）。"""
    deleted = await _store(request).delete(plan_id)
    if not deleted:
        return JSONResponse(
            status_code=404,
            content={
                "error": {"type": "pause_plan_not_found", "message": "停机计划不存在。"}
            },
        )
    return Response(status_code=204)
