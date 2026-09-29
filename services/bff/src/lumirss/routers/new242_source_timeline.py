"""NEW-242 来源时间轴路由 — 四类时间 + 出处说明 + 个人备注。

- GET /api/v1/entries/{entry_ref}/source-timeline
      发表 / 接收 / 更新 / 个人保存 + 每项 source 字段（时间从哪来）；
- GET /api/v1/entries/{entry_ref}/source-timeline/annotations     备注列表；
- PUT /api/v1/entries/{entry_ref}/source-timeline/annotations/{kind}
      写（或改写）某类时间的备注（kind ∈ published/received/updated/saved）。

时间轴本体是派生读（search_entries / entry_revisions / library_bookmarks
查询时聚合）；备注负载非法 → 422 timeline_invalid。per-user 库天然隔离。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.new242_source_timeline import SourceTimelineStore, TimelineInvalid

router = APIRouter()


class TimelineAnnotationPut(BaseModel):
    model_config = {"extra": "forbid"}

    note: str = Field(min_length=1, max_length=500)


def _store(request: Request) -> SourceTimelineStore:
    return SourceTimelineStore(request.app.state.db)


def _invalid(message: str) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": {"type": "timeline_invalid", "message": message}},
    )


@router.get("/api/v1/entries/{entry_ref}/source-timeline")
async def get_source_timeline(entry_ref: str, request: Request) -> Response:
    """四类时间 + 每项出处说明（缺失项 available=false 并说明原因）。"""
    return JSONResponse(await _store(request).build_timeline(entry_ref))


@router.get("/api/v1/entries/{entry_ref}/source-timeline/annotations")
async def list_timeline_annotations(entry_ref: str, request: Request) -> Response:
    return JSONResponse({"items": await _store(request).list_annotations(entry_ref)})


@router.put("/api/v1/entries/{entry_ref}/source-timeline/annotations/{kind}")
async def put_timeline_annotation(
    entry_ref: str, kind: str, payload: TimelineAnnotationPut, request: Request
) -> Response:
    try:
        item = await _store(request).put_annotation(entry_ref, kind, payload.note)
    except TimelineInvalid as exc:
        return _invalid(str(exc))
    return JSONResponse(item)
