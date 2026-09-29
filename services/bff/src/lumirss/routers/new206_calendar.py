"""NEW-206 来源阅读日历路由（per-feed 月历，只读投影）。"""

from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from lumirss.new206_calendar import feed_month_calendar, validate_month

router = APIRouter()


class CalendarDaySample(BaseModel):
    entryRef: str
    title: str
    publishedAt: str


class CalendarDay(BaseModel):
    date: str
    count: int
    sample: list[CalendarDaySample]


class CalendarView(BaseModel):
    feedUrl: str
    month: str
    days: list[CalendarDay]
    totalEntries: int
    coverage: str
    """projection（正常投影口径）| no_projection_data（资料缺失）。"""
    outOfWindowRows: int
    fetchPaused: bool
    basis: str
    note: str


@router.get("/api/v1/new206/calendar", response_model=CalendarView)
async def get_feed_calendar(
    request: Request,
    feedUrl: str = Query(min_length=1),
    month: str = Query(min_length=1),
) -> Any:
    """按真实发表日期的来源月历（只读；无发文与资料缺失严格区分）。"""
    try:
        clean_month = validate_month(month)
    except ValueError as exc:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "invalid_month", "message": str(exc)}},
        )
    return CalendarView(
        **await feed_month_calendar(request.app.state.db, feedUrl, clean_month)
    )
