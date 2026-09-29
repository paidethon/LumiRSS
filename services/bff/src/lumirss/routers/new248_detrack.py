"""NEW-248 来源链接去追踪预览路由 — 预览 / 用户保留参数管理。

- POST   /api/v1/links/detrack-preview               预览（纯计算，零写入）：
       removed（将移除的已知追踪参数）/ keptRequired（签名/授权 + 清单外
       未知，保守保留）/ keptUser（用户标记保留）/ cleanedUrl；
- GET    /api/v1/links/detrack-kept-params            用户保留参数列表；
- PUT    /api/v1/links/detrack-kept-params/{param}    标记保留（理由可选）；
- DELETE /api/v1/links/detrack-kept-params/{param}    撤销保留（恢复可移除态）。

绝不删除登录或内容选择必需参数：它们不在追踪清单里，预览永远归入
keptRequired。负载非法 → 422 detrack_invalid。per-user 库天然隔离。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.new248_detrack import DetrackInvalid, DetrackStore

router = APIRouter()


class DetrackPreview(BaseModel):
    model_config = {"extra": "forbid"}

    url: str = Field(min_length=1, max_length=4000)


class DetrackKeptPut(BaseModel):
    model_config = {"extra": "forbid"}

    reason: str = Field(default="", max_length=300)


def _store(request: Request) -> DetrackStore:
    return DetrackStore(request.app.state.db)


def _invalid(message: str) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": {"type": "detrack_invalid", "message": message}},
    )


@router.post("/api/v1/links/detrack-preview")
async def run_detrack_preview(payload: DetrackPreview, request: Request) -> Response:
    try:
        result = await _store(request).preview(payload.url)
    except DetrackInvalid as exc:
        return _invalid(str(exc))
    return JSONResponse(result)


@router.get("/api/v1/links/detrack-kept-params")
async def list_kept_params(request: Request) -> Response:
    return JSONResponse({"items": await _store(request).list_kept_params()})


@router.put("/api/v1/links/detrack-kept-params/{param}")
async def put_kept_param(param: str, payload: DetrackKeptPut, request: Request) -> Response:
    try:
        item = await _store(request).put_kept_param(param, payload.reason)
    except DetrackInvalid as exc:
        return _invalid(str(exc))
    return JSONResponse(item)


@router.delete("/api/v1/links/detrack-kept-params/{param}", status_code=204)
async def delete_kept_param(param: str, request: Request) -> Response:
    try:
        await _store(request).delete_kept_param(param)
    except DetrackInvalid as exc:
        return _invalid(str(exc))
    return Response(status_code=204)
