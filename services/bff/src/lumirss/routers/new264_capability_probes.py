"""NEW-264 翻译服务能力比较路由 — 用户样本对已配置服务的显式对照。

- POST /api/v1/translation/capability-probe
      body {samples:[str,...]} （1..5 段、每段 ≤500 字符）→ 逐侧逐样本
      结果/耗时/错误。零缓存写入；绝不自动发送整库。
- GET  /api/v1/translation/capability-probe?limit=10  本人最近报告（新→旧）。

无已配置服务 → 200 + available=false + 诚实 reason（不臆造结果）；
样本越界 → 422。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.deps import _get_segment_service, _provider_factory_for
from lumirss.new264_capability_probes import (
    ProbeInvalid,
    get_probe,
    list_probes,
    run_probe,
)

router = APIRouter()


class ProbeBody(BaseModel):
    model_config = {"extra": "forbid"}

    samples: list[str] = Field(min_length=1, max_length=5)


def _invalid(exc: ProbeInvalid) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": {"type": "probe_invalid", "message": str(exc)}},
    )


@router.post("/api/v1/translation/capability-probe", response_model=None)
async def post_capability_probe(
    payload: ProbeBody, request: Request
) -> dict[str, object] | JSONResponse:
    """对用户显式提交的少量样本做一次能力对照（已配置两侧逐样本运行）。"""
    try:
        service = _get_segment_service(request)
        settings = await service._resolve_settings()
        report = await run_probe(
            request.app.state.db,
            settings,
            payload.samples,
            _provider_factory_for(request, "translation"),
            secrets=request.app.state.secrets_store,
        )
    except ProbeInvalid as exc:
        return _invalid(exc)
    return {
        "id": report.id,
        "samples": report.samples,
        "sides": report.sides,
        "available": report.available,
        "reason": report.reason,
        "createdAt": report.created_at,
    }


@router.get("/api/v1/translation/capability-probe")
async def get_capability_probes(request: Request, limit: int = 10) -> dict[str, object]:
    """本人最近的能力探测报告（新→旧；per-user 库天然隔离）。"""
    items = await list_probes(request.app.state.db, limit)
    return {"probes": items}


@router.get("/api/v1/translation/capability-probe/{probe_id}")
async def get_capability_probe(probe_id: str, request: Request) -> dict[str, object]:
    """单份报告回看；未知 id → 404。"""
    item = await get_probe(request.app.state.db, probe_id)
    if item is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": {"type": "probe_not_found", "message": "报告不存在。"}
            },
        )
    return item
