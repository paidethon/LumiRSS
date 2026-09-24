"""Workspace routes (phase2 M1) — ref collections + unified resolve.

Workspaces hold typed ItemRefs only; resolving them to unified ViewModels
goes through the Source Registry (:mod:`lumirss.sources`). The reserved
``read-later`` workspace cannot be deleted or renamed.
"""

import asyncio
import logging
from datetime import UTC

from fastapi import APIRouter, Request, Response

from lumirss.itemref import InvalidItemRef
from lumirss.models import (
    ReadLaterItem,
    ReadLaterSnoozedList,
    ReadLaterSnoozeRequest,
    ReadLaterSnoozeResult,
    ReadLaterTimelineResponse,
    ResearchPackPreviewRequest,
    ResearchPackRequest,
    ResolvedItem,
    ResolveRequest,
    Workspace,
    WorkspaceCreate,
    WorkspaceGroupOrderPut,
    WorkspaceGroupsResponse,
    WorkspaceItem,
    WorkspaceItemAddRequest,
    WorkspaceItemGroupMoveRequest,
    WorkspaceItemPinRequest,
    WorkspaceItemsResolvedResponse,
    WorkspaceItemsResponse,
    WorkspaceListResponse,
    WorkspacePatch,
    WorkspaceReorderRequest,
    WorkspaceResumePointer,
    WorkspaceResumePutRequest,
    WorkspaceResumeResponse,
    WorkspaceSnapshot,
    WorkspaceSnapshotCreate,
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
    return _item_model(item)


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
