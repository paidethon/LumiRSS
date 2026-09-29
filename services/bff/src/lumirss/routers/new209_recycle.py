"""NEW-209 订阅变动回收箱路由（退订捕获配置 → 限期保留 → 恢复/放弃）。"""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.deps import _get_control_adapter
from lumirss.new209_recycle import (
    BinRowNotFound,
    BinRowNotRestorable,
    UnsubscribeBinStore,
)
from lumirss.subscriptionref import (
    InvalidSubscriptionReference,
    decode_subscription_ref,
)
from lumirss.util import utc_now

router = APIRouter()

_BIN_NOTE = (
    "回收箱保存订阅配置（URL/标题/分类）；恢复=按原配置重新订阅"
    "（新代次），已被源站删除的正文不承诺恢复。purge_after 是建议清理"
    "日，过期行等待显式放弃，无后台自动清理。"
)


def _store(request: Request) -> UnsubscribeBinStore:
    return UnsubscribeBinStore(request.app.state.db)


class BinUnsubscribeRequest(BaseModel):
    """POST /api/v1/new209/unsubscribe body。"""

    model_config = {"extra": "forbid"}

    subscriptionRef: str = Field(min_length=1)
    keepDays: int = Field(ge=1, le=365)
    """配置保留天数（用户选择；过期只标注，不自动物理删除）。"""


class BinRowView(BaseModel):
    id: str
    feedUrl: str
    streamId: str
    title: str | None
    categoryId: str | None
    categoryLabel: str | None
    keepDays: int
    unsubscribedAt: str
    purgeAfter: str
    status: str
    restoredAt: str | None
    restoredStreamId: str | None
    discardedAt: str | None
    createdAt: str
    expired: bool = False


class BinList(BaseModel):
    items: list[BinRowView]
    note: str


def _not_found() -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"error": {"type": "bin_row_not_found", "message": "回收箱行不存在。"}},
    )


def _not_restorable() -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={
            "error": {
                "type": "bin_row_not_restorable",
                "message": "该行已恢复或已放弃，请刷新后重试。",
            }
        },
    )


def _view(row: dict[str, Any]) -> BinRowView:
    from lumirss.new209_recycle import is_expired

    return BinRowView(**row, expired=is_expired(row))


@router.post("/api/v1/new209/unsubscribe", status_code=201, response_model=BinRowView)
async def unsubscribe_to_bin(payload: BinUnsubscribeRequest, request: Request) -> Any:
    """退订进回收箱：解析订阅 → 捕获配置 → 上游退订 → 落箱。

    上游不可用/订阅不存在时不落箱、不退订（无半途状态）。"""
    try:
        stream_id = decode_subscription_ref(payload.subscriptionRef)
    except InvalidSubscriptionReference:
        return JSONResponse(
            status_code=400,
            content={
                "error": {"type": "invalid_subscription_ref", "message": "订阅引用无效。"}
            },
        )
    control = _get_control_adapter(request)
    subscriptions = await control.list_subscriptions()
    subscription = next(
        (sub for sub in subscriptions if sub.stream_id == stream_id), None
    )
    if subscription is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": {"type": "subscription_not_found", "message": "订阅不存在。"}
            },
        )
    await control.unsubscribe(stream_id)
    row = await _store(request).capture(
        feed_url=str(subscription.feed_url),
        stream_id=stream_id,
        title=getattr(subscription, "title", None),
        category_id=getattr(subscription, "category_id", None),
        category_label=getattr(subscription, "category_label", None),
        keep_days=payload.keepDays,
        unsubscribed_at=utc_now(),
    )
    return _view(row)


@router.get("/api/v1/new209/bin", response_model=BinList)
async def list_bin(
    request: Request, includeDiscarded: bool = False
) -> BinList:
    """回收箱列表（kept + restored；discard 行需显式 include）。"""
    rows = await _store(request).list_rows(include_discarded=includeDiscarded)
    return BinList(items=[_view(row) for row in rows], note=_BIN_NOTE)


@router.post("/api/v1/new209/bin/{row_id}/restore", status_code=200, response_model=BinRowView)
async def restore_bin_row(row_id: str, request: Request) -> Any:
    """按捕获的配置重新订阅（新代次），行转 restored。

    分类恢复策略：原 category_id 仍在 → 直接归位；分类已不存在 →
    按 category_label 重建（move_to_new_category）并如实标注。"""
    store = _store(request)
    row = await store.get(row_id)
    if row is None:
        return _not_found()
    if row["status"] != "kept":
        return _not_restorable()
    control = _get_control_adapter(request)
    created = await control.subscribe(
        row["feedUrl"],
        category_id=row["categoryId"],
        title=row["title"],
    )
    if row["categoryId"] is None and row["categoryLabel"]:
        # 原分类不存在（或退订前就是无 id 的标签）→ 按标签重建归位。
        await control.move_to_new_category(created.stream_id, row["categoryLabel"])
    updated = await store.mark_restored(row_id, str(created.stream_id))
    view = _view(updated)
    view.expired = False
    return view


@router.post("/api/v1/new209/bin/{row_id}/discard", status_code=200, response_model=BinRowView)
async def discard_bin_row(row_id: str, request: Request) -> Any:
    """显式放弃（kept → discarded；行保留作审计，不再可恢复）。"""
    try:
        row = await _store(request).mark_discarded(row_id)
    except BinRowNotFound:
        return _not_found()
    except BinRowNotRestorable:
        return _not_restorable()
    return _view(row)
