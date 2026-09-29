"""NEW-317 剪藏重复合并路由 — 分组预览（零写入）+ 显式合并 + 台账。

- GET  /api/v1/library/clip-duplicates → 同页候选组（保守归一化）
- POST /api/v1/library/clips/merge {keepRef, mergeRefs[], metaPolicy} → 合并
- GET  /api/v1/library/clip-duplicates/merges → 合并台账（只追加）
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.library_clips import ClipNotFound
from lumirss.new317_clip_merge import ClipMergeInvalid, ClipMergeStore

router = APIRouter()


class MergeBody(BaseModel):
    model_config = {"extra": "forbid"}

    keepRef: str = Field(min_length=9, max_length=100)
    mergeRefs: list[str] = Field(min_length=1, max_length=20)
    metaPolicy: str = Field(default="kept", pattern="^(kept|newest)$")


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


def _store(request: Request) -> ClipMergeStore:
    return ClipMergeStore(request.app.state.db)


@router.get("/api/v1/library/clip-duplicates")
async def list_duplicate_groups(request: Request) -> Response:
    return JSONResponse(await _store(request).list_groups())


@router.post("/api/v1/library/clips/merge")
async def merge_duplicates(payload: MergeBody, request: Request) -> Response:
    try:
        return JSONResponse(
            await _store(request).merge(
                payload.keepRef, payload.mergeRefs, payload.metaPolicy
            )
        )
    except ClipNotFound:
        return _error(404, "clip_not_found", "要合并的剪藏不存在。")
    except ClipMergeInvalid as exc:
        return _error(422, "invalid_merge_group", str(exc))


@router.get("/api/v1/library/clip-duplicates/merges")
async def list_merges(request: Request) -> Response:
    return JSONResponse({"merges": await _store(request).list_merges()})
