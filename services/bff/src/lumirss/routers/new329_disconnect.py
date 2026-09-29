"""NEW-329 本地资料断开连接路由 — 撤销授权 / 副本去留 / 重新授权。

- POST /api/v1/obsidian/roots/{root_id}/disconnect  撤销授权 → 扫描停止
- POST /api/v1/obsidian/roots/{root_id}/copies      {action: 'keep'|'delete'}
- POST /api/v1/obsidian/roots/{root_id}/reconnect   重新授权（扫描恢复）

撤销授权后扫描入口（scan 路由与任何后续扫描）都校验授权状态并拒绝；
副本去留必须由用户显式二选一，Lumi 绝不自作主张删除，也绝不触碰
源目录。owner 门槛（O168）。
"""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from lumirss.new325_root_profiles import (
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


@router.post("/api/v1/obsidian/roots/{root_id}/disconnect")
async def disconnect_root(root_id: str, request: Request) -> Any:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    try:
        profile = await _store(request).disconnect(root_id)
    except RootProfileNotFound:
        return _error(404, "root_profile_not_found", "资料根档案不存在。")
    return JSONResponse(profile)


@router.post("/api/v1/obsidian/roots/{root_id}/copies")
async def decide_root_copies(root_id: str, payload: dict[str, Any], request: Request) -> Any:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    try:
        result = await _store(request).decide_copies(
            root_id, str(payload.get("action") or "")
        )
    except RootProfileNotFound:
        return _error(404, "root_profile_not_found", "资料根档案不存在。")
    except RootProfileInvalid as exc:
        return _error(400, "invalid_copies_action", str(exc))
    return JSONResponse(result)


@router.post("/api/v1/obsidian/roots/{root_id}/reconnect")
async def reconnect_root(root_id: str, request: Request) -> Any:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    try:
        profile = await _store(request).reconnect(root_id)
    except RootProfileNotFound:
        return _error(404, "root_profile_not_found", "资料根档案不存在。")
    return JSONResponse(profile)
