"""N041 今日必读队列 + N042 分段 + N043 冻结快照 + N044 完成过滤 路由。

- 生成是**修订式幂等**：当天队列已存在时 POST /queue/today/generate
  返回现有队列（200, generated=false）——后台刷新绝不重排已确认的
  队列；?force=1 才重建（done 状态保留，绝不复活）；
- done / 移除 / 重排 / 分段都是显式 set 语义；「只看未完成」过滤只
  活在读取侧（N044）——本路由没有任何路径因过滤删记录；
- 冻结快照不可变：POST freeze 之后没有任何端点能改写既有快照；
  打开视图原样返回成员顺序，消失的 ref 由 Web 诚实呈现占位。
- 稳定错误走 errors.py 信封表（invalid_queue / queue_item_not_found /
  queue_item_done / queue_snapshot_not_found / queue_snapshot_limit）。
"""

from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from lumirss.deps import _get_workspace_store
from lumirss.reading_queue import (
    QueueSnapshotNotFound,
    ReadingQueueStore,
)
from lumirss.workspaces import WorkspaceNotFound

router = APIRouter()


def _store(request: Request) -> ReadingQueueStore:
    return ReadingQueueStore(request.app.state.db)


# ---- 请求/响应模型（OpenAPI 契约真源） ----


class QueueGenerateRequest(BaseModel):
    """POST /api/v1/queue/today/generate body。"""

    model_config = {"extra": "forbid"}

    timeBudgetMinutes: int | None = Field(default=None, ge=5, le=480)
    """预算上限（分钟）；缺省 30。候选装填依据（服务端粗估）。"""
    levels: list[str] = Field(default_factory=list, max_length=20)
    """预留：N020 关注级别在本仓库尚未实现——当前被忽略（响应 notes
    诚实标注），绝不伪装成已生效的过滤。"""
    workspaceId: str | None = None
    """提供时候选限定为该工作区成员。"""


class QueueItemView(BaseModel):
    """队列成员（呈现数据 best-effort：无投影 → title/estimate 为 null）。"""

    id: str
    itemRef: str
    addedAt: str
    position: int
    queueDate: str
    source: Literal["manual", "budget", "level"]
    status: Literal["pending", "done", "removed"]
    segment: str | None
    title: str | None = None
    estimateMinutes: int | None = None


class QueueSegmentView(BaseModel):
    """派生分段（name=null = 未分组，恒为隐式前置组）。"""

    name: str | None
    items: list[QueueItemView]


class QueueTodayResponse(BaseModel):
    """GET /api/v1/queue/today 与 generate/order/segments 的统一视图。"""

    queueDate: str
    items: list[QueueItemView]
    segments: list[QueueSegmentView]
    segmentOrder: list[str]
    totalEstimateMinutes: int


class QueueGenerateResponse(QueueTodayResponse):
    """generate 响应 = 今日视图 + 生成元数据（幂等/诚实标注）。"""

    generated: bool
    force: bool
    basis: str
    budgetMinutes: int | None = None
    notes: list[str] = Field(default_factory=list)


class QueueAddRequest(BaseModel):
    """POST /api/v1/queue/today/items body。"""

    model_config = {"extra": "forbid"}

    itemRef: str
    segment: str | None = None


class QueueItemDoneRequest(BaseModel):
    """POST /api/v1/queue/today/items/{id}/done body（set 语义）。"""

    model_config = {"extra": "forbid"}

    done: bool


class QueueReorderRequest(BaseModel):
    """PUT /api/v1/queue/today/order body：给定的 id 按序列排前，
    未提及行保持相对顺序垫后（语义同工作区 reorder）。"""

    model_config = {"extra": "forbid"}

    order: list[str] = Field(max_length=200)


class QueueSegmentMoveRequest(BaseModel):
    """PATCH /api/v1/queue/today/items/{id}/segment body。"""

    model_config = {"extra": "forbid"}

    segment: str | None = None


class QueueSegmentOrderRequest(BaseModel):
    """PUT /api/v1/queue/today/segments body：段名有序数组（呈现提示）。"""

    model_config = {"extra": "forbid"}

    order: list[str] = Field(default_factory=list, max_length=50)


class QueueFreezeRequest(BaseModel):
    """POST /api/v1/queue/today/freeze body。"""

    model_config = {"extra": "forbid"}

    label: str = Field(min_length=1, max_length=100)


class QueueSnapshotView(BaseModel):
    """冻结快照元数据（payload 留在服务端）。"""

    id: str
    label: str
    queueDate: str
    createdAt: str
    itemCount: int


class QueueSnapshotList(BaseModel):
    items: list[QueueSnapshotView]


class QueueSnapshotItem(BaseModel):
    """冻结成员（ItemRef + 顺序元数据；内容解析在读取侧）。"""

    itemRef: str
    position: int
    segment: str | None


class QueueSnapshotDetail(BaseModel):
    """打开冻结视图：原始成员顺序原样返回（不可变）。"""

    id: str
    label: str
    queueDate: str
    createdAt: str
    items: list[QueueSnapshotItem]
    segmentOrder: list[str]


# ---- N041 队列本体 ----


@router.post(
    "/api/v1/queue/today/generate",
    response_model=QueueGenerateResponse,
    responses={200: {"model": QueueGenerateResponse}, 201: {"model": QueueGenerateResponse}},
)
async def generate_today_queue(
    payload: QueueGenerateRequest,
    request: Request,
    response: Response,
    force: bool = False,
) -> QueueGenerateResponse:
    """生成（或幂等返回）今天的队列。

    - 队列已存在且未 force → 200 + generated=false（**绝不重排**——
      后台刷新不打扰已确认的队列）；
    - force=1 → 重建：清掉 pending/removed 重新装填，done 状态保留；
    - 新建 → 201 + generated=true。"""
    if payload.workspaceId is not None:
        found = await _get_workspace_store(request).get_workspace(payload.workspaceId)
        if found is None:
            raise WorkspaceNotFound(payload.workspaceId)
    view = await _store(request).generate(
        budget_minutes=payload.timeBudgetMinutes,
        workspace_id=payload.workspaceId,
        force=force,
    )
    if payload.levels:
        view["notes"] = [
            "levels 参数已忽略：N020 关注级别尚未实现，候选只按"
            " 未读 + 近期 挑选；估读为服务端粗估（400 字符/分钟）。"
        ]
    result = QueueGenerateResponse(**view)
    response.status_code = 201 if result.generated else 200
    return result


@router.get("/api/v1/queue/today", response_model=QueueTodayResponse)
async def get_today_queue(request: Request) -> QueueTodayResponse:
    """今日队列视图（pending + done；removed 行保留在库但不出库门）。"""
    view = await _store(request).today_view()
    return QueueTodayResponse(**view)


@router.post(
    "/api/v1/queue/today/items",
    response_model=QueueItemView,
    responses={200: {"model": QueueItemView}, 201: {"model": QueueItemView}},
)
async def add_queue_item(
    payload: QueueAddRequest, request: Request, response: Response
) -> QueueItemView:
    """手动加入（新 201；重复 pending 幂等 200；removed 复活 200；
    今天已完成 → 409 queue_item_done）。"""
    row, outcome = await _store(request).add_item(payload.itemRef, payload.segment)
    response.status_code = 201 if outcome == "created" else 200
    return QueueItemView(**row)


@router.delete("/api/v1/queue/today/items/{item_id}", status_code=204)
async def remove_queue_item(item_id: str, request: Request) -> Response:
    """移除（status=removed，行保留；再移除同一行 → 404）。"""
    await _store(request).remove_item(item_id)
    return Response(status_code=204)


@router.post("/api/v1/queue/today/items/{item_id}/done", response_model=QueueItemView)
async def set_queue_item_done(
    item_id: str, payload: QueueItemDoneRequest, request: Request
) -> QueueItemView:
    """完成状态（set 语义：done=true/false，不是 toggle；完成按条目
    身份记账，绝不隐式改写上游已读状态）。"""
    row = await _store(request).set_item_done(item_id, payload.done)
    return QueueItemView(**row)


@router.put("/api/v1/queue/today/order", response_model=QueueTodayResponse)
async def reorder_today_queue(
    payload: QueueReorderRequest, request: Request
) -> QueueTodayResponse:
    """持久化重排（跨设备可见；done 行位置同样可排）。"""
    await _store(request).reorder(payload.order)
    view = await _store(request).today_view()
    return QueueTodayResponse(**view)


# ---- N042 分段 ----


@router.patch(
    "/api/v1/queue/today/items/{item_id}/segment", response_model=QueueItemView
)
async def move_queue_item_segment(
    item_id: str, payload: QueueSegmentMoveRequest, request: Request
) -> QueueItemView:
    """行菜单移动分段（segment=null = 移回未分组）。"""
    row = await _store(request).set_item_segment(item_id, payload.segment)
    return QueueItemView(**row)


@router.put("/api/v1/queue/today/segments", response_model=QueueTodayResponse)
async def set_queue_segment_order(
    payload: QueueSegmentOrderRequest, request: Request
) -> QueueTodayResponse:
    """段顺序（呈现提示；服务端存储 → 跨设备一致）。"""
    await _store(request).set_segment_order(payload.order)
    view = await _store(request).today_view()
    return QueueTodayResponse(**view)


# ---- N043 冻结快照 ----


@router.post(
    "/api/v1/queue/today/freeze", response_model=QueueSnapshotView, status_code=201
)
async def freeze_today_queue(
    payload: QueueFreezeRequest, request: Request
) -> QueueSnapshotView:
    """把当前 pending 成员冻结为不可变快照（之后加入的项绝不进入）。"""
    meta = await _store(request).freeze(payload.label)
    return QueueSnapshotView(**meta)


@router.get("/api/v1/queue/snapshots", response_model=QueueSnapshotList)
async def list_queue_snapshots(request: Request) -> QueueSnapshotList:
    """快照列表（新→旧）。"""
    views = await _store(request).list_snapshots()
    return QueueSnapshotList(items=[QueueSnapshotView(**view) for view in views])


@router.get(
    "/api/v1/queue/snapshots/{snapshot_id}", response_model=QueueSnapshotDetail
)
async def get_queue_snapshot(snapshot_id: str, request: Request) -> QueueSnapshotDetail:
    """打开冻结视图：原始成员顺序原样返回（消失的 ref 由 Web 呈现
    占位；服务端绝不复活）。"""
    detail = await _store(request).get_snapshot(snapshot_id)
    return QueueSnapshotDetail(**detail)


@router.delete("/api/v1/queue/snapshots/{snapshot_id}", status_code=204)
async def delete_queue_snapshot(snapshot_id: str, request: Request) -> Response:
    """删除一个快照（housekeeping；快照本体在其生命周期内不可变）。"""
    deleted = await _store(request).delete_snapshot(snapshot_id)
    if not deleted:
        raise QueueSnapshotNotFound(snapshot_id)
    return Response(status_code=204)
