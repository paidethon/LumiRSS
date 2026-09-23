"""Obsidian read-only library routes (phase2 G6) + federated favorites."""

from typing import Any

from fastapi import APIRouter, Request, Response

from lumirss.favorites import FavoriteInvalid
from lumirss.models import (
    FavoritesResponse,
    LibraryFavoriteRequest,
    NoteListResponse,
    NoteView,
    ObsidianDeviceProfile,
    ObsidianDeviceProfileList,
    ObsidianDeviceProfilePayload,
    ObsidianExportHandoffRequest,
    ObsidianExportHandoffResult,
    ObsidianExportTemplateUpdate,
    ObsidianExportTemplateView,
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
    from fastapi.responses import JSONResponse

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


@router.get(
    "/api/v1/obsidian/export-template", response_model=ObsidianExportTemplateView
)
async def get_obsidian_export_template(
    request: Request,
) -> ObsidianExportTemplateView:
    from lumirss.obsidian_template import (
        ALLOWED_TEMPLATE_VARS,
        DEFAULT_TEMPLATE,
    )

    stored = await _template_store(request).get_stored_template()
    return ObsidianExportTemplateView(
        template=stored,
        defaultTemplate=DEFAULT_TEMPLATE,
        allowedVars=list(ALLOWED_TEMPLATE_VARS),
    )


@router.put(
    "/api/v1/obsidian/export-template", response_model=ObsidianExportTemplateView
)
async def set_obsidian_export_template(
    payload: ObsidianExportTemplateUpdate, request: Request
) -> ObsidianExportTemplateView:
    from lumirss.obsidian_template import (
        ALLOWED_TEMPLATE_VARS,
        DEFAULT_TEMPLATE,
    )

    stored = await _template_store(request).set_template(payload.template)
    return ObsidianExportTemplateView(
        template=stored,
        defaultTemplate=DEFAULT_TEMPLATE,
        allowedVars=list(ALLOWED_TEMPLATE_VARS),
    )


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
    URI budget and the client falls back to download + clipboard."""
    from lumirss.deps import _get_adapter
    from lumirss.entryref import decode_entry_ref
    from lumirss.obsidian_devices import DeviceProfileNotFound
    from lumirss.obsidian_handoff import prepare_handoff_for_entry

    store = _device_store(request)
    profile = await store.get(payload.deviceId)
    if profile is None:
        raise DeviceProfileNotFound(payload.deviceId)
    item_id = decode_entry_ref(payload.entryRef)
    detail = await _get_adapter(request).get_entry(item_id)
    template = await _template_store(request).get_template()
    prepared = await prepare_handoff_for_entry(
        request.app.state.db,
        detail,
        profile=profile,
        entry_ref=payload.entryRef,
        template=template,
    )
    return ObsidianExportHandoffResult(
        mode=prepared.mode,  # type: ignore[arg-type]
        uri=prepared.uri,
        reason=prepared.reason,
        filename=prepared.filename,
        content=prepared.content,
        unknownVars=prepared.unknown_vars,
        deviceLabel=prepared.device_label,
    )
