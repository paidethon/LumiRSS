"""NEW-307 自动接入来源配额路由。

- PUT    /api/v1/api-sources/{uuid}/intake-quota {maxItemsPerDay} → 200
- DELETE /api/v1/api-sources/{uuid}/intake-quota → 204（取消 = 不限）
- GET    /api/v1/api-sources/{uuid}/intake-quota → 现状（used/pending/remaining）

发布的拦截点在 feed 发布路径（routers/api_sources 集成 IntakeQuota
Store.claim）—— 到限只发布剩余名额，超出进 pending。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.api_sources import ApiSourceNotFound
from lumirss.new307_intake_quota import (
    IntakeQuotaInvalid,
    IntakeQuotaStore,
)

router = APIRouter()


class IntakeQuotaBody(BaseModel):
    model_config = {"extra": "forbid"}

    maxItemsPerDay: int = Field(ge=1, le=100000)


def _stores(request: Request):
    from lumirss.api_source_store import ApiSourceStore

    return (
        ApiSourceStore(request.app.state.db),
        IntakeQuotaStore(request.app.state.db),
    )


@router.put("/api/v1/api-sources/{source_uuid}/intake-quota")
async def put_intake_quota(
    source_uuid: str, payload: IntakeQuotaBody, request: Request
) -> Response:
    source_store, quota_store = _stores(request)
    if await source_store.get(source_uuid) is None:
        raise ApiSourceNotFound(source_uuid)
    try:
        result = await quota_store.set_quota(source_uuid, payload.maxItemsPerDay)
    except IntakeQuotaInvalid as exc:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "invalid_intake_quota", "message": str(exc)}},
        )
    return JSONResponse(result)


@router.delete("/api/v1/api-sources/{source_uuid}/intake-quota", status_code=204)
async def delete_intake_quota(source_uuid: str, request: Request) -> Response:
    source_store, quota_store = _stores(request)
    if await source_store.get(source_uuid) is None:
        raise ApiSourceNotFound(source_uuid)
    if not await quota_store.delete_quota(source_uuid):
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "intake_quota_not_found", "message": "该来源没有配额。"}},
        )
    return Response(status_code=204)


@router.get("/api/v1/api-sources/{source_uuid}/intake-quota")
async def get_intake_quota(source_uuid: str, request: Request) -> Response:
    source_store, quota_store = _stores(request)
    if await source_store.get(source_uuid) is None:
        raise ApiSourceNotFound(source_uuid)
    return JSONResponse(await quota_store.snapshot(source_uuid))
