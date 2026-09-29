"""NEW-201 订阅接管向导路由（预演映射 → 确认应用 → 台账）。"""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.adapters.freshrss import AdapterError
from lumirss.deps import _get_control_adapter
from lumirss.new201_takeover import (
    TakeoverInvalid,
    TakeoverStore,
    build_plan,
    parse_opml_or_raise,
    validate_apply_items,
)
from lumirss.url_normalize import normalize_feed_url

router = APIRouter()


def _store(request: Request) -> TakeoverStore:
    return TakeoverStore(request.app.state.db)


def _invalid(error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=422, content={"error": {"type": error_type, "message": message}}
    )


class TakeoverPreviewRequest(BaseModel):
    """POST /api/v1/new201/takeover/preview body（OPML 原文；只读）。"""

    model_config = {"extra": "forbid"}

    opml: str = Field(min_length=1)


class TakeoverApplyItem(BaseModel):
    """单个确认动作：subscribe（新 feed）| move（已有 feed 继承目录）。"""

    model_config = {"extra": "forbid"}

    action: str
    feedUrl: str = Field(min_length=1)
    title: str | None = None
    categoryLabel: str | None = None


class TakeoverApplyRequest(BaseModel):
    """POST /api/v1/new201/takeover/apply body（逐项确认过的动作表）。"""

    model_config = {"extra": "forbid"}

    items: list[TakeoverApplyItem] = Field(min_length=1, max_length=200)
    label: str | None = Field(default=None, max_length=100)


@router.post("/api/v1/new201/takeover/preview")
async def takeover_preview(payload: TakeoverPreviewRequest, request: Request) -> Any:
    """把导出映射到现有订阅：新建/已订（绝不重复订阅）/无效三类。"""
    try:
        parsed = parse_opml_or_raise(payload.opml.encode("utf-8"))
    except TakeoverInvalid as exc:
        return _invalid("takeover_invalid_opml", str(exc))
    control = _get_control_adapter(request)
    try:
        subscriptions = await control.list_subscriptions()
    except AdapterError as exc:
        return JSONResponse(
            status_code=502,
            content={"error": {"type": "upstream_unavailable", "message": str(exc)}},
        )
    plan = build_plan(parsed, subscriptions)
    return {
        **plan,
        "note": (
            "已订来源绝不重复订阅；categoryDiffers=true 的可在应用时选择"
            "「继承目录」（move）。预演只读，确认后才执行。"
        ),
    }


class TakeoverBatchView(BaseModel):
    id: str
    label: str | None
    summary: dict[str, Any]
    createdAt: str


class TakeoverBatchList(BaseModel):
    items: list[TakeoverBatchView]


@router.get("/api/v1/new201/takeover/batches", response_model=TakeoverBatchList)
async def list_takeover_batches(request: Request) -> TakeoverBatchList:
    """接管台账（新→旧，≤50；含逐项结果摘要）。"""
    batches = await _store(request).list_batches()
    return TakeoverBatchList(items=[TakeoverBatchView(**b) for b in batches])


@router.post("/api/v1/new201/takeover/apply")
async def takeover_apply(payload: TakeoverApplyRequest, request: Request) -> Any:
    """执行确认过的动作：新建订阅（不重复）/ 已有订阅继承目录。

    逐项汇报：任何单项失败不阻断其他项（上游无事务，诚实逐项回报）；
    台账落一行（含逐项结果）。subscribe 带 categoryLabel 时按导出的
    分类标签建类归位（move_to_new_category = FreshRSS 唯一
    create-category 通道）。"""
    try:
        items = validate_apply_items([item.model_dump() for item in payload.items])
    except TakeoverInvalid as exc:
        return _invalid("takeover_invalid_apply", str(exc))
    control = _get_control_adapter(request)
    try:
        subscriptions = await control.list_subscriptions()
    except AdapterError as exc:
        return JSONResponse(
            status_code=502,
            content={"error": {"type": "upstream_unavailable", "message": str(exc)}},
        )
    current_by_key: dict[str, Any] = {}
    for sub in subscriptions:
        key = normalize_feed_url(str(sub.feed_url))
        if key is not None:
            current_by_key[key] = sub
    results: list[dict[str, Any]] = []
    created = skipped = moved = failed = 0
    for item in items:
        key = normalize_feed_url(item["feedUrl"])
        try:
            if item["action"] == "subscribe":
                existing = current_by_key.get(key) if key else None
                if existing is not None:
                    skipped += 1
                    results.append(
                        {
                            **item,
                            "outcome": "skipped_existing",
                            "subscriptionRef": getattr(
                                existing, "subscription_ref", None
                            ),
                        }
                    )
                    continue
                created_sub = await control.subscribe(
                    item["feedUrl"], category_id=None, title=item["title"]
                )
                if item["categoryLabel"]:
                    await control.move_to_new_category(
                        str(created_sub.stream_id), item["categoryLabel"]
                    )
                if key:
                    # 记入本批映射：同批重复 URL 不会再订阅（负向契约）。
                    current_by_key[key] = created_sub
                created += 1
                results.append({**item, "outcome": "created"})
            else:  # move：已有订阅继承导出分类
                existing = current_by_key.get(key) if key else None
                if existing is None or getattr(existing, "stream_id", None) is None:
                    failed += 1
                    results.append(
                        {**item, "outcome": "failed", "error": "subscription_not_found"}
                    )
                    continue
                await control.move_to_new_category(
                    str(existing.stream_id), item["categoryLabel"] or ""
                )
                moved += 1
                results.append({**item, "outcome": "moved"})
        except AdapterError as exc:
            failed += 1
            results.append({**item, "outcome": "failed", "error": str(exc)})
    summary = {
        "created": created,
        "skippedExisting": skipped,
        "moved": moved,
        "failed": failed,
        "results": results,
    }
    batch = await _store(request).record_batch(label=payload.label, summary=summary)
    return {"batch": batch, **summary}
