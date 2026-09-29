"""NEW-255 事件时间线编辑器路由 — 事件发生时间 vs 报道时间。

- /projects/{id}/timeline（GET/POST）、/timeline-events/{id}（PATCH/DELETE）

event_at 按用户掌握的精度原文存储；只有两侧都能解析成日期前缀时才
计算 reportedDaysAfter，解析不了诚实返回 null，绝不猜时间差。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from lumirss.new251_research import ProjectNotFound, ResearchInvalid
from lumirss.new255_timeline import TimelineEventNotFound, TimelineStore

router = APIRouter()


class TimelineEventCreate(BaseModel):
    model_config = {"extra": "forbid"}

    title: str
    eventAt: str
    reportedAt: str | None = None
    itemRef: str | None = None
    note: str | None = None


class TimelineEventPatch(BaseModel):
    model_config = {"extra": "forbid"}

    title: str | None = None
    eventAt: str | None = None
    reportedAt: str | None = None
    itemRef: str | None = None
    note: str | None = None


def _store(request: Request) -> TimelineStore:
    return TimelineStore(request.app.state.db)


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


@router.get("/api/v1/research/projects/{project_id}/timeline")
async def list_events(project_id: str, request: Request) -> Response:
    try:
        return JSONResponse(await _store(request).list(project_id))
    except ProjectNotFound:
        return _error(404, "research_project_not_found", "研究项目不存在。")


@router.post("/api/v1/research/projects/{project_id}/timeline", status_code=201)
async def create_event(project_id: str, payload: TimelineEventCreate, request: Request) -> Response:
    try:
        event = await _store(request).create(
            project_id,
            title=payload.title,
            event_at=payload.eventAt,
            reported_at=payload.reportedAt,
            item_ref=payload.itemRef,
            note=payload.note,
        )
    except ProjectNotFound:
        return _error(404, "research_project_not_found", "研究项目不存在。")
    except ResearchInvalid as exc:
        return _error(422, "invalid_research_payload", str(exc))
    return JSONResponse(status_code=201, content=event)


@router.patch("/api/v1/research/timeline-events/{event_id}")
async def patch_event(event_id: str, payload: TimelineEventPatch, request: Request) -> Response:
    try:
        return JSONResponse(
            await _store(request).update(
                event_id,
                title=payload.title,
                event_at=payload.eventAt,
                reported_at=payload.reportedAt,
                item_ref=payload.itemRef,
                note=payload.note,
            )
        )
    except TimelineEventNotFound:
        return _error(404, "research_timeline_event_not_found", "时间线事件不存在。")
    except ResearchInvalid as exc:
        return _error(422, "invalid_research_payload", str(exc))


@router.delete("/api/v1/research/timeline-events/{event_id}", status_code=204)
async def delete_event(event_id: str, request: Request) -> Response:
    try:
        await _store(request).delete(event_id)
    except TimelineEventNotFound:
        return _error(404, "research_timeline_event_not_found", "时间线事件不存在。")
    return Response(status_code=204)
