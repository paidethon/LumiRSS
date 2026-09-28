"""NEW-231 笔记修订对照路由 — 快照 / 版本列表 / 差异 / 恢复（留记录）。

- POST /api/v1/library/notes/{note_id}/versions            手动快照当前版；
- GET  /api/v1/library/notes/{note_id}/versions            版本列表 + 当前版；
- GET  /api/v1/library/notes/{note_id}/versions/diff       两版逐行差异
      （from/to 为版本 id 或 'current'；省略 to → 与 current 比）；
- POST /api/v1/library/notes/{note_id}/versions/{ref}/restore  恢复某版
      （恢复前自动快照当前版；恢复记录进 note_restore_log）；
- GET  /api/v1/library/notes/{note_id}/versions/restores   恢复记录。

笔记或版本不存在 → 404 note_version_not_found；per-user 库天然隔离。
"""

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response

from lumirss.new231_note_versions import (
    NoteVersionNotFound,
    NoteVersionStore,
)

router = APIRouter()


def _store(request: Request) -> NoteVersionStore:
    return NoteVersionStore(request.app.state.db)


def _not_found(message: str) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"error": {"type": "note_version_not_found", "message": message}},
    )


@router.post("/api/v1/library/notes/{note_id}/versions", status_code=201)
async def snapshot_note_version(note_id: str, request: Request) -> Response:
    """手动快照当前版（origin='manual'）。"""
    try:
        item = await _store(request).snapshot(note_id)
    except NoteVersionNotFound:
        return _not_found("笔记不存在。")
    return JSONResponse(status_code=201, content=item)


@router.get("/api/v1/library/notes/{note_id}/versions")
async def list_note_versions(note_id: str, request: Request) -> Response:
    try:
        result = await _store(request).list_versions(note_id)
    except NoteVersionNotFound:
        return _not_found("笔记不存在。")
    return JSONResponse(result)


@router.get("/api/v1/library/notes/{note_id}/versions/diff")
async def diff_note_versions(
    note_id: str,
    request: Request,
    fromVersion: str = Query(...),
    toVersion: str | None = Query(None),
) -> Response:
    """两版逐行差异；toVersion 缺省 = 与 current 比。同一版本自身 →
    identical=true、零增删（诚实空 diff）。"""
    store = _store(request)
    try:
        from_version = await store.get_version(note_id, fromVersion)
        to_version = await store.get_version(note_id, toVersion or "current")
    except NoteVersionNotFound:
        return _not_found("版本不存在。")
    result = NoteVersionStore.diff_versions(from_version, to_version)
    return JSONResponse(
        {
            "noteId": note_id,
            "fromVersion": from_version["ref"],
            "toVersion": to_version["ref"],
            **result,
        }
    )


@router.post("/api/v1/library/notes/{note_id}/versions/{version_ref}/restore")
async def restore_note_version(
    note_id: str, version_ref: str, request: Request
) -> Response:
    """恢复某版；恢复前当前版自动快照（pre_restore），恢复动作进台账。
    version_ref='current' 恢复当前版 = 无意义，422 拒绝。"""
    if version_ref == "current":
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "type": "invalid_note_version",
                    "message": "不能恢复 current（它就是当前内容）。",
                }
            },
        )
    try:
        result = await _store(request).restore(note_id, version_ref)
    except NoteVersionNotFound:
        return _not_found("笔记或版本不存在。")
    return JSONResponse(result)


@router.get("/api/v1/library/notes/{note_id}/versions/restores")
async def note_restore_log(note_id: str, request: Request) -> Response:
    """恢复记录台账（新→旧）。"""
    store = _store(request)
    try:
        await store.list_versions(note_id)  # 存在性校验
    except NoteVersionNotFound:
        return _not_found("笔记不存在。")
    items = await store.restore_log(note_id)
    return JSONResponse({"noteId": note_id, "items": items})
