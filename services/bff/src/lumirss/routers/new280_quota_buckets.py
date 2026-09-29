"""NEW-280 AI 配额分桶路由 — 分桶 CRUD + 用量快照。

- PUT  /api/v1/ai/quota/buckets/{purpose}  {maxCalls} → 200
- DELETE /api/v1/ai/quota/buckets/{purpose} → 204（取消分桶 = 沿用全局）
- GET  /api/v1/ai/quota/buckets            → 快照（每桶 used/remaining/nearLimit）
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.new280_quota_buckets import (
    BucketInvalid,
    BucketPurposeInvalid,
    QuotaBucketStore,
)

router = APIRouter()


class BucketSetBody(BaseModel):
    model_config = {"extra": "forbid"}

    maxCalls: int = Field(ge=1, le=100000)


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


def _store(request: Request) -> QuotaBucketStore:
    return QuotaBucketStore(request.app.state.db)


@router.put("/api/v1/ai/quota/buckets/{purpose}")
async def put_quota_bucket(
    purpose: str, payload: BucketSetBody, request: Request
) -> Response:
    try:
        result = await _store(request).set_bucket(purpose, payload.maxCalls)
    except BucketPurposeInvalid as exc:
        return _error(422, "invalid_bucket_purpose", str(exc))
    except BucketInvalid as exc:
        return _error(422, "invalid_bucket_payload", str(exc))
    return JSONResponse(result, status_code=200)


@router.delete("/api/v1/ai/quota/buckets/{purpose}", status_code=204)
async def delete_quota_bucket(purpose: str, request: Request) -> Response:
    try:
        deleted = await _store(request).delete_bucket(purpose)
    except BucketPurposeInvalid as exc:
        return _error(422, "invalid_bucket_purpose", str(exc))
    if not deleted:
        return _error(404, "bucket_not_found", "该用途没有分桶。")
    return Response(status_code=204)


@router.get("/api/v1/ai/quota/buckets")
async def get_quota_buckets(request: Request) -> Response:
    from lumirss.ai_settings import KEY_QUOTA_WINDOW, AiSettingsStore

    values = await AiSettingsStore(request.app.state.db).load()
    window = values[KEY_QUOTA_WINDOW] or "day"
    return JSONResponse(await _store(request).snapshot(window))
