"""Workspace routes (phase2 M1) — ref collections + unified resolve.

Workspaces hold typed ItemRefs only; resolving them to unified ViewModels
goes through the Source Registry (:mod:`lumirss.sources`). The reserved
``read-later`` workspace cannot be deleted or renamed.
"""

import asyncio
import logging
from datetime import UTC
from typing import Any

from fastapi import APIRouter, Query, Request, Response

from lumirss.itemref import (
    LIBRARY_DOMAIN,
    RSS_DOMAIN,
    InvalidItemRef,
    parse_item_ref,
)
from lumirss.models import (
    CompileExcluded,
    CompileItem,
    CompileRequest,
    CompileResponse,
    CompileSection,
    ReadLaterItem,
    ReadLaterSnoozedList,
    ReadLaterSnoozeRequest,
    ReadLaterSnoozeResult,
    ReadLaterTimelineResponse,
    ResearchPackPreviewRequest,
    ResearchPackRequest,
    ResolvedItem,
    ResolveRequest,
    SharePackageRequest,
    Workspace,
    WorkspaceCleanupApplyRequest,
    WorkspaceCleanupApplyResult,
    WorkspaceCleanupCategory,
    WorkspaceCleanupLogList,
    WorkspaceCleanupPreviewResponse,
    WorkspaceCleanupUndoRequest,
    WorkspaceCleanupUndoResult,
    WorkspaceCreate,
    WorkspaceGroupOrderPut,
    WorkspaceGroupsResponse,
    WorkspaceItem,
    WorkspaceItemAddRequest,
    WorkspaceItemGroupMoveRequest,
    WorkspaceItemMoveRequest,
    WorkspaceItemMoveResult,
    WorkspaceItemPinRequest,
    WorkspaceItemsResolvedResponse,
    WorkspaceItemsResponse,
    WorkspaceListResponse,
    WorkspacePatch,
    WorkspaceReorderRequest,
    WorkspaceResumePointer,
    WorkspaceResumePutRequest,
    WorkspaceResumeResponse,
    WorkspaceSearchHit,
    WorkspaceSearchResponse,
    WorkspaceSectionCreate,
    WorkspaceSectionItem,
    WorkspaceSectionItemAddRequest,
    WorkspaceSectionItemsOrderPut,
    WorkspaceSectionList,
    WorkspaceSectionOrderPut,
    WorkspaceSectionPatch,
    WorkspaceSectionView,
    WorkspaceSnapshot,
    WorkspaceSnapshotCreate,
    WorkspaceSnapshotDiff,
    WorkspaceSnapshotList,
    WorkspaceSnapshotRestoreRequest,
    WorkspaceSnapshotRestoreResult,
)
from lumirss.sources import (
    ItemRefUnresolvable,
    ensure_resolvable,
    resolve_item,
    stale_placeholder,
)
from lumirss.util import utc_now
from lumirss.workspaces import (
    RESERVED_WORKSPACE_ID,
    WorkspaceInvalid,
    WorkspaceItemDuplicate,
    WorkspaceNotFound,
    WorkspaceStore,
)

from ..deps import _get_library_store, _get_source_registry, _get_workspace_store

router = APIRouter()

_DEFAULT_ITEM_LIMIT = 200
_MAX_ITEM_LIMIT = 500
_MAX_RESOLVE_REFS = 100
# Pool #44: resolve fan-out is bounded — one page must not start one
# upstream round trip per ref with no ceiling. 16 concurrent resolves
# keeps worst-case page latency at ceil(refs/16) round trips while a
# slow FreshRSS cannot pin hundreds of event-loop tasks.
_RESOLVE_CONCURRENCY = 16
_RESOLVE_TIMEOUT_S = 15.0
_resolve_semaphore: asyncio.Semaphore = asyncio.Semaphore(_RESOLVE_CONCURRENCY)

_logger = logging.getLogger("lumirss.sources")


def _groups_model(overview: dict) -> WorkspaceGroupsResponse:
    """store.group_overview → API 模型（固定区 + 分组序列）。"""
    return WorkspaceGroupsResponse(
        workspaceId=overview["workspaceId"],
        revision=overview["revision"],
        groupOrder=overview["groupOrder"],
        pinned=[_item_model(item) for item in overview["pinned"]],
        groups=[
            {"name": group["name"], "items": [_item_model(i) for i in group["items"]]}
            for group in overview["groups"]
        ],
    )


def _snapshot_model(view: dict) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(
        id=view["id"],
        workspaceId=view["workspaceId"],
        name=view["name"],
        createdAt=view["createdAt"],
        itemCount=view["itemCount"],
    )


def _snapshot_store(request: Request):
    from lumirss.workspace_snapshots import WorkspaceSnapshotStore

    return WorkspaceSnapshotStore(request.app.state.db, _get_workspace_store(request))


async def _resolve_bounded(registry: dict, ref: str) -> ResolvedItem:
    """One ref resolve under the shared concurrency cap and a per-item
    deadline; upstream failures become distinguishable stale cards
    (pool #13/#44), never a whole-page 500 and never a silent fake
    success. A malformed ref stays a client error (400), as before."""
    try:
        async with _resolve_semaphore:
            return await asyncio.wait_for(
                resolve_item(registry, ref), timeout=_RESOLVE_TIMEOUT_S
            )
    except TimeoutError:
        return stale_placeholder(ref, "timeout", title="解析超时，请稍后重试")
    except InvalidItemRef:
        raise
    except Exception:
        _logger.exception("resolve failed for ref %s", ref)
        return stale_placeholder(ref, "error", title="暂时无法解析，请稍后重试")


def _workspace_model(summary) -> Workspace:
    return Workspace(
        id=summary.id,
        name=summary.name,
        position=summary.position,
        itemCount=summary.item_count,
        reserved=summary.reserved,
        description=summary.description,
        archived=summary.archived,
        archivedAt=summary.archived_at,
        revision=summary.revision,
    )


def _item_model(item) -> WorkspaceItem:
    return WorkspaceItem(
        itemRef=item.item_ref,
        position=item.position,
        addedAt=item.added_at,
        groupName=item.group_name,
        pinned=item.pinned,
    )


def _resolved_models(views) -> list[ResolvedItem]:
    return [
        ResolvedItem(
            ref=view.ref,
            domain=view.domain,
            kind=view.kind,
            title=view.title,
            source=view.source,
            datetime=view.datetime,
            excerpt=view.excerpt,
            url=view.url,
            stale=view.stale,
            staleReason=view.staleReason,
            payload=view.payload,
        )
        for view in views
    ]


@router.post("/api/v1/workspaces", response_model=Workspace, status_code=201)
async def create_workspace(payload: WorkspaceCreate, request: Request) -> Workspace:
    store: WorkspaceStore = _get_workspace_store(request)
    return _workspace_model(
        await store.create_workspace(payload.name, payload.description or "")
    )


@router.get("/api/v1/workspaces", response_model=WorkspaceListResponse)
async def list_workspaces(request: Request) -> WorkspaceListResponse:
    store: WorkspaceStore = _get_workspace_store(request)
    summaries = await store.list_workspaces()
    return WorkspaceListResponse(
        items=[_workspace_model(summary) for summary in summaries]
    )


@router.get("/api/v1/workspaces/{workspace_id}", response_model=Workspace)
async def get_workspace(workspace_id: str, request: Request) -> Workspace:
    store: WorkspaceStore = _get_workspace_store(request)
    summary = await store.get_workspace(workspace_id)
    if summary is None:
        raise WorkspaceNotFound(workspace_id)
    return _workspace_model(summary)


@router.patch("/api/v1/workspaces/{workspace_id}", response_model=Workspace)
async def rename_workspace(
    workspace_id: str, payload: WorkspacePatch, request: Request
) -> Workspace:
    """F084：PATCH 扩展——archived=true 归档 / false 恢复；name/description
    缺省 = 不修改（与归档可同请求组合）。"""
    store: WorkspaceStore = _get_workspace_store(request)
    if payload.archived is not None:
        from lumirss.workspace_archive import WorkspaceArchiveStore

        archive = WorkspaceArchiveStore(request.app.state.db, store)
        try:
            if payload.archived:
                await archive.archive(workspace_id)
            else:
                await archive.restore(workspace_id)
        except KeyError as exc:
            raise WorkspaceNotFound(workspace_id) from exc
    if payload.name is not None:
        await store.rename_workspace(
            workspace_id, payload.name, payload.description
        )
    summary = await store.get_workspace(workspace_id)
    if summary is None:
        raise WorkspaceNotFound(workspace_id)
    return _workspace_model(summary)


@router.delete("/api/v1/workspaces/{workspace_id}", status_code=204)
async def delete_workspace(workspace_id: str, request: Request) -> Response:
    store: WorkspaceStore = _get_workspace_store(request)
    deleted = await store.delete_workspace(workspace_id)
    if not deleted:
        raise WorkspaceNotFound(workspace_id)
    return Response(status_code=204)


@router.post(
    "/api/v1/workspaces/{workspace_id}/items",
    response_model=WorkspaceItem,
    status_code=201,
)
async def add_workspace_item(
    workspace_id: str, payload: WorkspaceItemAddRequest, request: Request
) -> WorkspaceItem:
    """Idempotent add of one typed ItemRef (returns 201 with current slot).

    The ref must resolve (ADR 0004): writes never create dangling
    membership. A known-but-stale domain (FreshRSS unconfigured) passes.
    N101：``groupName`` 可选（null/缺省 = 未分组隐式前置组）；幂等重放
    返回既有行原样——改组归属走 PATCH .../group。
    """
    registry = _get_source_registry(request)

    try:
        await ensure_resolvable(registry, payload.itemRef)
    except ItemRefUnresolvable as exc:
        raise WorkspaceInvalid("引用的内容不存在，无法加入工作区。") from exc
    store: WorkspaceStore = _get_workspace_store(request)
    item = await store.add_item(workspace_id, payload.itemRef, payload.groupName)
    # N047：canonical URL 撞车检查（非阻断——条目已加入；warning 附在
    # 响应里，客户端提供 定位/仍要加入）。比较范围 = 队列 pending 行 +
    # 队列冻结快照 + 本工作区其他成员。解析不出 URL 的条目不提示。
    duplicate_warning = None
    try:
        from lumirss.link_dedupe import find_duplicate_for_ref

        same_ws = [
            (other.item_ref, "workspace")  # ItemRef 同构：rss:<entryRef>
            for other in await store.list_items(workspace_id, limit=200)
            if other.item_ref != payload.itemRef
        ]
        duplicate_warning = await find_duplicate_for_ref(
            request.app.state.db, payload.itemRef, extra_refs=same_ws
        )
    except Exception:  # noqa: BLE001 — 提示是尽力而为，绝不阻断加入
        duplicate_warning = None
    model = _item_model(item)
    model.duplicateWarning = duplicate_warning
    return model


@router.get(
    "/api/v1/workspaces/{workspace_id}/items",
    response_model=WorkspaceItemsResponse,
)
async def list_workspace_items(
    workspace_id: str, request: Request, limit: int = _DEFAULT_ITEM_LIMIT
) -> WorkspaceItemsResponse:
    if limit < 1 or limit > _MAX_ITEM_LIMIT:
        raise WorkspaceInvalid(f"limit must be between 1 and {_MAX_ITEM_LIMIT}.")
    store: WorkspaceStore = _get_workspace_store(request)
    items = await store.list_items(workspace_id, limit=limit)
    return WorkspaceItemsResponse(items=[_item_model(item) for item in items])


@router.patch(
    "/api/v1/workspaces/{workspace_id}/items",
    response_model=WorkspaceItemsResponse,
)
async def reorder_workspace_items(
    workspace_id: str, payload: WorkspaceReorderRequest, request: Request
) -> WorkspaceItemsResponse:
    """P15：``expectedRevision`` 可选（If-Match 式）；与当前 revision
    不匹配 → 409 workspace_revision_conflict（错误体带 currentRevision），
    客户端重取后重试；不传 = 旧行为（last-write-wins），兼容既有调用方。"""
    store: WorkspaceStore = _get_workspace_store(request)
    await store.reorder_items(
        workspace_id, payload.itemRefs, payload.expectedRevision
    )
    items = await store.list_items(workspace_id)
    return WorkspaceItemsResponse(items=[_item_model(item) for item in items])


@router.delete(
    "/api/v1/workspaces/{workspace_id}/items/{item_ref}", status_code=204
)
async def remove_workspace_item(
    workspace_id: str, item_ref: str, request: Request, force: bool = False
) -> Response:
    """移除一个成员（幂等契约：非成员也 404 诚实报错）。

    N102：固定条目拒绝静默移除——不带 ``?force=1`` → 409
    workspace_item_pinned；``?force=1`` 显式确认后才放行。"""
    store: WorkspaceStore = _get_workspace_store(request)
    removed = await store.remove_item(workspace_id, item_ref, force=force)
    if not removed:
        raise WorkspaceInvalid("Item is not a member of this workspace.")
    return Response(status_code=204)


@router.post(
    "/api/v1/workspaces/{workspace_id}/items/{item_ref}/move",
    response_model=WorkspaceItemMoveResult,
)
async def move_workspace_item(
    workspace_id: str,
    item_ref: str,
    payload: WorkspaceItemMoveRequest,
    request: Request,
) -> Any:
    """N108：跨工作区移动成员（同一 ItemRef——底层对象绝不复制）。

    - 幂等：目标已有该条目默认 skip（结果 duplicate=true，绝不产生
      第二份内容）；``onDuplicate='conflict'`` 显式选择 409；
    - ``keepInSource=true`` 保留源成员关系（双工作区同持）；
    - 预览侧（Web 移动对话框）用既有列表 API 展示重复/关系影响。"""
    from fastapi.responses import JSONResponse

    if payload.targetWorkspaceId == workspace_id:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "type": "invalid_workspace",
                    "message": "目标工作区不能与源工作区相同。",
                }
            },
        )
    store: WorkspaceStore = _get_workspace_store(request)
    try:
        result = await store.move_item(
            workspace_id,
            item_ref,
            payload.targetWorkspaceId,
            keep_in_source=payload.keepInSource,
            on_duplicate=payload.onDuplicate,
        )
    except WorkspaceItemDuplicate:
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "type": "workspace_item_duplicate",
                    "message": "目标工作区已存在该条目（onDuplicate=conflict）。",
                }
            },
        )
    if result is None:
        raise WorkspaceInvalid("Item is not a member of this workspace.")
    return WorkspaceItemMoveResult(**result)


@router.get(
    "/api/v1/workspaces/{workspace_id}/groups",
    response_model=WorkspaceGroupsResponse,
)
async def get_workspace_groups(
    workspace_id: str, request: Request, limit: int = _DEFAULT_ITEM_LIMIT
) -> WorkspaceGroupsResponse:
    """N101：分组视图——固定区（N102）在最前，未分组 = 隐式前置组，
    命名组按 group_order_json 排序（未列入的按名字典序追加）。"""
    store: WorkspaceStore = _get_workspace_store(request)
    overview = await store.group_overview(workspace_id, limit=limit)
    return _groups_model(overview)


@router.put(
    "/api/v1/workspaces/{workspace_id}/groups",
    response_model=WorkspaceGroupsResponse,
)
async def put_workspace_group_order(
    workspace_id: str, payload: WorkspaceGroupOrderPut, request: Request
) -> WorkspaceGroupsResponse:
    """N101：设置命名组呈现顺序（PUT 幂等；不创建、不重命名组）。

    名字必须是当前真实存在的组（400 拒绝未知名字）；顺序真实变化才
    bump revision。"""
    store: WorkspaceStore = _get_workspace_store(request)
    await store.set_group_order(workspace_id, payload.order)
    overview = await store.group_overview(workspace_id)
    return _groups_model(overview)


@router.patch(
    "/api/v1/workspaces/{workspace_id}/items/{item_ref}/group",
    response_model=WorkspaceItem,
)
async def move_workspace_item_group(
    workspace_id: str,
    item_ref: str,
    payload: WorkspaceItemGroupMoveRequest,
    request: Request,
) -> WorkspaceItem:
    """N101：移动条目到分组（``groupName=null`` 移回未分组隐式前置组）。

    条目非成员 → 404；组归属真实变化才 bump revision（幂等重放不
    制造跨设备 409 噪声）。"""
    store: WorkspaceStore = _get_workspace_store(request)
    item = await store.set_item_group(workspace_id, item_ref, payload.groupName)
    if item is None:
        raise WorkspaceNotFound(f"workspace item {item_ref}")
    return _item_model(item)


@router.put(
    "/api/v1/workspaces/{workspace_id}/items/{item_ref}/pin",
    response_model=WorkspaceItem,
)
async def pin_workspace_item(
    workspace_id: str, item_ref: str, payload: WorkspaceItemPinRequest, request: Request
) -> WorkspaceItem:
    """N102：设置固定标记（set 语义非 toggle；幂等重放不 bump）。

    固定条目在分组视图中排所有组之前；移除需 DELETE ?force=1。"""
    store: WorkspaceStore = _get_workspace_store(request)
    item = await store.set_item_pinned(workspace_id, item_ref, payload.pinned)
    if item is None:
        raise WorkspaceNotFound(f"workspace item {item_ref}")
    return _item_model(item)


# -- N105 工作区会话快照 -------------------------------------------------------


@router.post(
    "/api/v1/workspaces/{workspace_id}/snapshots",
    response_model=WorkspaceSnapshot,
    status_code=201,
)
async def capture_workspace_snapshot(
    workspace_id: str, payload: WorkspaceSnapshotCreate, request: Request
) -> WorkspaceSnapshot:
    """捕获当前标签页/分组状态为命名快照（只存 ref + 排序元数据，
    绝不复制内容；上限 50 个/工作区）。"""
    snapshot = await _snapshot_store(request).capture(workspace_id, payload.name)
    return _snapshot_model(snapshot)


@router.get(
    "/api/v1/workspaces/{workspace_id}/snapshots",
    response_model=WorkspaceSnapshotList,
)
async def list_workspace_snapshots(
    workspace_id: str, request: Request
) -> WorkspaceSnapshotList:
    """快照列表（新→旧）。未知工作区 → 404（诚实报错）。"""
    store = _snapshot_store(request)
    store_for_ws: WorkspaceStore = _get_workspace_store(request)
    if await store_for_ws.get_workspace(workspace_id) is None:
        raise WorkspaceNotFound(workspace_id)
    views = await store.list_snapshots(workspace_id)
    return WorkspaceSnapshotList(items=[_snapshot_model(v) for v in views])


@router.delete(
    "/api/v1/workspaces/{workspace_id}/snapshots/{snapshot_id}", status_code=204
)
async def delete_workspace_snapshot(
    workspace_id: str, snapshot_id: str, request: Request
) -> Response:
    """删除一个快照（Web 侧删除前二次确认）。"""
    deleted = await _snapshot_store(request).delete(workspace_id, snapshot_id)
    if not deleted:
        from lumirss.workspace_snapshots import WorkspaceSnapshotNotFound

        raise WorkspaceSnapshotNotFound(snapshot_id)
    return Response(status_code=204)


@router.post(
    "/api/v1/workspaces/{workspace_id}/snapshots/{snapshot_id}/restore",
    response_model=WorkspaceSnapshotRestoreResult,
)
async def restore_workspace_snapshot(
    workspace_id: str,
    snapshot_id: str,
    payload: WorkspaceSnapshotRestoreRequest,
    request: Request,
) -> WorkspaceSnapshotRestoreResult:
    """恢复快照（reorder | replace），返回 diff 摘要。

    - 快照中已消失的 ref 上报 ``missing``，绝不复活（内容从未复制）；
    - ``replace`` 移除快照外成员（列表见 ``removed``）；固定条目受
      N102 保护——拒绝丢固定条目除非 ``force=true``（409
      workspace_item_pinned）；
    - 真实写库时 bump revision（P15 并发）。"""
    store = _snapshot_store(request)
    result = await store.restore(
        workspace_id, snapshot_id, payload.mode, force=payload.force
    )
    summary: WorkspaceStore = _get_workspace_store(request)
    refreshed = await summary.get_workspace(workspace_id)
    revision = refreshed.revision if refreshed is not None else 0
    return WorkspaceSnapshotRestoreResult(
        restored=result["restored"],
        missing=result["missing"],
        kept=result["kept"],
        removed=result["removed"],
        revision=revision,
    )


@router.get(
    "/api/v1/workspaces/{workspace_id}/snapshots/{snapshot_id_a}/diff/{snapshot_id_b}",
    response_model=WorkspaceSnapshotDiff,
)
async def diff_workspace_snapshots(
    workspace_id: str,
    snapshot_id_a: str,
    snapshot_id_b: str,
    request: Request,
) -> WorkspaceSnapshotDiff:
    """N115：两快照差异（纯只读）。

    - ``added`` / ``removed``：B 相对 A 的成员增减（ref 列表）；
    - ``moved``：两者都有但位置变化（fromPos → toPos）；
    - ``groupChanges``：两者都有但分组归属变化（null = 未分组）；
    - ref 的内容定位走既有 views/resolve 端点（本端点绝不解析内容，
      绝不触碰工作区成员行）。"""
    ws_store: WorkspaceStore = _get_workspace_store(request)
    if await ws_store.get_workspace(workspace_id) is None:
        raise WorkspaceNotFound(workspace_id)
    result = await _snapshot_store(request).diff(
        workspace_id, snapshot_id_a, snapshot_id_b
    )
    return WorkspaceSnapshotDiff(**result)


@router.put(
    "/api/v1/workspaces/{workspace_id}/resume",
    response_model=WorkspaceResumeResponse,
)
async def put_workspace_resume(
    workspace_id: str, payload: WorkspaceResumePutRequest, request: Request
) -> WorkspaceResumeResponse:
    """P15：保存「上次看到哪」指针（每工作区一个；PUT 幂等 upsert）。

    校验与 add_item 同构：404 未知工作区 / 404 条目不在工作区。
    不 bump revision（阅读光标 ≠ 共享条目状态，见 store 注释）。"""
    store: WorkspaceStore = _get_workspace_store(request)
    pointer = await store.set_resume(workspace_id, payload.itemRef)
    return WorkspaceResumeResponse(
        workspaceId=workspace_id,
        pointer=WorkspaceResumePointer(
            itemRef=pointer.item_ref,
            positionAtSave=pointer.position_at_save,
            updatedAt=pointer.updated_at,
        ),
    )


@router.get(
    "/api/v1/workspaces/{workspace_id}/resume",
    response_model=WorkspaceResumeResponse,
)
async def get_workspace_resume(
    workspace_id: str, request: Request
) -> WorkspaceResumeResponse:
    """P15：读取续读指针；无指针（含未知工作区）返回 pointer=null。"""
    store: WorkspaceStore = _get_workspace_store(request)
    pointer = await store.get_resume(workspace_id)
    return WorkspaceResumeResponse(
        workspaceId=workspace_id,
        pointer=(
            WorkspaceResumePointer(
                itemRef=pointer.item_ref,
                positionAtSave=pointer.position_at_save,
                updatedAt=pointer.updated_at,
            )
            if pointer is not None
            else None
        ),
    )


@router.get(
    "/api/v1/workspaces/{workspace_id}/contents",
    response_model=WorkspaceItemsResolvedResponse,
)
async def workspace_contents(
    workspace_id: str, request: Request, limit: int = _DEFAULT_ITEM_LIMIT
) -> WorkspaceItemsResolvedResponse:
    """Ordered membership with each ref resolved to a unified ViewModel.

    Stale rss refs (entry gone from FreshRSS) resolve to ``stale=True``
    views — rows are never auto-deleted.
    """
    if limit < 1 or limit > _MAX_ITEM_LIMIT:
        raise WorkspaceInvalid(f"limit must be between 1 and {_MAX_ITEM_LIMIT}.")
    store: WorkspaceStore = _get_workspace_store(request)
    items = await store.list_items(workspace_id, limit=limit)
    registry = _get_source_registry(request)

    # Refs resolve independently (rss hits FreshRSS, library stays local)
    # under the shared concurrency cap (pool #44); one broken ref degrades
    # to its own stale card instead of 500ing the page.
    resolved = list(
        await asyncio.gather(
            *(_resolve_bounded(registry, item.item_ref) for item in items)
        )
    )
    return WorkspaceItemsResolvedResponse(items=_resolved_models(resolved))


# ---- N109：工作区标签全文检索 ------------------------------------------------

_WORKSPACE_SEARCH_MAX_HITS = 200
_WORKSPACE_SEARCH_EXCERPT = 160
# SQLite 变量数上限远大于此；分块只为了让超大工作区（≤500 成员）的
# IN 查询保持有界。
_SEARCH_IN_CHUNK = 100


def _search_excerpt(text: str, needle_lower: str, limit: int) -> str:
    """命中处上下文摘要（≤limit 字符；截断侧加 …）。仅标题命中 → 标题。"""
    text = str(text or "")
    idx = text.lower().find(needle_lower)
    if idx < 0:
        return text[:limit]
    start = max(0, idx - limit // 4)
    chunk = text[start : start + limit]
    prefix = "…" if start > 0 else ""
    suffix = "…" if start + limit < len(text) else ""
    return f"{prefix}{chunk}{suffix}"


async def _fetch_projection_rows(
    db, table: str, key_col: str, keys: list[str], fields: tuple[str, ...]
) -> dict[str, dict]:
    """按主键分块拉取搜索投影行（表/列名均为代码内常量，值全部绑定）。"""
    out: dict[str, dict] = {}
    for start in range(0, len(keys), _SEARCH_IN_CHUNK):
        chunk = keys[start : start + _SEARCH_IN_CHUNK]
        placeholders = ",".join("?" for _ in chunk)
        rows = await db.fetch_all(
            f"SELECT {key_col} AS _key, {', '.join(fields)} FROM {table} WHERE {key_col} IN ({placeholders})",
            tuple(chunk),
        )
        for row in rows:
            out[str(row["_key"])] = dict(row)
    return out


@router.get(
    "/api/v1/workspaces/{workspace_id}/search",
    response_model=WorkspaceSearchResponse,
)
async def search_workspace(
    workspace_id: str,
    request: Request,
    q: str = Query(min_length=1, max_length=200),
) -> WorkspaceSearchResponse:
    """N109：在「当前工作区自己的条目」内做标题 + 全文检索。

    范围严格限定工作区成员关系：先把 workspace_items 的 ref 全部取出，
    再按域查各自的派生投影（rss → search_entries.content_text；library
    → search_library.body）。其他工作区的条目即使内容命中也绝不返回；
    投影缺失（ref 已失效/未同步）的成员诚实跳过。命中 ≤200 条，每条
    摘要 ≤160 字符。"""
    needle = q.strip().lower()
    store: WorkspaceStore = _get_workspace_store(request)
    if await store.get_workspace(workspace_id) is None:
        raise WorkspaceNotFound(workspace_id)
    if needle == "":
        return WorkspaceSearchResponse(workspaceId=workspace_id, query=q, results=[])
    members = await store.list_items(workspace_id, limit=_MAX_ITEM_LIMIT)

    rss_keys: list[str] = []
    library_keys: list[str] = []
    for item in members:
        try:
            ref = parse_item_ref(item.item_ref)
        except InvalidItemRef:
            continue  # 损坏的 ref 不参与匹配（成员列表自身会把它显示为失效）
        if ref.domain == RSS_DOMAIN:
            rss_keys.append(ref.key)
        elif ref.domain == LIBRARY_DOMAIN:
            # search_library.ref 存完整 itemRef 形态（library:<uuid>）。
            library_keys.append(item.item_ref)
    rss_rows = await _fetch_projection_rows(
        request.app.state.db, "search_entries", "entry_ref", rss_keys, ("title", "content_text")
    )
    library_rows = await _fetch_projection_rows(
        request.app.state.db, "search_library", "ref", library_keys, ("title", "body")
    )

    results: list[WorkspaceSearchHit] = []
    truncated = False
    for item in members:
        try:
            ref = parse_item_ref(item.item_ref)
        except InvalidItemRef:
            continue
        if ref.domain == RSS_DOMAIN:
            row = rss_rows.get(ref.key)
            body = str(row.get("content_text", "")) if row else ""
        elif ref.domain == LIBRARY_DOMAIN:
            row = library_rows.get(item.item_ref)
            body = str(row.get("body", "")) if row else ""
        else:
            continue
        if row is None:
            continue  # 投影缺失 → 无标题也无内容可匹配，诚实跳过
        title = str(row.get("title", "") or "")
        in_title = needle in title.lower()
        in_content = needle in body.lower()
        if not in_title and not in_content:
            continue
        if len(results) >= _WORKSPACE_SEARCH_MAX_HITS:
            truncated = True
            break
        if in_title and in_content:
            matched_in = "title+content"
        elif in_title:
            matched_in = "title"
        else:
            matched_in = "content"
        excerpt = (
            _search_excerpt(body, needle, _WORKSPACE_SEARCH_EXCERPT)
            if in_content
            else title[:_WORKSPACE_SEARCH_EXCERPT]
        )
        results.append(
            WorkspaceSearchHit(
                itemRef=item.item_ref,
                domain=ref.domain,
                title=title,
                excerpt=excerpt,
                matchedIn=matched_in,
            )
        )
    return WorkspaceSearchResponse(
        workspaceId=workspace_id, query=q, truncated=truncated, results=results
    )


@router.post(
    "/api/v1/workspaces/{workspace_id}/research-pack/preview",
    response_model=None,
)
async def preview_research_pack(
    workspace_id: str, payload: ResearchPackPreviewRequest, request: Request
):
    """F088：资料包预览（计数 + 体积估算 + 可选快照清单；缺失诚实跳过）。"""
    from pathlib import Path

    from lumirss.config import LumiSettings
    from lumirss.models import ResearchPackPreviewResponse
    from lumirss.research_pack_zip import ResearchPackZipBuilder

    store = _get_workspace_store(request)
    summary = await store.get_workspace(workspace_id)
    if summary is None:
        raise WorkspaceNotFound(workspace_id)
    members = await store.list_items(workspace_id, limit=500)
    registry = _get_source_registry(request)
    resolved = list(
        await asyncio.gather(
            *(_resolve_bounded(registry, member.item_ref) for member in members)
        )
    )
    missing = sum(1 for view in resolved if view.stale)
    asset_root = Path(LumiSettings().data_dir) / "library" / "assets"
    builder = ResearchPackZipBuilder(request.app.state.db, asset_root)
    preview = await builder.preview(
        entry_count=len(members),
        missing_count=missing,
        include_snapshots=payload.includeSnapshots,
    )
    return ResearchPackPreviewResponse(
        entryCount=preview["entryCount"],
        missingCount=preview["missingCount"],
        estBytes=preview["estBytes"],
        snapshots=preview["snapshots"],
    )


@router.post(
    "/api/v1/workspaces/{workspace_id}/research-pack",
)
async def export_research_pack(
    workspace_id: str,
    payload: ResearchPackRequest,
    request: Request,
    format: str | None = None,
) -> Response:
    """F27 研究包导出（Markdown + manifest；只读，可重现）。

    条目小节 = 解析后的标题/链接/摘录（含书签笔记可选并入）；缺失来源
    明确标注缺失原因，不冒充内容；文末附机器可读 manifest（条目数、缺
    失数、生成时间）。路径安全：只输出文本与 URL。"""
    import json as _json
    from urllib.parse import quote

    store = _get_workspace_store(request)
    summary = await store.get_workspace(workspace_id)
    if summary is None:
        raise WorkspaceNotFound(workspace_id)
    members = await store.list_items(workspace_id, limit=500)
    registry = _get_source_registry(request)
    resolved = list(
        await asyncio.gather(
            *(_resolve_bounded(registry, member.item_ref) for member in members)
        )
    )
    notes_by_ref: dict[str, str] = {}
    if payload.includeNotes:
        library = _get_library_store(request)
        for member in members:
            if member.item_ref.startswith("library:"):
                view = await library.get_library_item(
                    member.item_ref.removeprefix("library:")
                )
                if view is not None and view.note:
                    notes_by_ref[member.item_ref] = view.note

    lines = [
        f"# {payload.title or summary.name}（研究包）",
        "",
        f"- 生成时间：{utc_now()}",
        f"- 工作区：{summary.name}" + (f"（{summary.description}）" if summary.description else ""),
        f"- 条目数：{len(members)}",
        "",
        "## 条目",
        "",
    ]
    manifest_entries = []
    missing = 0
    for member, view in zip(members, resolved, strict=True):
        entry = {
            "itemRef": member.item_ref,
            "title": view.title,
            "url": view.url,
            "stale": view.stale,
        }
        if view.stale:
            missing += 1
            lines.append(f"### {view.title}（缺失：{view.staleReason or '来源不可用'}）")
            lines.append("")
            continue
        lines.append(f"### {view.title}")
        lines.append("")
        if view.url:
            lines.append(f"- 链接：{view.url}")
        if view.excerpt:
            lines.append(f"- 摘录：{view.excerpt}")
        if member.item_ref in notes_by_ref:
            lines.append(f"- 笔记：{notes_by_ref[member.item_ref]}")
        lines.append("")
        manifest_entries.append(entry)

    manifest = {
        "kind": "lumirss-research-pack",
        "schemaVersion": 1,
        "workspace": {"id": workspace_id, "name": summary.name},
        "entryCount": len(members),
        "missingCount": missing,
        "generatedAt": utc_now(),
        "includeNotes": payload.includeNotes,
        "entries": manifest_entries,
    }
    lines.append("## Manifest（机器可读）")
    lines.append("")
    lines.append("```json")
    lines.append(_json.dumps(manifest, ensure_ascii=False, indent=2))
    lines.append("```")

    text = "\n".join(lines)
    if format == "zip":
        # F088：ZIP 导出（快照纳入 + manifest sha256 + 成员路径白名单）。
        from pathlib import Path

        from lumirss.config import LumiSettings
        from lumirss.research_pack_zip import ResearchPackZipBuilder

        asset_root = Path(LumiSettings().data_dir) / "library" / "assets"
        builder = ResearchPackZipBuilder(request.app.state.db, asset_root)
        zip_bytes, manifest = await builder.build_zip(
            markdown=text,
            entry_count=len(members),
            missing_count=missing,
            include_snapshots=getattr(payload, "includeSnapshots", None) or [],
        )
        filename = f"research-pack-{workspace_id}.zip"
        quoted = quote(filename)
        return Response(
            content=zip_bytes,
            media_type="application/zip",
            headers={
                "Content-Disposition": f"attachment; filename=\"{filename}\"; filename*=UTF-8''{quoted}",
                "X-Manifest-Files": str(manifest["fileCount"]),
            },
        )
    filename = f"research-pack-{workspace_id}.md"
    quoted = quote(filename)
    return Response(
        content=text,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=\"{filename}\"; filename*=UTF-8''{quoted}"
        },
    )


# -- N113 分节大纲 -------------------------------------------------------------


def _sections_store(request: Request):
    from lumirss.workspace_sections import WorkspaceSectionStore

    return WorkspaceSectionStore(request.app.state.db, _get_workspace_store(request))


def _section_view(section: dict) -> WorkspaceSectionView:
    return WorkspaceSectionView(
        id=section["id"],
        workspaceId=section["workspaceId"],
        title=section["title"],
        sortIndex=section["sortIndex"],
        createdAt=section["createdAt"],
        items=[
            WorkspaceSectionItem(
                itemRef=i["itemRef"],
                position=i["position"],
                addedAt=i["addedAt"],
                unresolved=i["unresolved"],
            )
            for i in section["items"]
        ],
    )


@router.get(
    "/api/v1/workspaces/{workspace_id}/sections",
    response_model=WorkspaceSectionList,
)
async def list_workspace_sections(
    workspace_id: str, request: Request
) -> WorkspaceSectionList:
    """N113：分节大纲（sort_index 序）。成员引用以 item_ref 引用而非复制；
    同一条目可出现在多个分节；引用已不是工作区成员 → 行保留并诚实标记
    ``unresolved``（绝不静默隐藏，N113 契约）。"""
    sections = await _sections_store(request).list_sections(workspace_id)
    return WorkspaceSectionList(items=[_section_view(s) for s in sections])


@router.post(
    "/api/v1/workspaces/{workspace_id}/sections",
    response_model=WorkspaceSectionView,
    status_code=201,
)
async def create_workspace_section(
    workspace_id: str, payload: WorkspaceSectionCreate, request: Request
) -> WorkspaceSectionView:
    section = await _sections_store(request).create_section(
        workspace_id, payload.title
    )
    return _section_view(section)


@router.patch(
    "/api/v1/workspaces/{workspace_id}/sections/{section_id}",
    response_model=WorkspaceSectionView,
)
async def rename_workspace_section(
    workspace_id: str, section_id: str, payload: WorkspaceSectionPatch, request: Request
) -> WorkspaceSectionView:
    section = await _sections_store(request).rename_section(
        workspace_id, section_id, payload.title
    )
    return _section_view(section)


@router.delete(
    "/api/v1/workspaces/{workspace_id}/sections/{section_id}", status_code=204
)
async def delete_workspace_section(
    workspace_id: str, section_id: str, request: Request
) -> Response:
    deleted = await _sections_store(request).delete_section(workspace_id, section_id)
    if not deleted:
        from lumirss.workspace_sections import SectionNotFound

        raise SectionNotFound(section_id)
    return Response(status_code=204)


@router.put(
    "/api/v1/workspaces/{workspace_id}/sections/order",
    response_model=WorkspaceSectionList,
)
async def reorder_workspace_sections(
    workspace_id: str, payload: WorkspaceSectionOrderPut, request: Request
) -> WorkspaceSectionList:
    """N113：分节顺序持久化（PUT 全量 1..N；真实变化 bump revision）。"""
    store = _sections_store(request)
    await store.reorder_sections(workspace_id, payload.sectionIds)
    sections = await store.list_sections(workspace_id)
    return WorkspaceSectionList(items=[_section_view(s) for s in sections])


@router.post(
    "/api/v1/workspaces/{workspace_id}/sections/{section_id}/items",
    response_model=WorkspaceSectionItem,
    status_code=201,
)
async def add_workspace_section_item(
    workspace_id: str,
    section_id: str,
    payload: WorkspaceSectionItemAddRequest,
    request: Request,
) -> WorkspaceSectionItem:
    """把一个工作区成员引用进分节（幂等；同一 ref 可进入多个分节——
    引用而非复制，ADR 0004）。非成员 → 404。"""
    item = await _sections_store(request).add_item(
        workspace_id, section_id, payload.itemRef
    )
    return WorkspaceSectionItem(
        itemRef=item["itemRef"],
        position=item["position"],
        addedAt=item["addedAt"],
        unresolved=False,
    )


@router.delete(
    "/api/v1/workspaces/{workspace_id}/sections/{section_id}/items/{item_ref}",
    status_code=204,
)
async def remove_workspace_section_item(
    workspace_id: str, section_id: str, item_ref: str, request: Request
) -> Response:
    """从分节移除一个引用（只拆引用，绝不删除工作区成员本身）。"""
    removed = await _sections_store(request).remove_item(
        workspace_id, section_id, item_ref
    )
    if not removed:
        from lumirss.workspace_sections import SectionItemNotFound

        raise SectionItemNotFound(item_ref)
    return Response(status_code=204)


@router.put(
    "/api/v1/workspaces/{workspace_id}/sections/{section_id}/items/order",
    response_model=WorkspaceSectionList,
)
async def reorder_workspace_section_items(
    workspace_id: str,
    section_id: str,
    payload: WorkspaceSectionItemsOrderPut,
    request: Request,
) -> WorkspaceSectionList:
    """N113：节内条目顺序持久化（PUT 全量 1..N）。"""
    store = _sections_store(request)
    await store.reorder_items(workspace_id, section_id, payload.itemRefs)
    sections = await store.list_sections(workspace_id)
    return WorkspaceSectionList(items=[_section_view(s) for s in sections])


# -- N114 汇编预览 -------------------------------------------------------------


def _citation_for(view: ResolvedItem) -> str:
    """引文链接：rss → /reader?entry=<entryRef>（应用内阅读路由）；
    library → 有安全外链用外链，否则 /library?item=<uuid>（诚实占位）。"""
    if view.ref.startswith("rss:"):
        entry_ref = view.payload.get("entryRef") or view.ref.removeprefix("rss:")
        return f"/reader?entry={entry_ref}"
    url = view.url or ""
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return f"/library?item={view.ref.removeprefix('library:')}"


async def _compile_notes(
    request: Request,
    workspace_id: str,
    resolved: dict[str, ResolvedItem],
) -> dict[str, str]:
    """条目自有笔记（诚实、有界）：
    - library: 引用 → 库条目自带的 note 字段（研究包同一口径）；
    - 全部引用 → 本工作区 lumi_notes 标题精确匹配（lumi_notes 以
      workspace_id 归属工作区，与条目的唯一自然链接是标题）。
    绝不虚构：匹配不到就没有 note。"""
    notes: dict[str, str] = {}
    library = _get_library_store(request)
    for ref in resolved:
        if not ref.startswith("library:"):
            continue
        try:
            item = await library.get_library_item(ref.removeprefix("library:"))
        except Exception:  # noqa: BLE001 — 笔记增强失败不阻断汇编
            item = None
        if item is not None and getattr(item, "note", None):
            notes[ref] = str(item.note)
    rows = await request.app.state.db.fetch_all(
        "SELECT title, content_md FROM lumi_notes WHERE workspace_id = ? AND deleted_at IS NULL ORDER BY updated_at DESC LIMIT 100",
        (workspace_id,),
    )
    by_title: dict[str, str] = {}
    for row in rows:
        title = str(row["title"]).strip()
        first_line = str(row["content_md"] or "").strip().splitlines()
        if title and title not in by_title:
            by_title[title] = (first_line[0] if first_line else "")[:300]
    for ref, view in resolved.items():
        if ref in notes:
            continue
        match = by_title.get(view.title.strip())
        if match:
            notes[ref] = match
    return notes


async def _compile_workspace_internal(
    workspace_id: str, payload: CompileRequest, request: Request
) -> tuple[CompileResponse, dict[str, ResolvedItem], Any]:
    """N114 汇编草稿构建（compile / markdown / N116 分享包共用）。

    返回 (draft, resolved_by_ref, workspace_summary)：分享包需要解析
    视图做来源标注，草稿本体不含 source/datetime 字段。"""
    store = _get_workspace_store(request)
    summary = await store.get_workspace(workspace_id)
    if summary is None:
        raise WorkspaceNotFound(workspace_id)
    section_store = _sections_store(request)
    sections = await section_store.sections_for_compile(
        workspace_id, payload.sectionIds
    )
    flat = not any(s["items"] for s in sections)
    if flat:
        # 无大纲 → 平铺成员（compile 仍可用；单隐式节，标题 = 工作区名）。
        members = await store.list_items(workspace_id, limit=500)
        outline = [
            {
                "id": None,
                "title": summary.name,
                "items": [
                    {
                        "itemRef": m.item_ref,
                        "position": m.position,
                        "addedAt": m.added_at,
                        "unresolved": False,
                    }
                    for m in members
                ],
            }
        ]
    else:
        outline = sections

    # 去重解析（同一 ref 多节引用只解析一次）。
    all_refs: list[str] = []
    seen: set[str] = set()
    for section in outline:
        for item in section["items"]:
            if item["itemRef"] not in seen:
                seen.add(item["itemRef"])
                all_refs.append(item["itemRef"])
    registry = _get_source_registry(request)
    resolved_list = list(
        await asyncio.gather(
            *(_resolve_bounded(registry, ref) for ref in all_refs)
        )
    )
    resolved = {v.ref: v for v in resolved_list}
    notes = await _compile_notes(request, workspace_id, resolved)

    draft_sections: list[CompileSection] = []
    excluded: list[CompileExcluded] = []
    included = 0
    for section in outline:
        items: list[CompileItem] = []
        for item in section["items"]:
            ref = item["itemRef"]
            view = resolved.get(ref)
            if view is None or view.stale:
                reason = (
                    view.staleReason if view is not None else "resolve_failed"
                ) or "来源不可用"
                excluded.append(CompileExcluded(itemRef=ref, reason=reason))
                continue
            included += 1
            items.append(
                CompileItem(
                    itemRef=ref,
                    title=view.title,
                    excerpt=(view.excerpt or "")[:200],
                    citation=_citation_for(view),
                    note=notes.get(ref),
                )
            )
        draft_sections.append(
            CompileSection(
                sectionId=section["id"], title=section["title"], items=items
            )
        )
    draft = CompileResponse(
        workspaceId=workspace_id,
        workspaceName=summary.name,
        generatedAt=utc_now(),
        sections=draft_sections,
        includedCount=included,
        excludedMissing=len(excluded),
        excluded=excluded,
    )
    return draft, resolved, summary


@router.post(
    "/api/v1/workspaces/{workspace_id}/compile",
    response_model=CompileResponse,
)
async def compile_workspace(
    workspace_id: str, payload: CompileRequest, request: Request
) -> CompileResponse:
    """N114：按大纲汇编草稿（纯预览，绝不落库）。

    - 每个分节：标题 + 成员（标题 / 摘录 ≤200 / 引文链接 / 自有笔记）；
    - 无分节（或全部为空大纲）→ 单一隐式节（工作区名，平铺全部成员）；
    - 已消失 / 未授权的引用诚实排除并计数（excluded + excludedMissing），
      绝不冒充内容。"""
    draft, _resolved, _summary = await _compile_workspace_internal(
        workspace_id, payload, request
    )
    return draft


def _compile_markdown(draft: CompileResponse) -> str:
    """CompileResponse → Markdown 文本（引文链接逐条保留）。"""
    lines = [
        f"# {draft.workspaceName}（汇编草稿）",
        "",
        f"- 生成时间：{draft.generatedAt}",
        f"- 收录 {draft.includedCount} 条 / 排除 {draft.excludedMissing} 条（缺失或未授权）",
        "",
    ]
    for section in draft.sections:
        lines.append(f"## {section.title}")
        lines.append("")
        if not section.items:
            lines.append("（本节暂无可汇编条目）")
            lines.append("")
            continue
        for item in section.items:
            lines.append(f"### {item.title}")
            lines.append("")
            lines.append(f"- 引文：{item.citation}")
            if item.excerpt:
                lines.append(f"- 摘录：{item.excerpt}")
            if item.note:
                lines.append(f"- 笔记：{item.note}")
            lines.append("")
    if draft.excluded:
        lines.append("## 未收录（诚实排除）")
        lines.append("")
        for item in draft.excluded:
            lines.append(f"- `{item.itemRef}`：{item.reason}")
        lines.append("")
    return "\n".join(lines)


@router.post("/api/v1/workspaces/{workspace_id}/compile/markdown")
async def compile_workspace_markdown(
    workspace_id: str, payload: CompileRequest, request: Request
) -> Response:
    """N114：汇编草稿的 Markdown 文本版（同样纯预览不落库）。"""
    draft = await compile_workspace(workspace_id, payload, request)
    text = _compile_markdown(draft)
    return Response(
        content=text,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'inline; filename="compile-{workspace_id}.md"'},
    )


@router.post("/api/v1/workspaces/{workspace_id}/share-package")
async def export_share_package(
    workspace_id: str, payload: SharePackageRequest, request: Request
) -> Response:
    """N116：汇编只读分享包（自包含静态 HTML 下载）。

    - 与 N114 同一大纲/解析口径；私人笔记绝不进入（includeNotes
      固定 false——传 true 是 422 契约错误，不是静默忽略）；
    - 引文链接策略：绝对 http(s) → 真链接；应用内路由 → 仅当配置
      ``LUMIRSS_PUBLIC_URL`` 时拼公开绝对链接，否则纯文本诚实省略；
    - 每条附来源标注，文末隐私提示；包内绝无 cookie/token/凭据/
      绝对本地路径（测试断言）。"""
    from urllib.parse import quote

    from lumirss.config import LumiSettings
    from lumirss.workspace_share import render_share_package_html

    draft, resolved, _summary = await _compile_workspace_internal(
        workspace_id,
        CompileRequest(sectionIds=payload.sectionIds),
        request,
    )
    html_text = render_share_package_html(
        draft,
        resolved,
        public_base_url=LumiSettings().LUMIRSS_PUBLIC_URL,
    )
    filename = f"share-package-{workspace_id}.html"
    quoted = quote(filename)
    return Response(
        content=html_text,
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename=\"{filename}\"; filename*=UTF-8''{quoted}"
        },
    )


# -- N120 清理预演 -------------------------------------------------------------


def _cleanup_store(request: Request):
    from lumirss.workspace_cleanup import WorkspaceCleanupStore

    return WorkspaceCleanupStore(request.app.state.db, _get_workspace_store(request))


async def _verify_rss_ref(request: Request, item_ref: str) -> str:
    """核实一个 rss: 成员是否真的消失（「gone」才可清理）。

    投影命中 → ok；投影未命中且上游适配器可用 → 问一次上游（404 = gone；
    其他异常/超时 = unverifiable）；上游不可用 = unverifiable（FreshRSS
    未配置绝不等于条目消失——清理绝不建议在故障时删数据）。"""
    from lumirss.entryref import InvalidEntryReference, decode_entry_ref
    from lumirss.search_store import SearchStore

    entry_ref = item_ref.removeprefix("rss:")
    row = await SearchStore(request.app.state.db).entry_row_by_ref(item_ref)
    if row is not None:
        return "ok"
    adapter = request.app.state.freshrss_adapter
    if adapter is None:
        return "unverifiable"
    try:
        item_id = decode_entry_ref(entry_ref)
    except InvalidEntryReference:
        return "gone"
    from lumirss.adapters.freshrss import EntryNotFound

    try:
        await asyncio.wait_for(adapter.get_entry(item_id), timeout=15.0)
    except (EntryNotFound, InvalidEntryReference):
        return "gone"
    except Exception:  # noqa: BLE001 — 上游故障 ≠ 内容消失
        return "unverifiable"
    return "ok"


async def _cleanup_unresolved(request: Request, members: list):
    """成员 ref 核实分类（N120 预演/应用的共同输入）。"""
    registry = _get_source_registry(request)
    rss_refs = [m.item_ref for m in members if m.item_ref.startswith("rss:")]
    library_refs = [m.item_ref for m in members if m.item_ref.startswith("library:")]
    gone: list[str] = []
    unverifiable: list[str] = []
    for ref, verdict in zip(
        rss_refs,
        await asyncio.gather(*(_verify_rss_ref(request, ref) for ref in rss_refs)),
        strict=True,
    ):
        if verdict == "gone":
            gone.append(ref)
        elif verdict == "unverifiable":
            unverifiable.append(ref)
    protected: list[str] = []
    for ref, view in zip(
        library_refs,
        await asyncio.gather(*(_resolve_bounded(registry, ref) for ref in library_refs)),
        strict=True,
    ):
        if view.stale:
            # 库对象受保护：解析不到也绝不进可执行类目。
            protected.append(ref)
    return gone, unverifiable, protected


@router.get(
    "/api/v1/workspaces/{workspace_id}/cleanup-preview",
    response_model=WorkspaceCleanupPreviewResponse,
)
async def workspace_cleanup_preview(
    workspace_id: str, request: Request
) -> WorkspaceCleanupPreviewResponse:
    """N120：只读清理预演——每项带原因，绝不静默；只报告不删除。"""
    store = _get_workspace_store(request)
    summary = await store.get_workspace(workspace_id)
    if summary is None:
        raise WorkspaceNotFound(workspace_id)
    members = await store.list_items_full(workspace_id)
    gone, unverifiable, protected = await _cleanup_unresolved(request, members)
    cleanup = _cleanup_store(request)
    empty_groups = await cleanup.empty_groups(workspace_id)
    orphans = await cleanup.orphan_section_refs(workspace_id)
    conflicts = await cleanup.pinned_group_conflicts(workspace_id)
    categories = [
        WorkspaceCleanupCategory(
            category="unresolved_refs",
            items=[
                {"itemRef": ref, "reason": "来源条目已不存在（feed/entry 已消失）。"}
                for ref in gone
            ],
        ),
        WorkspaceCleanupCategory(
            category="protected_library_refs",
            items=[
                {
                    "itemRef": ref,
                    "reason": "库对象引用解析不到（已删除/回收站）——库对象受保护，不参与清理。",
                }
                for ref in protected
            ],
        ),
        WorkspaceCleanupCategory(
            category="unverifiable_refs",
            items=[
                {
                    "itemRef": ref,
                    "reason": "当前无法核实（FreshRSS 未配置或查询失败）——绝不建议删除。",
                }
                for ref in unverifiable
            ],
        ),
        WorkspaceCleanupCategory(category="empty_groups", items=empty_groups),
        WorkspaceCleanupCategory(category="orphan_section_refs", items=orphans),
        WorkspaceCleanupCategory(category="pinned_group_conflicts", items=conflicts),
    ]
    from lumirss.workspace_cleanup import (
        ACTIONABLE_CATEGORIES,
        REPORT_ONLY_CATEGORIES,
    )

    return WorkspaceCleanupPreviewResponse(
        workspaceId=workspace_id,
        categories=categories,
        actionable=list(ACTIONABLE_CATEGORIES),
        reportOnly=list(REPORT_ONLY_CATEGORIES),
    )


@router.post(
    "/api/v1/workspaces/{workspace_id}/cleanup",
    response_model=WorkspaceCleanupApplyResult,
)
async def workspace_cleanup_apply(
    workspace_id: str, payload: WorkspaceCleanupApplyRequest, request: Request
) -> WorkspaceCleanupApplyResult:
    """N120：应用选中的清理类目（快照先行，可撤销）。

    只删 Lumi 自有元数据行（stale rss 成员行 / 空组名 / 悬空分节引用）；
    绝不触碰 FreshRSS 数据；library: 域引用受保护（即使解析不到）。"""
    store = _get_workspace_store(request)
    summary = await store.get_workspace(workspace_id)
    if summary is None:
        raise WorkspaceNotFound(workspace_id)
    members = await store.list_items_full(workspace_id)
    gone, _unverifiable, _protected = await _cleanup_unresolved(request, members)
    result = await _cleanup_store(request).apply(
        workspace_id, payload.categories, unresolved_refs=gone
    )
    return WorkspaceCleanupApplyResult(logId=result["logId"], removed=result["removed"])


@router.get(
    "/api/v1/workspaces/{workspace_id}/cleanup-logs",
    response_model=WorkspaceCleanupLogList,
)
async def workspace_cleanup_logs(
    workspace_id: str, request: Request
) -> WorkspaceCleanupLogList:
    """清理日志（新→旧，上限 5；供撤销入口选择）。"""
    store = _get_workspace_store(request)
    if await store.get_workspace(workspace_id) is None:
        raise WorkspaceNotFound(workspace_id)
    logs = await _cleanup_store(request).list_logs(workspace_id)
    return WorkspaceCleanupLogList(items=logs)


@router.post(
    "/api/v1/workspaces/{workspace_id}/cleanup/undo",
    response_model=WorkspaceCleanupUndoResult,
)
async def workspace_cleanup_undo(
    workspace_id: str, payload: WorkspaceCleanupUndoRequest, request: Request
) -> WorkspaceCleanupUndoResult:
    """N120：按日志恢复被移除的行（缺省 = 最近一条；重复 undo 幂等）。"""
    store = _get_workspace_store(request)
    if await store.get_workspace(workspace_id) is None:
        raise WorkspaceNotFound(workspace_id)
    result = await _cleanup_store(request).undo(workspace_id, payload.logId)
    return WorkspaceCleanupUndoResult(
        logId=result["logId"],
        restoredRefs=result["restoredRefs"],
        restoredSectionRefs=result["restoredSectionRefs"],
    )


@router.post(
    "/api/v1/workspaces/read-later/items/{item_ref}/snooze",
    response_model=ReadLaterSnoozeResult,
)
async def snooze_read_later_item(
    item_ref: str, payload: ReadLaterSnoozeRequest, request: Request
) -> ReadLaterSnoozeResult:
    """F19：延后一个稍后读项目到指定时刻（ISO；到期自动回到时间线）。

    只影响时间线可见性：行保留、成员关系与已读/收藏状态不变。
    until 必须是未来时刻（防止「延后到过去」造成假消失）。
    入库前归一化为 UTC「Z」串（Gate A P2：与 utc_now() 的比较是字典序，
    非 UTC 偏移格式会造成提前/滞后回归）。"""
    from datetime import datetime

    try:
        until_dt = datetime.fromisoformat(payload.until.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WorkspaceInvalid("until must be an ISO timestamp.") from exc
    if until_dt.tzinfo is None:
        until_dt = until_dt.replace(tzinfo=UTC)
    now = datetime.now(UTC)
    if until_dt <= now:
        raise WorkspaceInvalid("until must be in the future.")
    until_canonical = until_dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    store: WorkspaceStore = _get_workspace_store(request)
    ok = await store.snooze_item(RESERVED_WORKSPACE_ID, item_ref, until_canonical)
    if not ok:
        raise WorkspaceNotFound(f"read-later item {item_ref}")
    return ReadLaterSnoozeResult(itemRef=item_ref, snoozedUntil=until_canonical)


@router.delete(
    "/api/v1/workspaces/read-later/items/{item_ref}/snooze",
    status_code=204,
)
async def unsnooze_read_later_item(item_ref: str, request: Request) -> Response:
    """F19：取消延后——项目立即回到时间线。"""
    store: WorkspaceStore = _get_workspace_store(request)
    ok = await store.snooze_item(RESERVED_WORKSPACE_ID, item_ref, None)
    if not ok:
        raise WorkspaceNotFound(f"read-later item {item_ref}")
    return Response(status_code=204)


@router.get(
    "/api/v1/workspaces/read-later/snoozed",
    response_model=ReadLaterSnoozedList,
)
async def list_snoozed_read_later(request: Request) -> ReadLaterSnoozedList:
    """当前处于延后状态的项目（供「已延后」视图展示）。"""
    store: WorkspaceStore = _get_workspace_store(request)
    rows = await store.list_snoozed(RESERVED_WORKSPACE_ID)
    return ReadLaterSnoozedList(
        items=[
            ReadLaterSnoozeResult(itemRef=ref, snoozedUntil=until) for ref, until in rows
        ]
    )


@router.get(
    "/api/v1/workspaces/read-later/timeline",
    response_model=ReadLaterTimelineResponse,
)
async def read_later_timeline(
    request: Request,
    limit: int = 25,
    cursor: str | None = None,
    order: str = "newest",
) -> ReadLaterTimelineResponse:
    """Server-driven read-later timeline (P0-01): keyset-paged over the
    reserved workspace's members by add time. ``order`` is ``newest``
    (default) or ``oldest`` (pool #14); cursors are bound to the order
    they were issued under. Cards come from the derived projection; a
    projection miss falls back to the FreshRSS adapter; a ref that
    resolves nowhere stays visible as ``stale`` instead of vanishing
    (ADR 0004)."""
    if limit < 1 or limit > 100:
        raise WorkspaceInvalid("limit must be between 1 and 100.")
    store: WorkspaceStore = _get_workspace_store(request)
    members, next_cursor = await store.list_items_desc(
        RESERVED_WORKSPACE_ID, cursor=cursor, limit=limit, order=order
    )
    # Q-P2-05: cards resolve concurrently (same gather pattern as
    # workspace_contents below) — the serial comprehension paid one
    # projection query or FreshRSS round-trip per card, back to back.
    # return_exceptions + stale-card mapping: one broken ref must not
    # 500 the whole timeline (same contract as the favorites view).
    views = await asyncio.gather(
        *(_read_later_card(request, member) for member in members),
        return_exceptions=True,
    )
    items = [
        view
        if not isinstance(view, BaseException)
        else ReadLaterItem(
            itemRef=member.item_ref, addedAt=member.added_at, stale=True
        )
        for view, member in zip(views, members, strict=True)
    ]
    return ReadLaterTimelineResponse(items=items, nextCursor=next_cursor)


async def _read_later_card(request: Request, member: WorkspaceItem) -> ReadLaterItem:
    from lumirss.deps import _get_source_registry
    from lumirss.entryref import InvalidEntryReference, decode_entry_ref
    from lumirss.models import SearchItem

    item_ref = member.item_ref
    stale_card = ReadLaterItem(
        itemRef=item_ref, addedAt=member.added_at, stale=True, entry=None
    )
    if not item_ref.startswith("rss:"):
        # Library refs (inbox api_item, clips, …) are first-class members:
        # render the unified registry view instead of a fake-stale row
        # (Q-P1-05 — the inbox save path legitimately adds these).
        if item_ref.startswith("library:"):
            registry = _get_source_registry(request)
            # Shared resolve cap + per-item deadline (pool #44); failures
            # degrade to this row's stale card, not a page-wide 500.
            view = await _resolve_bounded(registry, item_ref)
            if view.stale:
                return stale_card
            return ReadLaterItem(
                itemRef=item_ref,
                addedAt=member.added_at,
                stale=False,
                resolved=ResolvedItem(**view.to_dict()),
            )
        return stale_card
    try:
        item_id = decode_entry_ref(item_ref[len("rss:") :])
    except InvalidEntryReference:
        return stale_card
    from lumirss.search_store import SearchStore

    row = await SearchStore(request.app.state.db).entry_row_by_ref(item_ref)
    if row is not None:
        return ReadLaterItem(
            itemRef=item_ref,
            addedAt=member.added_at,
            entry=SearchItem(
                entryRef=str(row["entry_ref"]),
                title=str(row["title"]),
                feedTitle=str(row["feed_title"]),
                feedUrl=str(row["feed_url"]),
                author=row["author"] or None,
                url=row["url"] or None,
                publishedAt=str(row["published_at"]),
                read=bool(row["read"]),
                starred=bool(row["starred"]),
                snippet=(row["content_text"] or "")[:160],
                matchedFields=[],
            ),
        )
    # Projection miss: ask FreshRSS once before declaring the ref stale.
    adapter = request.app.state.freshrss_adapter
    if adapter is not None:
        from lumirss.adapters.freshrss import EntryNotFound

        try:
            detail = await adapter.get_entry(item_id)
        except (EntryNotFound, InvalidEntryReference):
            return stale_card
        except Exception:  # noqa: BLE001 — upstream failure ≠ stale content
            return ReadLaterItem(
                itemRef=item_ref,
                addedAt=member.added_at,
                stale=True,
                entry=None,
            )
        return ReadLaterItem(
            itemRef=item_ref,
            addedAt=member.added_at,
            entry=SearchItem(
                entryRef=item_ref,
                title=detail.title,
                feedTitle=detail.feedTitle,
                feedUrl=detail.feedUrl or "",
                author=detail.author,
                url=detail.url,
                publishedAt=detail.publishedAt or "",
                read=detail.read,
                starred=detail.starred,
                snippet=(detail.contentText or "")[:160],
                matchedFields=[],
            ),
        )
    return ReadLaterItem(itemRef=item_ref, addedAt=member.added_at, stale=True, entry=None)


@router.post("/api/v1/resolve", response_model=WorkspaceItemsResolvedResponse)
async def resolve_refs(payload: ResolveRequest, request: Request) -> WorkspaceItemsResolvedResponse:
    """Resolve one batch of ItemRefs to unified ViewModels (≤100 refs)."""
    if not payload.refs or len(payload.refs) > _MAX_RESOLVE_REFS:
        raise WorkspaceInvalid(
            f"refs must contain between 1 and {_MAX_RESOLVE_REFS} items."
        )
    registry = _get_source_registry(request)

    resolved = list(
        await asyncio.gather(
            *(_resolve_bounded(registry, ref) for ref in payload.refs)
        )
    )
    return WorkspaceItemsResolvedResponse(items=_resolved_models(resolved))
