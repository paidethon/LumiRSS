"""NEW-216 集合快照差异路由 —— 命名快照 capture/list/delete、两次快照
diff、按选择恢复成员。全部端点挂在既有集合（工作区）路径下，只触
per-user 库本地表。422 invalid_collection_snapshot / 404 snapshot_not_found。
"""

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.new216_collection_snapshots import (
    CollectionSnapshotInvalid,
    CollectionSnapshotNotFound,
    CollectionSnapshotStore,
)

router = APIRouter()


class CollectionSnapshotCapture(BaseModel):
    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1, max_length=100)


class CollectionSnapshotDiffRequest(BaseModel):
    model_config = {"extra": "forbid"}

    a: str = Field(min_length=1, max_length=64)
    b: str = Field(min_length=1, max_length=64)


class CollectionSnapshotRestoreRequest(BaseModel):
    model_config = {"extra": "forbid"}

    snapshotId: str = Field(min_length=1, max_length=64)
    refs: list[str] = Field(min_length=1, max_length=500)


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


def _store(request: Request) -> CollectionSnapshotStore:
    return CollectionSnapshotStore(request.app.state.db)


@router.post("/api/v1/workspaces/{workspace_id}/member-snapshots", status_code=201)
async def capture_member_snapshot(
    workspace_id: str, payload: CollectionSnapshotCapture, request: Request
) -> Response:
    try:
        result = await _store(request).capture(workspace_id, payload.name)
    except CollectionSnapshotInvalid as exc:
        return _error(422, "invalid_collection_snapshot", str(exc))
    return JSONResponse(status_code=201, content=result)


@router.get("/api/v1/workspaces/{workspace_id}/member-snapshots")
async def list_member_snapshots(workspace_id: str, request: Request) -> JSONResponse:
    return JSONResponse({"items": await _store(request).list_snapshots(workspace_id)})


@router.delete("/api/v1/workspaces/{workspace_id}/member-snapshots/{snapshot_id}", status_code=204)
async def delete_member_snapshot(
    workspace_id: str, snapshot_id: str, request: Request
) -> Response:
    deleted = await _store(request).delete(workspace_id, snapshot_id)
    if not deleted:
        return _error(404, "snapshot_not_found", "快照不存在。")
    return Response(status_code=204)


@router.post("/api/v1/workspaces/{workspace_id}/member-snapshots/diff")
async def diff_member_snapshots(
    workspace_id: str, payload: CollectionSnapshotDiffRequest, request: Request
) -> Response:
    try:
        result = await _store(request).diff(workspace_id, payload.a, payload.b)
    except CollectionSnapshotInvalid as exc:
        return _error(422, "invalid_collection_snapshot", str(exc))
    except CollectionSnapshotNotFound:
        return _error(404, "snapshot_not_found", "快照不存在。")
    return JSONResponse(result)


@router.post("/api/v1/workspaces/{workspace_id}/member-snapshots/restore")
async def restore_member_snapshot(
    workspace_id: str, payload: CollectionSnapshotRestoreRequest, request: Request
) -> Response:
    try:
        result = await _store(request).restore(workspace_id, payload.snapshotId, payload.refs)
    except CollectionSnapshotInvalid as exc:
        return _error(422, "invalid_collection_snapshot", str(exc))
    except CollectionSnapshotNotFound:
        return _error(404, "snapshot_not_found", "快照不存在。")
    return JSONResponse(result)
