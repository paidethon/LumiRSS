"""Opml routes (moved verbatim from main.py)."""



import contextlib
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse

from lumirss.deps import _get_control_adapter
from lumirss.import_batch_store import ImportBatchStore
from lumirss.models import (
    OpmlImportLogList,
    OpmlImportPreview,
    OpmlImportResult,
    OpmlTreeApplyResult,
    OpmlTreePlan,
    OpmlUndoResult,
)
from lumirss.opml import (
    MAX_OPML_BYTES,
    OpmlService,
    OpmlTooLarge,
)
from lumirss.opml_import_log import OpmlImportLogStore

router = APIRouter()


async def _read_bounded_opml(request: Request) -> bytes:
    """Read the raw OPML upload with a hard size cap (never buffers more
    than MAX_OPML_BYTES + one chunk before rejecting)."""
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_OPML_BYTES:
            raise OpmlTooLarge("OPML file exceeds the 2 MiB limit.")
        chunks.append(chunk)
    return b"".join(chunks)


@router.get("/api/v1/opml/export")
async def opml_export(
    request: Request,
    subscription_refs: Annotated[list[str] | None, Query()] = None,
    category_ids: Annotated[list[str] | None, Query()] = None,
) -> Response:
    """Download the FreshRSS OPML export (subscriptions + categories only).

    Proxied through the BFF so the browser never learns FreshRSS
    credentials. The document contains no settings dump, no API keys, no
    read history and no favorites — only the subscription outline tree
    FreshRSS itself produces.

    F003：可选 subscription_refs / category_ids（可重复的查询参数）限定
    导出集合——按选中集合在 BFF 侧重建 OPML（保留分类结构，XML 转义）；
    两个参数都缺省 = 全库导出，保持既有上游透传行为完全向后兼容。
    非法/不存在的 subscriptionRef → 400 opml_invalid。
    """
    control = _get_control_adapter(request)
    if subscription_refs is None and category_ids is None:
        xml = await control.export_opml()
    else:
        service = OpmlService(control)
        xml = await service.export_selected(subscription_refs, category_ids)
    return Response(
        content=xml,
        media_type="text/x-opml; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="LumiRSS-subscriptions.opml"'
        },
    )


@router.post("/api/v1/opml/import/preview", response_model=OpmlImportPreview)
async def opml_import_preview(request: Request) -> dict[str, object]:
    """Parse an uploaded OPML and report what an import WOULD do.

    Strictly non-mutating: bounded read → defusedxml parse → counts
    (new / duplicates / invalid / per-category). Duplicates are only the
    reliably detectable kind: exact feed-URL matches against the current
    FreshRSS subscriptions (plus repeats inside the file). Importing is
    POST /api/v1/opml/import.
    """
    data = await _read_bounded_opml(request)
    service = OpmlService(_get_control_adapter(request))
    return await service.preview(data)


@router.post(
    "/api/v1/opml/import",
    response_model=OpmlImportResult,
    response_model_exclude_none=False,  # uncategorized added feed → null label
)
async def opml_import(
    request: Request,
    selected_indexes: str | None = None,
) -> dict[str, object]:
    """Merge-import an OPML: subscribe each NEW feed, categorize it, report.

    Merge-only — existing subscriptions are reported as duplicates and
    never modified, nothing is unsubscribed or overwritten (destructive
    restore is out of 0013 scope). Per-feed failures (rejected feeds,
    upstream timeouts) are reported honestly in the result; the file is
    re-parsed and the subscription list re-read at import time, so the
    preview is advisory, never a stale contract.

    F002：selected_indexes（查询参数，逗号分隔的逐项预览 index）只导入
    勾选的条目；缺省 = 全部（向后兼容）。格式非法 → 400。未选中/重复/
    不可用的条目进入 skipped，不产生任何写。
    """
    data = await _read_bounded_opml(request)
    service = OpmlService(_get_control_adapter(request))
    selected: set[int] | None
    try:
        selected = service._parse_selected(selected_indexes)
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "type": "invalid_selection",
                    "message": f"selected_indexes 参数非法：{exc}",
                }
            },
        )
    result = await service.import_opml(data, selected)
    # F049：导入批次追踪（计数如实；失败项存 retry_payload 供仅重试失败）。
    try:
        failed_items = result.get("failed") or []
        added_items = result.get("added") or []
        retry_payload = [
            {"url": item.get("feedUrl"), "title": item.get("title")}
            for item in failed_items
            if isinstance(item, dict) and item.get("feedUrl")
        ]
        await ImportBatchStore(request.app.state.db).record(
            kind="opml",
            counts={
                "imported": len(added_items),
                "skipped": len(result.get("skipped") or []),
                "failed": len(failed_items),
            },
            errors=[
                {"url": item.get("feedUrl"), "reason": item.get("error")}
                for item in failed_items
                if isinstance(item, dict)
            ],
            retry_payload=retry_payload,
        )
    except Exception:  # noqa: BLE001 — 批次记录失败不影响导入本身
        pass
    return result




# ---- N018 树对照导入（plan → apply → undo） ---------------------------------


@router.post(
    "/api/v1/opml/import/tree-preview",
    response_model=OpmlTreePlan,
)
async def opml_tree_preview(request: Request) -> dict[str, object]:
    """N018：OPML 分类树对照预览——严格只读。

    解析上传 OPML 的分类结构，对照当前 FreshRSS 分类，产出计划：
    createCategories / reuseCategories / moveFeeds / duplicateFeeds
    （skip|update 策略见 OpmlService._build_tree_plan 的确定性规则）。
    不订阅、不移动、不建类；应用走 tree-apply。"""
    data = await _read_bounded_opml(request)
    service = OpmlService(_get_control_adapter(request))
    return await service.tree_preview(data)


@router.post(
    "/api/v1/opml/import/tree-apply",
    response_model=OpmlTreeApplyResult,
)
async def opml_tree_apply(request: Request) -> dict[str, object]:
    """N018：应用树对照计划（订阅新 feed → 建类/移动随行）。

    以执行时刻的服务器状态为准（预览是建议，不是陈旧契约）。每次
    执行写一行撤销台账（opml_import_log，cap 5），撤销走
    POST /api/v1/opml/import/{id}/undo。"""
    data = await _read_bounded_opml(request)
    service = OpmlService(_get_control_adapter(request), request.app.state.db)
    result = await service.tree_apply(data)
    # F049 复用：树对照执行同样留导入批次计数（成功/跳过/失败）。
    with contextlib.suppress(Exception):
        await ImportBatchStore(request.app.state.db).record(
            kind="opml",
            counts={
                "imported": len(result.get("added") or []),
                "skipped": len(result.get("skipped") or []),
                "failed": len(result.get("failed") or []),
            },
            errors=[
                {"url": item.get("feedUrl"), "reason": item.get("error")}
                for item in result.get("failed", [])
                if isinstance(item, dict)
            ],
            retry_payload=[
                {"url": item.get("feedUrl"), "title": None}
                for item in result.get("failed", [])
                if isinstance(item, dict) and item.get("kind") == "subscribe"
            ],
        )
    return result


@router.post("/api/v1/opml/import/{log_id}/undo", response_model=OpmlUndoResult)
async def opml_import_undo(log_id: int, request: Request) -> dict[str, object]:
    """N018：撤销一次树对照导入（feed 移回原分类）。

    每行至多撤销一次；被移动 feed 的原分类已消失 / feed 已退订时逐项
    如实汇报原因。新建分类无法经 greader API 删除（无该端点，诚实
    边界）——响应 categoriesNotDeleted 如实列出，可在 FreshRSS 原生
    界面清理。"""
    service = OpmlService(_get_control_adapter(request), request.app.state.db)
    return await service.undo_import(log_id)


@router.get("/api/v1/opml/import/log", response_model=OpmlImportLogList)
async def opml_import_log_list(request: Request) -> dict[str, object]:
    """N018：最近撤销台账（≤5 行，新→旧；undoneAt 非 null = 已撤销）。"""
    items = await OpmlImportLogStore(request.app.state.db).list_recent()
    return {"items": items}
