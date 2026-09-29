"""NEW-223 队列工作量预览路由。

估时 = 投影纯文本长度 ÷ 本人可校正阅读速度；响应恒带 basis 与
「估算，非精确」提示。压缩范围只是建议清单（用户挑选），服务端
绝不替用户裁队列。稳定错误信封：invalid_workload。
"""

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from lumirss.new223_workload import WorkloadInvalid, WorkloadStore

router = APIRouter()


def _store(request: Request) -> WorkloadStore:
    return WorkloadStore(request.app.state.db)


class SpeedView(BaseModel):
    charsPerMinute: int
    customized: bool
    updatedAt: str | None = None
    note: str | None = None


class SpeedUpdateRequest(BaseModel):
    model_config = {"extra": "forbid"}

    charsPerMinute: int = Field(ge=50, le=2000)
    """本人实际阅读速度（字符/分钟）；人工校正，不是精度表演。"""


class EstimateItemView(BaseModel):
    itemRef: str
    title: str | None = None
    minutes: int | None = None
    """null = 无投影文本（诚实未知，绝不瞎猜）。"""


class EstimateResponse(BaseModel):
    charsPerMinute: int
    items: list[EstimateItemView]
    totalKnownMinutes: int
    unknownCount: int
    basis: str
    note: str


class CompressionOption(BaseModel):
    key: str
    label: str
    refs: list[str]
    estimatedMinutes: int


class CompressionResponse(BaseModel):
    charsPerMinute: int
    options: list[CompressionOption]
    basis: str
    note: str


class EstimateRequest(BaseModel):
    model_config = {"extra": "forbid"}

    refs: list[str] = Field(min_length=1, max_length=200)


@router.get("/api/v1/queue/workload/speed", response_model=SpeedView)
async def get_reading_speed(request: Request) -> SpeedView:
    """当前阅读速度（未校正时返回缺省 400 并明示）。"""
    return SpeedView(**await _store(request).get_speed())


@router.put("/api/v1/queue/workload/speed", response_model=SpeedView)
async def set_reading_speed(
    payload: SpeedUpdateRequest, request: Request
) -> SpeedView:
    """校正本人阅读速度（50..2000 字符/分钟）。"""
    return SpeedView(**await _store(request).set_speed(payload.charsPerMinute))


@router.post("/api/v1/queue/workload/estimate", response_model=EstimateResponse)
async def estimate_workload(
    payload: EstimateRequest, request: Request
) -> EstimateResponse:
    """按本人速度估算给定材料集合的时长（逐篇 + 合计 + unknown）。"""
    return EstimateResponse(**await _store(request).estimate(payload.refs))


@router.post("/api/v1/queue/workload/compressions", response_model=CompressionResponse)
async def suggest_compressions(
    payload: EstimateRequest, request: Request
) -> CompressionResponse:
    """压缩范围建议清单（保持全部/前半/剔除最长/只留短文）——用户挑。"""
    return CompressionResponse(**await _store(request).compressions(payload.refs))


__all__ = ["router", "WorkloadInvalid"]
