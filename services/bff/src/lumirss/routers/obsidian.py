"""Obsidian read-only library routes (phase2 G6) + federated favorites."""

from fastapi import APIRouter, Request, Response

from lumirss.favorites import FavoriteInvalid
from lumirss.models import (
    FavoritesResponse,
    LibraryFavoriteRequest,
    NoteListResponse,
    NoteView,
    ObsidianNoteSetting,
    ObsidianRescanResult,
    ObsidianSettings,
    ObsidianStatus,
)
from lumirss.obsidian import NoteNotFound

from ..deps import _get_favorites_service, _get_obsidian_service

router = APIRouter()


@router.get("/api/v1/obsidian/status", response_model=ObsidianStatus)
async def obsidian_status(request: Request) -> ObsidianStatus:
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
    service = _get_obsidian_service(request)
    canonical = await service.set_vault_path(payload.vaultPath)
    return ObsidianSettings(
        vaultPath=str(canonical),
        noteCount=await service.note_count(),
    )


@router.post("/api/v1/obsidian/rescan", response_model=ObsidianRescanResult)
async def rescan_obsidian(request: Request) -> ObsidianRescanResult:
    service = _get_obsidian_service(request)
    return ObsidianRescanResult(**await service.rescan())


@router.get("/api/v1/obsidian/notes", response_model=NoteListResponse)
async def list_notes(
    request: Request,
    q: str | None = None,
    limit: int = 50,
) -> NoteListResponse:
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
