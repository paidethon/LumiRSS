"""NEW-328 库同步冲突收件箱路由 — 修正层 / 检测 / 收件箱 / 显式解决。

- PUT    /api/v1/obsidian/conflict-inbox/corrections   {noteUuid, personalTitle?, personalNote?}
- GET    /api/v1/obsidian/conflict-inbox/corrections   修正层列表（含 stale 标志）
- DELETE /api/v1/obsidian/conflict-inbox/corrections?noteUuid=
- POST   /api/v1/obsidian/conflict-inbox/detect        源更新 vs 个人修正检测
- GET    /api/v1/obsidian/conflict-inbox               open 冲突（并排数据）
- POST   /api/v1/obsidian/conflict-inbox/{id}/resolve  {decision}
- GET    /api/v1/obsidian/conflict-inbox/history       已解决冲突留档

个人修正是 Lumi 侧独立层，绝不写 Vault；解决必须显式二选一。
owner 门槛（O168）。
"""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from lumirss.new328_conflict_inbox import (
    ConflictInboxStore,
    ConflictInvalid,
    ConflictNotFound,
    NoteNotFoundInProjection,
)
from lumirss.routers.obsidian import _require_owner

router = APIRouter()


def _store(request: Request) -> ConflictInboxStore:
    return ConflictInboxStore(request.app.state.db)


@router.put("/api/v1/obsidian/conflict-inbox/corrections")
async def put_correction(payload: dict[str, Any], request: Request) -> Any:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    try:
        correction = await _store(request).put_correction(
            str(payload.get("noteUuid") or ""),
            str(payload.get("personalTitle") or ""),
            str(payload.get("personalNote") or ""),
        )
    except NoteNotFoundInProjection:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "type": "note_not_found",
                    "message": "投影中没有该笔记，无法建立个人修正。",
                }
            },
        )
    except ConflictInvalid as exc:
        return JSONResponse(
            status_code=400,
            content={"error": {"type": "invalid_correction", "message": str(exc)}},
        )
    return JSONResponse(correction)


@router.get("/api/v1/obsidian/conflict-inbox/corrections")
async def list_corrections(request: Request) -> Any:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    return JSONResponse({"corrections": await _store(request).list_corrections()})


@router.delete("/api/v1/obsidian/conflict-inbox/corrections")
async def delete_correction(request: Request, noteUuid: str = "") -> Any:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    deleted = await _store(request).delete_correction(noteUuid)
    if not deleted:
        return JSONResponse(
            status_code=404,
            content={
                "error": {"type": "correction_not_found", "message": "个人修正不存在。"}
            },
        )
    return JSONResponse({"deleted": True})


@router.post("/api/v1/obsidian/conflict-inbox/detect")
async def detect_conflicts(request: Request) -> Any:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    return JSONResponse(await _store(request).detect())


@router.get("/api/v1/obsidian/conflict-inbox")
async def list_conflict_inbox(request: Request) -> Any:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    return JSONResponse({"conflicts": await _store(request).list_open()})


@router.post("/api/v1/obsidian/conflict-inbox/{conflict_id}/resolve")
async def resolve_conflict(
    conflict_id: str, payload: dict[str, Any], request: Request
) -> Any:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    try:
        result = await _store(request).resolve(
            conflict_id, str(payload.get("decision") or "")
        )
    except ConflictNotFound:
        return JSONResponse(
            status_code=404,
            content={
                "error": {"type": "conflict_not_found", "message": "冲突不存在。"}
            },
        )
    except ConflictInvalid as exc:
        return JSONResponse(
            status_code=400,
            content={
                "error": {"type": "invalid_conflict_resolution", "message": str(exc)}
            },
        )
    return JSONResponse(result)


@router.get("/api/v1/obsidian/conflict-inbox/history")
async def conflict_history(request: Request) -> Any:
    guard = await _require_owner(request)
    if guard is not None:
        return guard
    return JSONResponse({"history": await _store(request).history()})
