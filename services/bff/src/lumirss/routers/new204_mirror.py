"""NEW-204 订阅镜像比对路由（只读 compare + 抉择台账）。"""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.feed_preview import (
    FeedFetchError,
    FeedTooLarge,
    NotAFeedError,
    UnsafeFeedUrl,
    safe_fetch,
)
from lumirss.new204_mirror import (
    MirrorChoiceStore,
    MirrorCompareInvalid,
    compare_sides,
    summarize_feed_document,
)

router = APIRouter()

_FETCH_ERRORS = (UnsafeFeedUrl, FeedFetchError, FeedTooLarge, NotAFeedError)


def _store(request: Request) -> MirrorChoiceStore:
    return MirrorChoiceStore(request.app.state.db)


class MirrorCompareRequest(BaseModel):
    """POST /api/v1/new204/compare body（两个候选 feed URL）。"""

    model_config = {"extra": "forbid"}

    urlA: str = Field(min_length=1)
    urlB: str = Field(min_length=1)


class MirrorChoiceRequest(BaseModel):
    """POST /api/v1/new204/choices body（比对后确认选用哪边）。"""

    model_config = {"extra": "forbid"}

    urlA: str = Field(min_length=1)
    urlB: str = Field(min_length=1)
    picked: str
    note: str | None = None


class MirrorSideSummary(BaseModel):
    title: str | None = None
    entryCount: int | None = None
    comparedEntries: list[dict[str, Any]] = []
    error: str | None = None


class MirrorCompareResponse(BaseModel):
    sideA: MirrorSideSummary
    sideB: MirrorSideSummary
    comparison: dict[str, Any] | None
    note: str


async def _summarize_side(request: Request, url: str) -> dict[str, Any]:
    """一侧探测：injected probe（app.state.new204_fetch，测试注入口）
    或既有 safe-fetch 边界；解析离线；失败 → error 字段。"""
    injected = getattr(request.app.state, "new204_fetch", None)
    try:
        if injected is not None:
            document = await injected(url)
        else:
            document = await safe_fetch(url)
        body = document.body if hasattr(document, "body") else document
        return summarize_feed_document(body)
    except _FETCH_ERRORS as exc:
        return {"error": str(exc)}
    except Exception as exc:  # noqa: BLE001 — 诊断面：单侧故障绝不 500 整个比对
        return {"error": f"{type(exc).__name__}: {exc}"}


@router.post("/api/v1/new204/compare", response_model=MirrorCompareResponse)
async def compare_mirrors(payload: MirrorCompareRequest, request: Request) -> Any:
    """并排比对两个候选 feed 的最近条目覆盖（只读；一侧失败不掩盖另一侧）。"""
    if payload.urlA == payload.urlB:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "type": "mirror_same_url",
                    "message": "两个候选 URL 相同，无需比对。",
                }
            },
        )
    side_a = await _summarize_side(request, payload.urlA)
    side_b = await _summarize_side(request, payload.urlB)
    comparison = compare_sides(
        side_a if "error" not in side_a else None,
        side_b if "error" not in side_b else None,
    )
    return MirrorCompareResponse(
        sideA=MirrorSideSummary(**side_a),
        sideB=MirrorSideSummary(**side_b),
        comparison=comparison,
        note=(
            "探测经既有 safe-fetch 边界（SSRF 防护/有界 body），离线解析；"
            "订阅动作走 POST /api/v1/subscriptions（本端点不代订）。"
        ),
    )


@router.post("/api/v1/new204/choices", status_code=201)
async def record_mirror_choice(payload: MirrorChoiceRequest, request: Request) -> Any:
    """记录抉择台账（比对后用户确认选用哪边；订阅走既有端点）。"""
    try:
        choice = await _store(request).record(
            url_a=payload.urlA,
            url_b=payload.urlB,
            picked_side=payload.picked,
            note=payload.note,
        )
    except MirrorCompareInvalid as exc:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "invalid_mirror_choice", "message": str(exc)}},
        )
    return {**choice, "note": "抉择已记录；订阅请走 POST /api/v1/subscriptions。"}


@router.get("/api/v1/new204/choices")
async def list_mirror_choices(request: Request) -> dict[str, Any]:
    """抉择台账（新→旧，≤20）。"""
    choices = await _store(request).list_choices()
    return {"items": choices}
