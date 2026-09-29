"""NEW-265 翻译任务预算预估路由 — 提交前的字数与费用估价（只读）。

- GET  /api/v1/translation/budget/settings      本人登记的估算单价
- PUT  /api/v1/translation/budget/settings      登记/清除（price=null）单价
- POST /api/v1/translation/budget/estimate      对提交范围做只读预检
      body {entryRef?, blocks:[{index,text}]} →
      {totalBlocks, chargeableBlocks, cachedBlocks, noTranslateBlocks,
       revisedBlocks, totalChars, chargeableChars, estimatedCost?,
       pricePer1kChars, currency, engine, note}

预检绝不调用 provider、绝不写缓存行。未登记单价 → estimatedCost=null
+ 诚实说明；browser 引擎 → 422 诚实不可用（服务端不翻译）。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.ai_translation_segments import SegmentInput
from lumirss.deps import _get_segment_service
from lumirss.entryref import decode_entry_ref
from lumirss.new265_budget_estimate import (
    BudgetEngineUnavailable,
    BudgetInvalid,
    estimate,
    get_budget_settings,
    save_budget_settings,
)

router = APIRouter()


class BudgetSettingsBody(BaseModel):
    model_config = {"extra": "forbid"}

    pricePer1kChars: float | None = Field(default=None, ge=0)
    currency: str = Field(default="", max_length=12)


class BudgetBlockIn(BaseModel):
    index: int = Field(ge=0, le=63)
    text: str = Field(min_length=1, max_length=20000)


class BudgetEstimateBody(BaseModel):
    model_config = {"extra": "forbid"}

    entryRef: str | None = Field(default=None, max_length=200)
    blocks: list[BudgetBlockIn] = Field(min_length=1, max_length=64)


def _settings_view(row) -> dict[str, object]:
    return {
        "pricePer1kChars": row.price_per_1k_chars,
        "currency": row.currency,
        "updatedAt": row.updated_at,
    }


def _estimate_view(item) -> dict[str, object]:
    return {
        "totalBlocks": item.total_blocks,
        "chargeableBlocks": item.chargeable_blocks,
        "cachedBlocks": item.cached_blocks,
        "noTranslateBlocks": item.no_translate_blocks,
        "revisedBlocks": item.revised_blocks,
        "totalChars": item.total_chars,
        "chargeableChars": item.chargeable_chars,
        "pricePer1kChars": item.price_per_1k_chars,
        "currency": item.currency,
        "estimatedCost": item.estimated_cost,
        "engine": item.engine,
        "note": item.note,
    }


def _invalid(exc: Exception, type_name: str) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": {"type": type_name, "message": str(exc)}},
    )


@router.get("/api/v1/translation/budget/settings")
async def get_budget_settings_route(request: Request) -> dict[str, object]:
    """本人登记的估算单价（未登记 → price null）。"""
    row = await get_budget_settings(request.app.state.db)
    return _settings_view(row)


@router.put("/api/v1/translation/budget/settings", response_model=None)
async def put_budget_settings_route(
    payload: BudgetSettingsBody, request: Request
) -> dict[str, object] | JSONResponse:
    """登记/清除估算单价（价格必须是正数；清除后 estimatedCost 回到 null）。"""
    try:
        row = await save_budget_settings(
            request.app.state.db, payload.pricePer1kChars, payload.currency
        )
    except BudgetInvalid as exc:
        return _invalid(exc, "budget_invalid")
    return _settings_view(row)


@router.post("/api/v1/translation/budget/estimate", response_model=None)
async def post_budget_estimate(
    payload: BudgetEstimateBody, request: Request
) -> dict[str, object] | JSONResponse:
    """对用户即将提交的范围做只读预算预估（零 provider 调用）。"""
    if payload.entryRef:
        decode_entry_ref(payload.entryRef)  # 400 on malformed refs
    service = _get_segment_service(request)
    settings = await service._resolve_settings()
    blocks = [
        SegmentInput(index=b.index, text=b.text) for b in payload.blocks
    ]
    try:
        item = await estimate(
            request.app.state.db,
            settings,
            blocks,
            payload.entryRef or "",
        )
    except BudgetInvalid as exc:
        return _invalid(exc, "budget_invalid")
    except BudgetEngineUnavailable as exc:
        return _invalid(exc, "budget_engine_unavailable")
    return _estimate_view(item)
