"""NEW-325 资料库多根目录档案路由 — 档案 CRUD / 独立扫描 / 笔记列表。

- POST   /api/v1/obsidian/roots                 {label, rootPath, ignoreGlobs?}
- GET    /api/v1/obsidian/roots                 全部档案 + 各自同步状态
- GET    /api/v1/obsidian/roots/{root_id}
- PATCH  /api/v1/obsidian/roots/{root_id}       {label?, ignoreGlobs?}
- DELETE /api/v1/obsidian/roots/{root_id}
- POST   /api/v1/obsidian/roots/{root_id}/scan  独立增量扫描（只读根）
- GET    /api/v1/obsidian/roots/{root_id}/notes?tag=

每个根是独立只读档案：containment 与主 Vault 同口径，扫描绝不写根。
owner 门槛（O168）：成员不可见、不可扫。
"""

from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from lumirss.new325_root_profiles import (
    RootNotAuthorized,
    RootProfileInvalid,
    RootProfileNotFound,
    RootProfileStore,
)
from lumirss.routers.obsidian import _require_owner

router = APIRouter()


def _store(request: Request) -> RootProfileStore:
    return RootProfileStore(request.app.state.db)


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


@router.post("/api/v1/obsidian/roots", status_code=201)
async def create_root_profile(payload: dict[str, Any], request: Request) -> Any:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    ignore = payload.get("ignoreGlobs")
    try:
        profile = await _store(request).create(
            str(payload.get("label") or ""),
            str(payload.get("rootPath") or ""),
            ignore if isinstance(ignore, list) else None,
        )
    except RootProfileInvalid as exc:
        return _error(400, "invalid_root_profile", str(exc))
    return JSONResponse(profile, status_code=201)


@router.get("/api/v1/obsidian/roots")
async def list_root_profiles(request: Request) -> Any:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    return JSONResponse({"roots": await _store(request).list_profiles()})


@router.get("/api/v1/obsidian/roots/{root_id}")
async def get_root_profile(root_id: str, request: Request) -> Any:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    profile = await _store(request).get(root_id)
    if profile is None:
        return _error(404, "root_profile_not_found", "资料根档案不存在。")
    return JSONResponse(profile)


@router.patch("/api/v1/obsidian/roots/{root_id}")
async def update_root_profile(root_id: str, payload: dict[str, Any], request: Request) -> Any:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    ignore = payload.get("ignoreGlobs")
    try:
        profile = await _store(request).update(
            root_id,
            label=payload.get("label"),
            ignore_globs=ignore if isinstance(ignore, list) else None,
        )
    except RootProfileInvalid as exc:
        return _error(400, "invalid_root_profile", str(exc))
    if profile is None:
        return _error(404, "root_profile_not_found", "资料根档案不存在。")
    return JSONResponse(profile)


@router.delete("/api/v1/obsidian/roots/{root_id}", status_code=204)
async def delete_root_profile(root_id: str, request: Request) -> Response:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    deleted = await _store(request).delete(root_id)
    if not deleted:
        return _error(404, "root_profile_not_found", "资料根档案不存在。")
    return Response(status_code=204)


@router.post("/api/v1/obsidian/roots/{root_id}/scan")
async def scan_root_profile(root_id: str, request: Request) -> Any:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    try:
        return JSONResponse(await _store(request).scan(root_id))
    except RootProfileNotFound:
        return _error(404, "root_profile_not_found", "资料根档案不存在。")
    except RootNotAuthorized as exc:
        return _error(409, "root_not_authorized", str(exc))


@router.get("/api/v1/obsidian/roots/{root_id}/notes")
async def list_root_notes(root_id: str, request: Request, tag: str = "") -> Any:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    try:
        notes = await _store(request).notes(root_id, tag=tag)
    except RootProfileNotFound:
        return _error(404, "root_profile_not_found", "资料根档案不存在。")
    return JSONResponse({"notes": notes})
