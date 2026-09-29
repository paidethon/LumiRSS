"""NEW-278 AI 输入隐私过滤路由 — 排除清单 + 过滤差异预览。

- GET /api/v1/ai/privacy-filters → 当前排除清单 + 可选字段 + 诚实口径
- PUT /api/v1/ai/privacy-filters {exclude: [...]} → 全量替换（可空）
- POST /api/v1/ai/privacy-filters/diff {entryRef, purpose, maxChars?, note?}
      → 未过滤 vs 过滤后的分段差异（差异 = 你勾选的字段，不是内容侦测）
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.entryref import decode_entry_ref
from lumirss.new271_input_preview import (
    build_conversation_preview,
    build_summary_preview,
)
from lumirss.new278_privacy_filters import (
    InvalidPrivacyFilter,
    PrivacyFilterStore,
    filter_diff,
)

router = APIRouter()


class PrivacyFilterBody(BaseModel):
    model_config = {"extra": "forbid"}

    exclude: list[str]


class PrivacyDiffBody(BaseModel):
    model_config = {"extra": "forbid"}

    entryRef: str = Field(min_length=1, max_length=200)
    purpose: str
    maxChars: int | None = Field(default=None, ge=512, le=50000)
    note: str | None = Field(default=None, max_length=2000)


@router.get("/api/v1/ai/privacy-filters")
async def get_privacy_filters(request: Request) -> Response:
    store = PrivacyFilterStore(request.app.state.db)
    return JSONResponse(store.view(await store.list_exclusions()))


@router.put("/api/v1/ai/privacy-filters")
async def put_privacy_filters(
    payload: PrivacyFilterBody, request: Request
) -> Response:
    try:
        result = await PrivacyFilterStore(request.app.state.db).set_exclusions(
            payload.exclude
        )
    except InvalidPrivacyFilter as exc:
        return JSONResponse(
            status_code=422,
            content={
                "error": {"type": "invalid_privacy_filter", "message": str(exc)}
            },
        )
    return JSONResponse(result)


@router.post("/api/v1/ai/privacy-filters/diff")
async def post_privacy_diff(payload: PrivacyDiffBody, request: Request) -> Response:
    """过滤差异预览：同一输入在「不过滤」与「当前勾选」下的对比。"""
    decode_entry_ref(payload.entryRef)
    if payload.purpose not in ("summary", "conversation"):
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "type": "invalid_preview_purpose",
                    "message": "purpose 必须是 summary 或 conversation。",
                }
            },
        )
    from lumirss.deps import _get_conversation_service, _get_summary_service

    store = PrivacyFilterStore(request.app.state.db)
    if payload.purpose == "summary":
        service = _get_summary_service(request)
        normalized, _identity = await service._resolve(payload.entryRef)
        unfiltered = build_summary_preview(
            content=normalized, max_chars=payload.maxChars
        )
    else:
        service = _get_conversation_service(request)
        inputs = await service.preview_inputs(
            payload.entryRef,
            question="",
            max_chars=payload.maxChars,
            note=payload.note,
            exclude=frozenset(),  # 差异基准 = 不过滤的全量构成
        )
        unfiltered = build_conversation_preview(inputs)
    result = await filter_diff(store, unfiltered.to_json()["sections"])
    return JSONResponse(
        {
            "purpose": payload.purpose,
            "unfilteredSections": unfiltered.to_json()["sections"],
            **result,
        }
    )
