"""W5 library routes — F081 批量元数据编辑 / F082 重复合并 / F087 失效检查.

全部为 Lumi 自有元数据操作：FreshRSS 条目与 Obsidian Vault 零接触。
"""

from fastapi import APIRouter, Request

from lumirss.bookmarks_check import LinkCheckService
from lumirss.library_batch_edit import BatchEditService
from lumirss.models import (
    BatchEditApplyItem,
    BatchEditApplyRequest,
    BatchEditApplyResponse,
    BatchEditPreviewItem,
    BatchEditPreviewRequest,
    BatchEditPreviewResponse,
    BookmarkCheckItem,
    BookmarkCheckRequest,
    BookmarkCheckResponse,
    MergeFieldCompare,
    MergePreviewRequest,
    MergePreviewResponse,
    MergeRequest,
    MergeResult,
)

from ..deps import _get_tag_store, _get_workspace_store

router = APIRouter()


def _batch_service(request: Request) -> BatchEditService:
    return BatchEditService(
        request.app.state.db,
        _get_tag_store(request),
        _get_workspace_store(request),
    )


@router.post(
    "/api/v1/library/batch-edit/preview",
    response_model=BatchEditPreviewResponse,
)
async def batch_edit_preview(
    payload: BatchEditPreviewRequest, request: Request
) -> BatchEditPreviewResponse:
    """逐项 before/after（预览零写入；失效 ref 以 before=None 呈现）。"""
    service = _batch_service(request)
    items = await service.preview(
        payload.refs,
        title_suffix=payload.patch.titleSuffix,
        tags_add=payload.patch.tagsAdd,
        tags_remove=payload.patch.tagsRemove,
        workspace_id=payload.patch.workspaceId,
    )
    return BatchEditPreviewResponse(
        items=[
            BatchEditPreviewItem(
                ref=item["ref"],
                before=item["before"],
                after=item["after"],
            )
            for item in items
        ]
    )


@router.post(
    "/api/v1/library/batch-edit",
    response_model=BatchEditApplyResponse,
)
async def batch_edit_apply(
    payload: BatchEditApplyRequest, request: Request
) -> BatchEditApplyResponse:
    """逐条应用（部分失败可重试：失败项逐项汇报 error）。"""
    service = _batch_service(request)
    results = await service.apply(
        payload.refs,
        title_suffix=payload.patch.titleSuffix,
        tags_add=payload.patch.tagsAdd,
        tags_remove=payload.patch.tagsRemove,
        workspace_id=payload.patch.workspaceId,
    )
    items = [BatchEditApplyItem(**result) for result in results]
    return BatchEditApplyResponse(
        items=items,
        applied=sum(1 for i in items if i.ok),
        failed=sum(1 for i in items if not i.ok),
    )


def _merge_service(request: Request):
    from lumirss.library_merge import LibraryMergeService

    return LibraryMergeService(request.app.state.db, _get_tag_store(request))


@router.post(
    "/api/v1/library/merge/preview",
    response_model=MergePreviewResponse,
)
async def merge_preview(
    payload: MergePreviewRequest, request: Request
) -> MergePreviewResponse:
    state = await _merge_service(request).preview(
        payload.primaryRef, payload.duplicateRef
    )
    return MergePreviewResponse(
        primaryRef=state["primaryRef"],
        duplicateRef=state["duplicateRef"],
        fields=[MergeFieldCompare(**field) for field in state["fields"]],
        annotationCount=state["annotationCount"],
        assetUuids=state["assetUuids"],
    )


@router.post("/api/v1/library/merge", response_model=MergeResult)
async def merge_apply(payload: MergeRequest, request: Request) -> MergeResult:
    result = await _merge_service(request).merge(
        payload.primaryRef,
        payload.duplicateRef,
        title_policy=payload.policy.title,
        note_policy=payload.policy.note,
    )
    return MergeResult(**result)


@router.post(
    "/api/v1/library/bookmarks/check-links",
    response_model=BookmarkCheckResponse,
)
async def check_bookmark_links(
    payload: BookmarkCheckRequest, request: Request
) -> BookmarkCheckResponse:
    """F087：并发≤4 探测书签 URL；绝不改写书签（redirect 只报告 finalUrl）。

    仅 url 型书签可探测；rss 引用与未知 ref 原样返回 network_error
    （ref 不变、URL 不动——「检查」是纯读操作）。"""
    from lumirss.itemref import LIBRARY_DOMAIN
    from lumirss.util import utc_now

    from ..deps import _get_library_store

    library = _get_library_store(request)
    targets: dict[str, str | None] = {}
    for ref in dict.fromkeys(payload.refs):
        view = None
        if ref.startswith(f"{LIBRARY_DOMAIN}:"):
            view = await library.get_bookmark(ref.removeprefix(f"{LIBRARY_DOMAIN}:"))
        targets[ref] = view.url if view is not None and view.url else None
    service = LinkCheckService()
    probe_urls = [u for u in targets.values() if u]
    probed_list = await service.check_many(probe_urls) if probe_urls else []
    probed = {item["ref"]: item for item in probed_list}
    items = []
    for ref, url in targets.items():
        if url is None:
            items.append(
                BookmarkCheckItem(
                    ref=ref,
                    status="network_error",
                    checkedAt=utc_now(),
                    error="no_url",
                )
            )
            continue
        result = probed.get(url) or {}
        items.append(
            BookmarkCheckItem(
                ref=ref,
                status=str(result.get("status") or "network_error"),
                httpStatus=result.get("httpStatus"),
                finalUrl=result.get("finalUrl"),
                checkedAt=str(result.get("checkedAt") or utc_now()),
                error=result.get("error"),
            )
        )
    return BookmarkCheckResponse(items=items)
