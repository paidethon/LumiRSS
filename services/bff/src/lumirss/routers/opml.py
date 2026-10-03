"""Opml routes (moved verbatim from main.py)."""



import contextlib
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse

from lumirss.deps import StrictId, _get_control_adapter, _get_rsshub_service
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
    parse_opml,
)
from lumirss.opml_import_log import OpmlImportLogStore
from lumirss.rsshub_import_flow import RsshubImportService, strategy_or_none
from lumirss.rsshub_source_mapping import (
    RsshubSourceMappingStore,
)

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
async def opml_import_undo(log_id: StrictId, request: Request) -> dict[str, object]:
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



# ---- R18 RSSHub 优化导入（匹配 / 验证 / 替换 / 映射台账） --------------------


def _parse_approved(approved: str | None) -> set[int] | None:
    """``approved`` 查询参数（逗号分隔预览 index）→ 集合；缺省 = None。
    非法格式 → ValueError（路由层 400）。"""
    if approved is None or approved.strip() == "":
        return None
    approved_set: set[int] = set()
    for chunk in approved.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if not chunk.isdigit():
            raise ValueError(f"invalid index: {chunk!r}")
        approved_set.add(int(chunk))
    return approved_set


def _parse_chosen(chosen: list[str] | None) -> dict[int, str]:
    """``chosen`` 重复查询参数（"index|路由路径"）→ 映射。

    manual 策略的人工指定路由；路径只能是 rsshub-plan 返回过的计划
    内候选（apply 侧强制）。格式非法 → ValueError。"""
    if not chosen:
        return {}
    chosen_map: dict[int, str] = {}
    for item in chosen:
        index_part, sep, path_part = item.partition("|")
        if not sep or not index_part.strip().isdigit() or not path_part.strip():
            raise ValueError(f"invalid chosen item: {item!r}")
        chosen_map[int(index_part.strip())] = path_part.strip()
    return chosen_map


def _rsshub_import_service(request: Request) -> RsshubImportService:
    """R18 导入流：控制适配器（订阅）+ RssHubService（有界验证拉取）。"""
    return RsshubImportService(
        _get_control_adapter(request),
        _get_rsshub_service(request),
        request.app.state.db,
    )


@router.post("/api/v1/opml/import/rsshub-plan")
async def opml_rsshub_plan(request: Request) -> dict[str, object]:
    """R18：OPML → RSSHub 匹配计划（严格只读，零网络零写入）。

    逐条给出决策（autoReplace / manualChoice / needsCredentials /
    needsParams / alreadyRsshub / keepNative / unsupported）与带置信
    度依据的候选列表。规则数据 = vendored pinned-image 快照
    （rsshub_routes.generated.json），结构化匹配，不执行任何上游
    代码。候选的实际可用性在 apply 阶段验证（拉取 200+feed）；
    RSSHub 未配置时 rsshubConfigured=false，apply 会拒绝。"""
    data = await _read_bounded_opml(request)
    parsed = parse_opml(data)
    service = _rsshub_import_service(request)
    return service.plan(parsed)


@router.post("/api/v1/opml/import/rsshub-apply")
async def opml_rsshub_apply(
    request: Request,
    strategy: str | None = None,
    approved: str | None = None,
    chosen: Annotated[list[str] | None, Query()] = None,
) -> dict[str, object]:
    """R18：应用 RSSHub 优化导入。

    strategy=prefer_rsshub（默认，只执行唯一高置信且无凭据需求的
    自动建议）/ prefer_native（全部按原生合并导入）/ manual（只替换
    approved 参数勾选的条目；chosen 重复参数可逐项指定计划内的候选
    路由，格式 "index|routePath"，缺省用该项首选候选）。

    替换 = 先实际验证（从本站实例拉取该路由确认 200 + 可解析 feed，
    有界预算）再经 FreshRSS 实际订阅入库；原地址已订阅的来源**保留
    旧源**并写映射台账（FreshRSS 已读/收藏状态绑定条目地址，无法跨
    源安全迁移——绝不自动退订）；新导入来源的原始地址进台账，可经
    rsshub-mappings 撤销回原生。RSSHub 未配置 → 503 rsshub_not_configured。"""
    clean_strategy = strategy_or_none(strategy)
    if clean_strategy is None:
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "type": "invalid_strategy",
                    "message": "strategy 必须是 prefer_rsshub / prefer_native / manual。",
                }
            },
        )
    try:
        approved_set = _parse_approved(approved)
        chosen_map = _parse_chosen(chosen)
    except ValueError as exc:
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "type": "invalid_selection",
                    "message": f"approved/chosen 参数非法：{exc}",
                }
            },
        )
    data = await _read_bounded_opml(request)
    parsed = parse_opml(data)
    service = _rsshub_import_service(request)
    result = await service.apply(
        parsed,
        strategy=clean_strategy,
        approved_indexes=approved_set,
        chosen_map=chosen_map,
    )
    # F049 复用：导入批次计数（替换/回落计入 imported，失败项可重试）。
    with contextlib.suppress(Exception):
        await ImportBatchStore(request.app.state.db).record(
            kind="opml",
            counts={
                "imported": int(result["counts"]["replaced"])  # type: ignore[index]
                + int(result["counts"]["addedNative"]),  # type: ignore[index]
                "skipped": int(result["counts"]["skipped"]),  # type: ignore[index]
                "failed": int(result["counts"]["failed"]),  # type: ignore[index]
            },
            errors=[
                {"url": str(item.get("feedUrl")), "reason": item.get("error")}
                for item in result.get("failed", [])
                if isinstance(item, dict)
            ],
        )
    return result


@router.get("/api/v1/opml/rsshub-mappings")
async def list_rsshub_source_mappings(request: Request) -> dict[str, object]:
    """R18：原生 ↔ RSSHub 来源映射台账（per-user，新→旧，有界 200）。

    来源运维工作台展示「原始地址 / 当前 RSSHub 地址 / 撤销映射」；
    凭据不落库，本表只存地址与路由结构。"""
    items = await RsshubSourceMappingStore(request.app.state.db).list_all()
    return {"items": items}


@router.post("/api/v1/opml/rsshub-mappings/{mapping_uuid}/revert")
async def revert_rsshub_source_mapping(
    mapping_uuid: str, request: Request
) -> dict[str, object]:
    """R18：撤销一条映射——重新订阅原始地址并把台账置 reverted。

    诚实边界：RSSHub 源**不自动退订**（避免破坏性动作；可稍后在来源
    管理手动退订）；原始地址订阅失败 → 502（台账保持 active，撤销未
    完成，如实报告）。幂等：已 reverted 的行原样返回。"""
    store = RsshubSourceMappingStore(request.app.state.db)
    mapping = await store.get(mapping_uuid)
    if mapping is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": {"type": "mapping_not_found", "message": "映射不存在。"}
            },
        )
    control = _get_control_adapter(request)
    original_url = str(mapping["originalUrl"])
    already = any(
        subscription.feed_url == original_url
        for subscription in await control.list_subscriptions()
    )
    if not already:
        from lumirss.rsshub import AdapterError
        from lumirss.rsshub_import_flow import _failure_type

        try:
            await control.subscribe(original_url)
        except AdapterError as exc:
            return JSONResponse(
                status_code=502,
                content={
                    "error": {
                        "type": "revert_subscribe_failed",
                        "message": "原始地址订阅失败，撤销未完成。",
                        "failureType": _failure_type(exc),
                    }
                },
            )
    reverted = await store.mark_reverted(mapping_uuid)
    return {
        "mapping": reverted,
        "originalSubscribed": True,
        "rsshubSourceRemoved": False,
        "note": (
            "已恢复订阅原始地址；RSSHub 来源未自动退订，可在来源管理中手动处理。"
        ),
    }
