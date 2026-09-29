"""NEW-294 通讯订阅来源映射路由 — 地址 → 个人资料来源 + 来源视图过滤。

- GET    /api/v1/email-source-maps            → 映射清单 + 诚实口径
- PUT    /api/v1/email-source-maps/{fromAddr} {sourceLabel} → 设置/更新
- DELETE /api/v1/email-source-maps/{fromAddr} → 取消映射（204/404）
- GET    /api/v1/email-materials?source=…     → 该来源视图（291 清单复用）
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.new294_email_source_maps import (
    SourceMapInvalid,
    SourceMapStore,
)

router = APIRouter()


class SourceMapBody(BaseModel):
    model_config = {"extra": "forbid"}

    sourceLabel: str = Field(min_length=1, max_length=120)


@router.get("/api/v1/email-source-maps")
async def get_source_maps(request: Request) -> Response:
    return JSONResponse(await SourceMapStore(request.app.state.db).list_maps())


@router.put("/api/v1/email-source-maps/{from_addr}")
async def put_source_map(
    from_addr: str, payload: SourceMapBody, request: Request
) -> Response:
    try:
        result = await SourceMapStore(request.app.state.db).set_map(
            from_addr, payload.sourceLabel
        )
    except SourceMapInvalid as exc:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "source_map_invalid", "message": str(exc)}},
        )
    return JSONResponse(result)


@router.delete("/api/v1/email-source-maps/{from_addr}", status_code=204)
async def delete_source_map(from_addr: str, request: Request) -> Response:
    try:
        deleted = await SourceMapStore(request.app.state.db).delete_map(from_addr)
    except SourceMapInvalid as exc:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "source_map_invalid", "message": str(exc)}},
        )
    if not deleted:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "type": "source_map_not_found",
                    "message": "这个地址没有映射。",
                }
            },
        )
    return Response(status_code=204)
