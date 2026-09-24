"""Obsidian read-only library routes (phase2 G6) + federated favorites."""

from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from lumirss.favorites import FavoriteInvalid
from lumirss.models import (
    FavoritesResponse,
    LibraryFavoriteRequest,
    NoteListResponse,
    NoteView,
    ObsidianBlockRef,
    ObsidianBlockRefsResponse,
    ObsidianDeviceProfile,
    ObsidianDeviceProfileList,
    ObsidianDeviceProfilePayload,
    ObsidianExportHandoffRequest,
    ObsidianExportHandoffResult,
    ObsidianExportIssue,
    ObsidianExportTemplateUpdate,
    ObsidianExportTemplateView,
    ObsidianExportValidateRequest,
    ObsidianExportValidateResult,
    ObsidianHandoffLogClearResult,
    ObsidianHandoffLogCreate,
    ObsidianHandoffLogEntry,
    ObsidianHandoffLogList,
    ObsidianNoteSetting,
    ObsidianRescanResult,
    ObsidianSettings,
    ObsidianStatus,
    ObsidianTemplatePreviewRequest,
    ObsidianTemplatePreviewResult,
)
from lumirss.obsidian import NoteNotFound

from ..deps import _get_favorites_service, _get_obsidian_service

router = APIRouter()


async def _require_owner(request: Request):
    """O168：Vault 属于运营者（owner）。member/admin 不可读写、不可
    扫描——一次越权扫描等于把 owner 的私人笔记灌进别人的索引。
    basic 模式只有 owner，行为不变。"""
    from lumirss.config import LumiSettings
    from lumirss.user_scope import principal_of

    if LumiSettings().LUMIRSS_AUTH_MODE != "session":
        return None
    principal = principal_of(request.scope)
    if principal is None or principal.get("role") != "owner":
        return JSONResponse(
            status_code=403,
            content={"error": {"type": "forbidden", "message": "Owner role required."}},
            headers={"Cache-Control": "no-store"},
        )
    return None


@router.get("/api/v1/obsidian/status", response_model=ObsidianStatus)
async def obsidian_status(request: Request) -> ObsidianStatus:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    service = _get_obsidian_service(request)
    status = await service.get_status()
    return ObsidianStatus(**status)


@router.put("/api/v1/obsidian/settings", response_model=ObsidianSettings)
async def set_obsidian_settings(
    payload: ObsidianNoteSetting, request: Request
) -> ObsidianSettings:
    """Configure the vault root (canonicalized, validated, read-only).

    Rejected while the deployment fixes the root via
    LUMIRSS_OBSIDIAN_VAULT_DIR — the bind mount owns the path then."""
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    service = _get_obsidian_service(request)
    canonical = await service.set_vault_path(payload.vaultPath)
    return ObsidianSettings(
        vaultPath=str(canonical),
        noteCount=await service.note_count(),
    )


@router.post("/api/v1/obsidian/rescan", response_model=ObsidianRescanResult)
async def rescan_obsidian(request: Request) -> ObsidianRescanResult:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    service = _get_obsidian_service(request)
    return ObsidianRescanResult(**await service.rescan())


@router.get("/api/v1/obsidian/notes", response_model=NoteListResponse)
async def list_notes(
    request: Request,
    q: str | None = None,
    limit: int = 50,
) -> NoteListResponse:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    service = _get_obsidian_service(request)
    notes = await service.list_notes(q=q, limit=limit)
    return NoteListResponse(
        items=[
            NoteView(
                ref=note["ref"],
                relPath=note["relPath"],
                title=note["title"],
                tags=note["tags"],
                indexedAt=note["indexedAt"],
            )
            for note in notes
        ]
    )


@router.get("/api/v1/obsidian/notes/{note_uuid}", response_model=NoteView)
async def get_note(note_uuid: str, request: Request) -> NoteView:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    service = _get_obsidian_service(request)
    note = await service.get_note(note_uuid)
    if note is None:
        # A missing row is a missing NOTE (404), not an unreachable
        # vault (503): the indexed snapshot renders without the vault.
        raise NoteNotFound(note_uuid)
    return NoteView(
        ref=note["ref"],
        relPath=note["relPath"],
        title=note["title"],
        tags=note["tags"],
        indexedAt=note["indexedAt"],
        contentHtml=note.get("contentHtml"),
        wikilinks=note.get("wikilinks"),
        truncated=note.get("truncated", False),
    )


@router.get("/api/v1/favorites", response_model=FavoritesResponse)
async def federated_favorites(request: Request) -> FavoritesResponse:
    """RSS star (FreshRSS truth) + library favorites (Lumi truth) merged
    for display — never copied across domains."""
    service = _get_favorites_service(request)
    return await service.federated_favorites()


@router.post("/api/v1/favorites/library", status_code=204)
async def add_library_favorite(
    payload: LibraryFavoriteRequest, request: Request
) -> Response:
    """Favorite one library ItemRef (existence-validated, ADR 0004)."""
    service = _get_favorites_service(request)
    # rss content uses FreshRSS star; favorites are library-domain only.
    from lumirss.itemref import parse_item_ref

    if parse_item_ref(payload.ref).domain == "rss":
        raise FavoriteInvalid(
            "RSS 内容使用星标（star），库收藏仅用于 library 内容。"
        )
    from lumirss.sources import ItemRefUnresolvable, ensure_resolvable

    from ..deps import _get_source_registry

    try:
        await ensure_resolvable(_get_source_registry(request), payload.ref)
    except ItemRefUnresolvable as exc:
        raise FavoriteInvalid("引用的内容不存在，无法收藏。") from exc
    await service.add_favorite(payload.ref)
    return Response(status_code=204)


@router.delete("/api/v1/favorites/library", status_code=204)
async def remove_library_favorite(
    payload: LibraryFavoriteRequest, request: Request
) -> Response:
    service = _get_favorites_service(request)
    await service.remove_favorite(payload.ref)
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# F080：反链/断链查询。
# ---------------------------------------------------------------------------


@router.get("/api/v1/obsidian/notes/{note_uuid}/backlinks")
async def list_note_backlinks(note_uuid: str, request: Request) -> Any:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    from lumirss.obsidian_backlinks import backlinks_for

    return {"items": await backlinks_for(request.app.state.db, note_uuid)}


@router.get("/api/v1/obsidian/notes/{note_uuid}/broken-links")
async def list_note_broken_links(note_uuid: str, request: Request) -> Any:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    from lumirss.obsidian_backlinks import broken_links_for

    return {"items": await broken_links_for(request.app.state.db, note_uuid)}


# ---------------------------------------------------------------------------
# N134：块级回跳 round-trip —— 投影扫描已把笔记正文里的 ^lumi-<paraId>
# 块 id 建成索引（rescan → rebuild_block_refs）；此处反查「哪些笔记引用
# 了这个段落」。与反链同属 Vault 投影域 → 同样的 owner 门槛。
# ---------------------------------------------------------------------------


@router.get(
    "/api/v1/obsidian/block-refs", response_model=ObsidianBlockRefsResponse
)
async def list_block_refs(
    request: Request,
    paraId: str = "",
) -> ObsidianBlockRefsResponse | JSONResponse:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    if not paraId.strip():
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "type": "invalid_request",
                    "message": "paraId 不能为空。",
                }
            },
        )
    from lumirss.obsidian_backlinks import block_refs_for

    items = await block_refs_for(request.app.state.db, paraId)
    return ObsidianBlockRefsResponse(
        items=[
            ObsidianBlockRef(
                paraId=item["paraId"],
                noteUuid=item["noteUuid"],
                title=item["title"],
                relPath=item["relPath"],
                indexedAt=item["indexedAt"],
            )
            for item in items
        ]
    )


# ---------------------------------------------------------------------------
# P16：多设备交接 —— 设备档案 / 导出模板 / 导出交接。
# 用户级（user-scoped）：设备档案描述用户自己设备上的 Obsidian，只服务
# obsidian:// URI 生成；与服务器端 vault_path（env 挂载/手动路径，owner
# 的扫描面）解耦 —— 因此这里刻意【不带】_require_owner 门槛，任何登录
# 账户管理自己的设备与模板。Vault 依旧只读（ADR 0004）：obsidian://new
# 只是把内容交给用户本机的 Obsidian，保存由用户在 Obsidian 里确认。
# ---------------------------------------------------------------------------


def _device_store(request: Request):
    from lumirss.obsidian_devices import ObsidianDeviceStore

    return ObsidianDeviceStore(request.app.state.db)


def _template_store(request: Request):
    from lumirss.obsidian_devices import ObsidianExportSettingsStore

    return ObsidianExportSettingsStore(request.app.state.db)


@router.get(
    "/api/v1/obsidian/devices", response_model=ObsidianDeviceProfileList
)
async def list_obsidian_devices(request: Request) -> ObsidianDeviceProfileList:
    items = await _device_store(request).list_profiles()
    return ObsidianDeviceProfileList(
        items=[
            ObsidianDeviceProfile(
                id=item["id"],
                label=item["label"],
                vaultName=item["vault_name"],
                vaultIdentifier=item["vault_identifier"],
                platform=item["platform"],  # type: ignore[arg-type]
                createdAt=item["created_at"],
            )
            for item in items
        ]
    )


@router.post(
    "/api/v1/obsidian/devices",
    response_model=ObsidianDeviceProfile,
    status_code=201,
)
async def create_obsidian_device(
    payload: ObsidianDeviceProfilePayload, request: Request
) -> ObsidianDeviceProfile:
    profile = await _device_store(request).create(
        label=payload.label,
        vault_name=payload.vaultName,
        vault_identifier=payload.vaultIdentifier,
        platform=payload.platform,
    )
    return ObsidianDeviceProfile(
        id=profile["id"],
        label=profile["label"],
        vaultName=profile["vault_name"],
        vaultIdentifier=profile["vault_identifier"],
        platform=profile["platform"],  # type: ignore[arg-type]
        createdAt=profile["created_at"],
    )


@router.put("/api/v1/obsidian/devices/{device_id}", response_model=ObsidianDeviceProfile)
async def update_obsidian_device(
    device_id: str, payload: ObsidianDeviceProfilePayload, request: Request
) -> ObsidianDeviceProfile:
    from lumirss.obsidian_devices import DeviceProfileNotFound

    profile = await _device_store(request).update(
        device_id,
        label=payload.label,
        vault_name=payload.vaultName,
        vault_identifier=payload.vaultIdentifier,
        platform=payload.platform,
    )
    if profile is None:
        raise DeviceProfileNotFound(device_id)
    return ObsidianDeviceProfile(
        id=profile["id"],
        label=profile["label"],
        vaultName=profile["vault_name"],
        vaultIdentifier=profile["vault_identifier"],
        platform=profile["platform"],  # type: ignore[arg-type]
        createdAt=profile["created_at"],
    )


@router.delete("/api/v1/obsidian/devices/{device_id}", status_code=204)
async def delete_obsidian_device(
    device_id: str, request: Request
) -> Response:
    from lumirss.obsidian_devices import DeviceProfileNotFound

    deleted = await _device_store(request).delete(device_id)
    if not deleted:
        raise DeviceProfileNotFound(device_id)
    return Response(status_code=204)


async def _template_view(request: Request) -> ObsidianExportTemplateView:
    from lumirss.obsidian_template import (
        ALLOWED_TEMPLATE_VARS,
        DEFAULT_TEMPLATE,
    )

    store = _template_store(request)
    stored = await store.get_stored_template()
    return ObsidianExportTemplateView(
        template=stored,
        defaultTemplate=DEFAULT_TEMPLATE,
        allowedVars=list(ALLOWED_TEMPLATE_VARS),
        exportNamePolicy=await store.get_name_policy(),  # type: ignore[arg-type]
    )


@router.get(
    "/api/v1/obsidian/export-template", response_model=ObsidianExportTemplateView
)
async def get_obsidian_export_template(
    request: Request,
) -> ObsidianExportTemplateView:
    return await _template_view(request)


@router.put(
    "/api/v1/obsidian/export-template", response_model=ObsidianExportTemplateView
)
async def set_obsidian_export_template(
    payload: ObsidianExportTemplateUpdate, request: Request
) -> ObsidianExportTemplateView:
    store = _template_store(request)
    if payload.template is not None:
        await store.set_template(payload.template)
    if payload.exportNamePolicy is not None:  # N135：命名策略可单独更新
        await store.set_name_policy(payload.exportNamePolicy)
    return await _template_view(request)


@router.post(
    "/api/v1/obsidian/export-template/preview",
    response_model=ObsidianTemplatePreviewResult,
)
async def preview_obsidian_export_template(
    payload: ObsidianTemplatePreviewRequest, request: Request
) -> ObsidianTemplatePreviewResult:
    """Live preview for the template editor.

    ``entryRef`` given → renders the REAL article (reader handoff
    preview); omitted → fixture text. Unknown variables are reported
    honestly instead of passing through silently."""
    from lumirss.deps import _get_adapter
    from lumirss.entryref import decode_entry_ref
    from lumirss.obsidian_handoff import (
        FIXTURE_CONTEXT,
        build_export_context,
        render_export_markdown,
    )

    if payload.entryRef:
        item_id = decode_entry_ref(payload.entryRef)
        detail = await _get_adapter(request).get_entry(item_id)
        # 预览不带批注（批注清单在阅读页交接时由服务端注入）。
        context = build_export_context(detail, [])
        source = "entry"
    else:
        context = FIXTURE_CONTEXT
        source = "fixture"
    rendered = render_export_markdown(payload.template, context)
    return ObsidianTemplatePreviewResult(
        text=rendered.text, unknownVars=rendered.unknown_vars, source=source
    )


async def _prepare_handoff_payload(
    payload: ObsidianExportHandoffRequest | ObsidianExportValidateRequest,
    request: Request,
):
    """Shared composition path for export-handoff 与 N139 校验：设备档案 →
    文章 → 模板/命名策略/公网基底 →（可选增量）批注 → 组装渲染。"""
    from lumirss.annotation_store import AnnotationStore
    from lumirss.config import LumiSettings
    from lumirss.deps import _get_adapter
    from lumirss.entryref import decode_entry_ref
    from lumirss.obsidian_devices import DeviceProfileNotFound
    from lumirss.obsidian_handoff import prepare_handoff_for_entry

    profile = await _device_store(request).get(payload.deviceId)
    if profile is None:
        raise DeviceProfileNotFound(payload.deviceId)
    item_id = decode_entry_ref(payload.entryRef)
    detail = await _get_adapter(request).get_entry(item_id)
    template_store = _template_store(request)
    template = await template_store.get_template()
    name_policy = await template_store.get_name_policy()
    watermark = None
    if payload.onlySinceLastExport:
        watermark = await AnnotationStore(request.app.state.db).last_export_watermark()
    prepared = await prepare_handoff_for_entry(
        request.app.state.db,
        detail,
        profile=profile,
        entry_ref=payload.entryRef,
        template=template,
        public_url=LumiSettings().LUMIRSS_PUBLIC_URL,
        name_policy=name_policy,
        only_updated_after=watermark,
    )
    return prepared, name_policy


@router.post(
    "/api/v1/obsidian/export-handoff",
    response_model=ObsidianExportHandoffResult,
)
async def export_obsidian_handoff(
    payload: ObsidianExportHandoffRequest, request: Request
) -> ObsidianExportHandoffResult:
    """Compose + render + decide URI vs file fallback for one article.

    Honest handoff: ``mode='uri'`` means the obsidian://new link was
    built (the USER's Obsidian does any writing after confirmation);
    ``mode='file'`` with reason='tooLong' means the content exceeded the
    URI budget and the client falls back to download + clipboard.

    N137：交接组装成功后回标导出水位（mark 幂等，重复导出无害）；
    N135：命名策略体现在 filename（timestamp_suffix 追加 -YYYYMMDD-HHmm）；
    N140：自动落一条 pending 交接记录（confirmed 只能由用户显式确认）。"""
    from lumirss.annotation_store import AnnotationStore
    from lumirss.obsidian_handoff_log import HandoffLogStore

    prepared, name_policy = await _prepare_handoff_payload(payload, request)
    if prepared.annotation_ids:
        await AnnotationStore(request.app.state.db).mark_exported(
            prepared.annotation_ids
        )
    await HandoffLogStore(request.app.state.db).log_pending(
        direction="export",
        entry_ref=payload.entryRef,
        note_name=prepared.filename,
        policy=name_policy,
    )
    return ObsidianExportHandoffResult(
        mode=prepared.mode,  # type: ignore[arg-type]
        uri=prepared.uri,
        reason=prepared.reason,
        filename=prepared.filename,
        content=prepared.content,
        unknownVars=prepared.unknown_vars,
        deviceLabel=prepared.device_label,
        annotationCount=len(prepared.annotation_ids),
    )


@router.post(
    "/api/v1/obsidian/export-handoff/validate",
    response_model=ObsidianExportValidateResult,
)
async def validate_obsidian_export(
    payload: ObsidianExportValidateRequest, request: Request
) -> ObsidianExportValidateResult:
    """N139 导出侧链接校验（只读报告）：对组装好的 Markdown 检查
    断链 wikilink / 缺失附件 / 重复块 id。绝不改写用户 Vault 文件，
    不交接、不落交接日志、不推进导出水位。"""
    from lumirss.obsidian import check_vault_path
    from lumirss.obsidian_handoff import (
        build_projection_index,
        validate_export_markdown,
    )

    prepared, _policy = await _prepare_handoff_payload(payload, request)
    notes = await request.app.state.db.fetch_all(
        "SELECT rel_path, title FROM obsidian_notes LIMIT 5000"
    )
    index = build_projection_index(
        [{"rel_path": str(r["rel_path"]), "title": str(r["title"])} for r in notes]
    )
    vault_path = await _get_obsidian_service(request).get_vault_path()
    vault_exists = None
    vault_checked = False
    if vault_path:
        # 只读存在性核对（含 containment 防护）；不可达 → None 跳过检查。
        vault_exists = lambda rel: check_vault_path(vault_path, rel)  # noqa: E731
        vault_checked = True
    issues = validate_export_markdown(prepared.content, projection_index=index, vault_exists=vault_exists)
    return ObsidianExportValidateResult(
        issues=[
            ObsidianExportIssue(
                kind=issue["kind"],  # type: ignore[arg-type]
                detail=issue["detail"],
                suggestion=issue["suggestion"],
            )
            for issue in issues
        ],
        vaultChecked=vault_checked,
    )


# ---------------------------------------------------------------------------
# N140：双向交接记录 —— 列表 / 显式确认 / 显式记录 open·import_confirm /
# 清理。用户级（per-user 库）；confirmed 只能由用户显式动作产生。
# ---------------------------------------------------------------------------


def _handoff_log_store(request: Request):
    from lumirss.obsidian_handoff_log import HandoffLogStore

    return HandoffLogStore(request.app.state.db)


def _handoff_log_entry(item: dict[str, Any]) -> ObsidianHandoffLogEntry:
    return ObsidianHandoffLogEntry(
        id=item["id"],
        direction=item["direction"],  # type: ignore[arg-type]
        entryRef=item["entryRef"],
        noteName=item["noteName"],
        policy=item["policy"],
        status=item["status"],  # type: ignore[arg-type]
        createdAt=item["createdAt"],
        confirmedAt=item["confirmedAt"],
    )


@router.get("/api/v1/obsidian/handoff-log", response_model=ObsidianHandoffLogList)
async def list_obsidian_handoff_log(
    request: Request, limit: int = 50
) -> ObsidianHandoffLogList:
    items = await _handoff_log_store(request).list_entries(limit=limit)
    return ObsidianHandoffLogList(items=[_handoff_log_entry(item) for item in items])


@router.post(
    "/api/v1/obsidian/handoff-log",
    response_model=ObsidianHandoffLogEntry,
    status_code=201,
)
async def create_obsidian_handoff_log(
    payload: ObsidianHandoffLogCreate, request: Request
) -> ObsidianHandoffLogEntry:
    """显式记录 open / import_confirm 交接（export 自动落库，不接受手工
    伪造方向）。pending 记录同样只能通过 confirm 端点显式确认。"""
    from lumirss.obsidian_handoff_log import HandoffLogInvalid

    try:
        item = await _handoff_log_store(request).log_pending(
            direction=payload.direction,
            entry_ref=payload.entryRef,
            note_name=payload.noteName,
            policy=payload.policy,
        )
    except HandoffLogInvalid as exc:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "invalid_handoff_log", "message": str(exc)}},
        )
    return _handoff_log_entry(item)


@router.post(
    "/api/v1/obsidian/handoff/{handoff_id}/confirm",
    response_model=ObsidianHandoffLogEntry,
)
async def confirm_obsidian_handoff(
    handoff_id: str, request: Request
) -> ObsidianHandoffLogEntry | JSONResponse:
    """显式确认（用户在 Obsidian 中保存后亲自触发）——confirmed 的唯一
    路径。页面可见性 / 重新加载等被动事件绝不调用这里。幂等：对已确认
    行重复确认返回原行；不存在 → 404。"""
    item = await _handoff_log_store(request).confirm(handoff_id)
    if item is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "type": "handoff_log_not_found",
                    "message": "交接记录不存在。",
                }
            },
        )
    return _handoff_log_entry(item)


@router.delete(
    "/api/v1/obsidian/handoff-log",
    response_model=ObsidianHandoffLogClearResult,
)
async def clear_obsidian_handoff_log(
    request: Request,
) -> ObsidianHandoffLogClearResult:
    return ObsidianHandoffLogClearResult(
        cleared=await _handoff_log_store(request).clear()
    )
