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

from typing import Any, Literal

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


class QueueClientItem(BaseModel):
    """N046：客户端本地视图行（冲突差异提示 + 按项合并的 keep-mine 源）。"""

    model_config = {"extra": "forbid"}

    id: str
    itemRef: str
    status: Literal["pending", "done", "removed"] = "pending"
    segment: str | None = None
    position: int | None = None


class QueueGenerateRequest(BaseModel):
    """POST /api/v1/queue/today/generate body。"""

    model_config = {"extra": "forbid"}

    timeBudgetMinutes: int | None = Field(default=None, ge=5, le=480)
    """预算上限（分钟）；缺省 30。候选装填依据（服务端粗估）。"""
    levels: list[str] = Field(default_factory=list, max_length=20)
    """N020 关注级别（must_read|normal|low，normal = 未设置级别）：
    非空时候选池限定到指定级别；候选排序恒为 must_read → normal → low
    （同级内按近期）。非法级别值忽略（诚实有界，不 500）。"""
    workspaceId: str | None = None
    """提供时候选限定为该工作区成员。"""


class QueueItemView(BaseModel):
    """队列成员（呈现数据 best-effort：无投影 → title/estimate 为 null）。"""

    id: str
    itemRef: str
    addedAt: str
    position: int
    queueDate: str
    source: Literal["manual", "budget", "level", "recovery"]
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
    revision: int = 0
    """N046：队列修订号（任何变更 +1；变更请求携带 expectedRevision
    做乐观并发守卫，落后 → 409 queue_revision_conflict）。"""


def _client_items(payload: Any) -> list[dict[str, Any]] | None:
    """pydantic clientItems → store 层 dict 列表（未传 → None）。"""
    items = getattr(payload, "clientItems", None)
    if items is None:
        return None
    return [item.model_dump() for item in items]


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
    expectedRevision: int | None = None
    """N046：乐观并发守卫（给定且落后 → 409 queue_revision_conflict）。"""
    clientItems: list[QueueClientItem] = Field(default_factory=list, max_length=200)
    """N046：客户端本地视图（冲突差异提示 yourItem 的来源；空 = 不带）。"""


class QueueAddResponse(QueueItemView):
    """加入响应 = 队列行 + N047 撞车提示（非阻断：条目已加入）。"""

    outcome: Literal["created", "duplicate", "resurrected"] = "created"
    duplicateWarning: dict[str, Any] | None = None
    """N047：canonical URL 撞车提示 {duplicateOf: {ref, scope, title?}}；
    null = 未撞车。只比 canonical URL，绝无标题相似度合并。"""


class QueueItemDoneRequest(BaseModel):
    """POST /api/v1/queue/today/items/{id}/done body（set 语义）。"""

    model_config = {"extra": "forbid"}

    done: bool
    expectedRevision: int | None = None
    clientItems: list[QueueClientItem] = Field(default_factory=list, max_length=200)


class QueueReorderRequest(BaseModel):
    """PUT /api/v1/queue/today/order body：给定的 id 按序列排前，
    未提及行保持相对顺序垫后（语义同工作区 reorder）。"""

    model_config = {"extra": "forbid"}

    order: list[str] = Field(max_length=200)
    expectedRevision: int | None = None
    clientItems: list[QueueClientItem] = Field(default_factory=list, max_length=200)


class QueueSegmentMoveRequest(BaseModel):
    """PATCH /api/v1/queue/today/items/{id}/segment body。"""

    model_config = {"extra": "forbid"}

    segment: str | None = None
    expectedRevision: int | None = None
    clientItems: list[QueueClientItem] = Field(default_factory=list, max_length=200)


class QueueMergeResolution(BaseModel):
    """N046：单个冲突 ref 的显式裁决。"""

    model_config = {"extra": "forbid"}

    itemRef: str
    action: Literal["keep-mine", "keep-theirs"]
    clientItem: QueueClientItem | None = None
    """action=keep-mine 时必填（应用其 status/segment）。"""


class QueueMergeRequest(BaseModel):
    """POST /api/v1/queue/today/merge-conflicts body。"""

    model_config = {"extra": "forbid"}

    expectedRevision: int
    resolutions: list[QueueMergeResolution] = Field(min_length=1, max_length=200)


class QueueMergeResponse(QueueTodayResponse):
    """合并后的今日视图 + 合并元数据。"""

    merge: dict[str, Any]


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
        levels=payload.levels,
    )
    if not payload.levels:
        view.setdefault(
            "notes",
            [
                "候选排序：N020 关注级别（must_read 优先，normal 次之，low 垫后）"
                "+ 近期；估读为服务端粗估（400 字符/分钟）。"
            ],
        )
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
    response_model=QueueAddResponse,
    responses={200: {"model": QueueAddResponse}, 201: {"model": QueueAddResponse}},
)
async def add_queue_item(
    payload: QueueAddRequest, request: Request, response: Response
) -> QueueAddResponse:
    """手动加入（新 201；重复 pending 幂等 200；removed 复活 200；
    今天已完成 → 409 queue_item_done）。

    N046：expectedRevision 落后 → 409 queue_revision_conflict（写入前
    发生，冲突绝不半途落库）。N047：加入成功后做 canonical URL 撞车
    检查——warning 附在成功响应里（非阻断，绝不因撞车拒绝写入）。"""
    row, outcome = await _store(request).add_item(
        payload.itemRef,
        payload.segment,
        expected_revision=payload.expectedRevision,
        client_items=_client_items(payload),
    )
    duplicate_warning = None
    if outcome == "created":
        from lumirss.link_dedupe import find_duplicate_for_ref

        duplicate_warning = await find_duplicate_for_ref(
            request.app.state.db, payload.itemRef
        )
    response.status_code = 201 if outcome == "created" else 200
    return QueueAddResponse(**row, outcome=outcome, duplicateWarning=duplicate_warning)


@router.delete("/api/v1/queue/today/items/{item_id}", status_code=204)
async def remove_queue_item(
    item_id: str,
    request: Request,
    expectedRevision: int | None = None,
) -> Response:
    """移除（status=removed，行保留；再移除 → 404）。

    N046：expectedRevision 落后 → 409（DELETE 无 body，clientItems 不
    随行——冲突体的 yourItem 为 null，客户端以本地面板状态补全）。"""
    await _store(request).remove_item(item_id, expected_revision=expectedRevision)
    return Response(status_code=204)


@router.post("/api/v1/queue/today/items/{item_id}/done", response_model=QueueItemView)
async def set_queue_item_done(
    item_id: str, payload: QueueItemDoneRequest, request: Request
) -> QueueItemView:
    """完成状态（set 语义：done=true/false，不是 toggle；完成按条目
    身份记账，绝不隐式改写上游已读状态）。N046：expectedRevision
    落后 → 409。"""
    row = await _store(request).set_item_done(
        item_id,
        payload.done,
        expected_revision=payload.expectedRevision,
        client_items=_client_items(payload),
    )
    return QueueItemView(**row)


@router.put("/api/v1/queue/today/order", response_model=QueueTodayResponse)
async def reorder_today_queue(
    payload: QueueReorderRequest, request: Request
) -> QueueTodayResponse:
    """持久化重排（跨设备可见；done 行位置同样可排）。N046：
    expectedRevision 落后 → 409。"""
    await _store(request).reorder(
        payload.order,
        expected_revision=payload.expectedRevision,
        client_items=_client_items(payload),
    )
    view = await _store(request).today_view()
    return QueueTodayResponse(**view)


# ---- N042 分段 ----


@router.patch(
    "/api/v1/queue/today/items/{item_id}/segment", response_model=QueueItemView
)
async def move_queue_item_segment(
    item_id: str, payload: QueueSegmentMoveRequest, request: Request
) -> QueueItemView:
    """行菜单移动分段（segment=null = 移回未分组）。N046：
    expectedRevision 落后 → 409。"""
    row = await _store(request).set_item_segment(
        item_id,
        payload.segment,
        expected_revision=payload.expectedRevision,
        client_items=_client_items(payload),
    )
    return QueueItemView(**row)


# ---- N046 按项合并 ----


@router.post(
    "/api/v1/queue/today/merge-conflicts", response_model=QueueMergeResponse
)
async def merge_queue_conflicts(
    payload: QueueMergeRequest, request: Request
) -> QueueMergeResponse:
    """按项合并：对 409 冲突体里的每个 ref 显式选择 keep-mine（应用
    clientItem 的 status/segment）或 keep-theirs（保持服务端现状）。

    - 修订号必须仍与 current 一致（期间又被改 → 再 409，重新取差异）；
    - 合并整体 bump 一次修订号；未提及的行原样保留（unmodified
      items survive——负向契约）；
    - keep-theirs 语义 = 放弃本地该行的变更，不是删除服务端行。"""
    view = await _store(request).merge_conflicts(
        payload.expectedRevision,
        [resolution.model_dump() for resolution in payload.resolutions],
    )
    return QueueMergeResponse(**view)


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
