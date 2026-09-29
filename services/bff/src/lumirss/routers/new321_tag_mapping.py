"""NEW-321 Obsidian 标签映射规则路由 — 预览 / 规则 CRUD / 物化导入层。

- GET    /api/v1/obsidian/tag-mapping/preview    纯预览（层级/合并/冲突）
- GET    /api/v1/obsidian/tag-mapping/rules      规则列表
- PUT    /api/v1/obsidian/tag-mapping/rules      upsert 单条规则
- DELETE /api/v1/obsidian/tag-mapping/rules?sourceTag=
- POST   /api/v1/obsidian/tag-mapping/materialize  按规则重建导入层
- GET    /api/v1/obsidian/tag-mapping/import     导入层总览
- GET    /api/v1/obsidian/tag-mapping/import?tag=  按个人标签查笔记

Vault 是 owner 的扫描面（O168）：全部路由走 owner 门槛；映射只改变
导入层，绝不写 Vault。
"""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from lumirss.new321_tag_mapping import TagMappingInvalid, TagMappingStore
from lumirss.routers.obsidian import _require_owner

router = APIRouter()


def _store(request: Request) -> TagMappingStore:
    return TagMappingStore(request.app.state.db)


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


@router.get("/api/v1/obsidian/tag-mapping/preview")
async def preview_tag_mapping(request: Request) -> Any:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    return JSONResponse(await _store(request).preview())


@router.get("/api/v1/obsidian/tag-mapping/rules")
async def list_tag_rules(request: Request) -> Any:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    return JSONResponse({"rules": await _store(request).rules()})


@router.put("/api/v1/obsidian/tag-mapping/rules", status_code=200)
async def put_tag_rule(payload: dict[str, Any], request: Request) -> Any:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    try:
        rule = await _store(request).put_rule(
            payload.get("sourceTag"), payload.get("targetTag")
        )
    except TagMappingInvalid as exc:
        return _error(400, "invalid_tag_mapping", str(exc))
    return JSONResponse(rule)


@router.delete("/api/v1/obsidian/tag-mapping/rules")
async def delete_tag_rule(request: Request, sourceTag: str = "") -> Any:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    try:
        deleted = await _store(request).delete_rule(sourceTag)
    except TagMappingInvalid as exc:
        return _error(400, "invalid_tag_mapping", str(exc))
    if not deleted:
        return _error(404, "tag_rule_not_found", "映射规则不存在。")
    return JSONResponse({"deleted": True})


@router.post("/api/v1/obsidian/tag-mapping/materialize")
async def materialize_tag_mapping(request: Request) -> Any:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    return JSONResponse(await _store(request).materialize())


@router.get("/api/v1/obsidian/tag-mapping/import")
async def import_layer(request: Request, tag: str = "") -> Any:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    store = _store(request)
    if tag.strip():
        return JSONResponse({"notes": await store.notes_with_tag(tag)})
    return JSONResponse({"tags": await store.import_overview()})
