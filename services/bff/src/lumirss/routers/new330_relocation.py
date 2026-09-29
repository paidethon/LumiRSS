"""NEW-330 资料路径重定位向导路由 — 预览 / 应用 / 历史。

- POST /api/v1/obsidian/roots/{root_id}/relocate/preview  {newPath} → 五类清单
- POST /api/v1/obsidian/roots/{root_id}/relocate/{rid}/apply
- GET  /api/v1/obsidian/roots/{root_id}/relocate          向导历史

匹配键 = content_hash（与 FIX-337/339 改名侦测同口径）；应用不重复
导入（行 id 不变），fresh/vanished 由下一次扫描如实处理。owner 门槛
（O168）。
"""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from lumirss.new325_root_profiles import RootProfileNotFound, RootProfileStore
from lumirss.new330_relocation import RelocateInvalid, RelocationWizard
from lumirss.obsidian import VaultPermissionDenied, VaultUnreachable
from lumirss.routers.obsidian import _require_owner

router = APIRouter()


def _wizard(request: Request) -> RelocationWizard:
    return RelocationWizard(
        request.app.state.db, RootProfileStore(request.app.state.db)
    )


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


@router.post("/api/v1/obsidian/roots/{root_id}/relocate/preview")
async def preview_relocation(root_id: str, payload: dict[str, Any], request: Request) -> Any:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    try:
        return JSONResponse(
            await _wizard(request).preview(root_id, str(payload.get("newPath") or ""))
        )
    except RootProfileNotFound:
        return _error(404, "root_profile_not_found", "资料根档案不存在。")
    except RelocateInvalid as exc:
        return _error(400, "invalid_relocation", str(exc))
    except VaultUnreachable as exc:
        return _error(503, "vault_unreachable", str(exc))
    except VaultPermissionDenied as exc:
        return _error(403, "vault_permission_denied", str(exc))


@router.post("/api/v1/obsidian/roots/{root_id}/relocate/{relocation_id}/apply")
async def apply_relocation(
    root_id: str, relocation_id: str, request: Request
) -> Any:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    try:
        return JSONResponse(
            await _wizard(request).apply(root_id, relocation_id)
        )
    except RootProfileNotFound:
        return _error(404, "root_profile_not_found", "资料根档案不存在。")
    except RelocateInvalid as exc:
        return _error(409, "invalid_relocation", str(exc))


@router.get("/api/v1/obsidian/roots/{root_id}/relocate")
async def relocation_history(root_id: str, request: Request) -> Any:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    try:
        return JSONResponse({"relocations": await _wizard(request).history(root_id)})
    except RootProfileNotFound:
        return _error(404, "root_profile_not_found", "资料根档案不存在。")
