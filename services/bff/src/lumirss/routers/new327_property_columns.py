"""NEW-327 笔记属性列映射路由 — 可用字段 / 列映射 / 按属性筛选。

- GET    /api/v1/obsidian/property-columns             可用字段 + 已配置列
- PUT    /api/v1/obsidian/property-columns             upsert 列映射
- DELETE /api/v1/obsidian/property-columns?field=
- GET    /api/v1/obsidian/property-columns/notes?field=&value=  按属性筛选

属性是扫描时的只读投影；原文件格式保持不变。owner 门槛（O168）。
"""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from lumirss.new327_property_columns import (
    PropertyColumnInvalid,
    PropertyColumnStore,
)
from lumirss.routers.obsidian import _require_owner

router = APIRouter()


def _store(request: Request) -> PropertyColumnStore:
    return PropertyColumnStore(request.app.state.db)


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


@router.get("/api/v1/obsidian/property-columns")
async def list_property_columns(request: Request) -> Any:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    store = _store(request)
    return JSONResponse(
        {
            "fields": await store.available_fields(),
            "columns": await store.list_columns(),
        }
    )


@router.put("/api/v1/obsidian/property-columns")
async def put_property_column(payload: dict[str, Any], request: Request) -> Any:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    try:
        column = await _store(request).put_column(
            str(payload.get("field") or ""),
            label=str(payload.get("label") or ""),
            visible=bool(payload.get("visible", True)),
            filterable=bool(payload.get("filterable", False)),
            position=payload.get("position", 0),
        )
    except PropertyColumnInvalid as exc:
        return _error(400, "invalid_property_column", str(exc))
    except TypeError:
        return _error(400, "invalid_property_column", "position 必须是整数。")
    return JSONResponse(column)


@router.delete("/api/v1/obsidian/property-columns")
async def delete_property_column(request: Request, field: str = "") -> Any:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    try:
        deleted = await _store(request).delete_column(field)
    except PropertyColumnInvalid as exc:
        return _error(400, "invalid_property_column", str(exc))
    if not deleted:
        return _error(404, "property_column_not_found", "列映射不存在。")
    return JSONResponse({"deleted": True})


@router.get("/api/v1/obsidian/property-columns/notes")
async def filter_notes_by_property(request: Request, field: str = "", value: str = "") -> Any:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    try:
        return JSONResponse(await _store(request).filtered_notes(field, value))
    except PropertyColumnInvalid as exc:
        return _error(400, "invalid_property_column", str(exc))
