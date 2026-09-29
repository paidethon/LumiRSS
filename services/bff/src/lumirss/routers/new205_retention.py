"""NEW-205 来源保留策略预演与确认启用路由。"""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.new205_retention import (
    RetentionConfirmRequired,
    retention_dry_run,
    retention_enable,
)
from lumirss.source_overrides import SourceOverrideStore, retention_days_valid

router = APIRouter()


def _invalid_days() -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "type": "invalid_retention_days",
                "message": "days 必须在 7..3650 之间。",
            }
        },
    )


class RetentionDryRunRequest(BaseModel):
    """POST /api/v1/new205/retention/dry-run body（只读）。"""

    model_config = {"extra": "forbid"}

    feedUrl: str = Field(min_length=1)
    days: int


class RetentionEnableRequest(BaseModel):
    """POST /api/v1/new205/retention/enable body（确认语义在服务端强制）。"""

    model_config = {"extra": "forbid"}

    feedUrl: str = Field(min_length=1)
    days: int
    confirmed: bool = False
    """必须显式 true；缺席/false → 422 confirmation_required。"""


@router.post("/api/v1/new205/retention/dry-run")
async def dry_run_retention(payload: RetentionDryRunRequest, request: Request) -> Any:
    """预演：保留多少收藏/标注/书签、回收多少普通缓存（只读零写入）。"""
    if not retention_days_valid(payload.days):
        return _invalid_days()
    return await retention_dry_run(request.app.state.db, payload.feedUrl, days=payload.days)


@router.post("/api/v1/new205/retention/enable")
async def enable_retention(payload: RetentionEnableRequest, request: Request) -> Any:
    """确认启用：策略落库 + 立即裁剪本地投影（starred 恒排除）+ 台账。

    FreshRSS 零调用（投影可再生成；真实删除需在原生界面执行）。"""
    if not retention_days_valid(payload.days):
        return _invalid_days()
    try:
        result = await retention_enable(
            request.app.state.db,
            payload.feedUrl,
            days=payload.days,
            confirmed=payload.confirmed,
            override_store=SourceOverrideStore(request.app.state.db),
        )
    except RetentionConfirmRequired as exc:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "confirmation_required", "message": str(exc)}},
        )
    return result
