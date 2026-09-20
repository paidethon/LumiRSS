"""Entries routes (moved verbatim from main.py)."""


from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field, model_validator

from lumirss.cursor import InvalidCursor, decode_cursor, encode_cursor
from lumirss.deps import _get_adapter, _get_search_service
from lumirss.entryref import InvalidEntryReference, decode_entry_ref
from lumirss.models import (
    BacklogApplyRequest,
    BacklogApplyResponse,
    BacklogPreviewRequest,
    BacklogPreviewResponse,
    BacklogSampleItem,
    EntryDetail,
    EntryListResponse,
)
from lumirss.util import utc_now

router = APIRouter()

# F024：单批执行上限（超出部分需要再次预览+确认，避免不可控大批量）。
_BACKLOG_APPLY_CAP = 1000


class EntryStateUpdate(BaseModel):
    """PATCH body: set (never toggle) read/starred; one bool is required.

    Strict bools: Pydantic does not coerce 1/0/"true" into bool.
    """

    read: bool | None = Field(default=None, strict=True)
    starred: bool | None = Field(default=None, strict=True)

    @model_validator(mode="after")
    def at_least_one_bool(self) -> "EntryStateUpdate":
        if self.read is None and self.starred is None:
            raise ValueError("At least one of 'read' or 'starred' must be provided.")
        return self


@router.get(
    "/api/v1/entries",
    response_model=EntryListResponse,
    response_model_exclude_none=False,
)
async def entries(
    request: Request,
    view: Literal["all", "unread", "starred"] | None = None,
    feedUrl: str | None = None,
    sourceType: str | None = None,
    categoryId: str | None = None,
    cursor: str | None = None,
    includeHidden: bool = False,
) -> EntryListResponse:
    """One filtered page of entries — list fields only, never bodies.

    Filtering happens upstream (FreshRSS). Cursor rules: without a cursor,
    a missing view means "all"; with a cursor, a missing view/feedUrl/
    sourceType/categoryId adopts the cursor's scope, while an explicit
    view/feedUrl/sourceType/categoryId must match the cursor's scope
    exactly (else 400, before touching FreshRSS).

    0011 scope 扩展（§6/§13，全部服务端过滤，不用已加载页假筛选）：
    - sourceType：当前唯一合法值 "rss"（全部条目都是 RSS；契约上独立
      于“全部”，未来新增来源后有真实过滤行为）；
    - categoryId：FreshRSS 分类（greader label stream，适配器含默认
      分类本地化名 fallback）；
    - feedUrl 与 categoryId 互斥（两者同时出现 → 400）。
    """
    if sourceType is not None and sourceType != "rss":
        raise InvalidEntryReference("sourceType must be 'rss' (only source type today).")
    if feedUrl is not None and categoryId is not None:
        raise InvalidEntryReference("feedUrl and categoryId are mutually exclusive.")
    effective_view = view or "all"
    continuation: str | None = None
    if cursor is not None:
        scope = decode_cursor(cursor)  # raises InvalidCursor → 400
        if view is not None and scope.view != view:
            raise InvalidCursor("cursor scope does not match the requested view.")
        if feedUrl is not None and scope.feed_url != feedUrl:
            raise InvalidCursor("cursor scope does not match the requested feedUrl.")
        if sourceType is not None and scope.source_type != sourceType:
            raise InvalidCursor("cursor scope does not match the requested sourceType.")
        if categoryId is not None and scope.category_id != categoryId:
            raise InvalidCursor("cursor scope does not match the requested categoryId.")
        effective_view = scope.view
        feedUrl = scope.feed_url
        sourceType = scope.source_type
        categoryId = scope.category_id
        continuation = scope.continuation
    adapter = _get_adapter(request)
    page = await adapter.list_entries(
        view=effective_view,
        feed_url=feedUrl,
        category_id=categoryId,
        source_type=sourceType,
        continuation=continuation,
    )
    # F11/F13：来源级显示覆盖只作用于通用时间线（all/unread、无来源/
    # 分类 scope）——用户显式打开某来源或分类时按明确意图显示全部。
    items = page.items
    if feedUrl is None and categoryId is None and effective_view in ("all", "unread"):
        from lumirss.source_overrides import filter_timeline_items

        items = await filter_timeline_items(request.app.state.db, list(page.items))
    # F045：服务端屏蔽规则（per-feed）。默认把命中项从结果中剔除并在
    # filteredCount 如实计数；includeHidden=true 临时包含（附带
    # hiddenByRule 标记）。规则不触碰 FreshRSS 侧任何状态。
    from lumirss.feed_filter_store import FeedFilterRuleStore, first_matching_rule

    rules_by_feed: dict[str, list[dict[str, object]]] = {}
    store = FeedFilterRuleStore(request.app.state.db)
    for rule in await store.list_rules(None):
        if rule["enabled"]:
            rules_by_feed.setdefault(str(rule["feedUrl"]), []).append(rule)
    filtered_count = 0
    kept: list[object] = []
    for item in items:
        item_feed_url = getattr(item, "feedUrl", None)
        rules = rules_by_feed.get(str(item_feed_url)) if item_feed_url else None
        hit = (
            first_matching_rule(
                rules, title=getattr(item, "title", None), author=getattr(item, "author", None)
            )
            if rules
            else None
        )
        if hit is None:
            kept.append(item)
            continue
        reason = (
            f"{'标题' if hit['field'] == 'title' else '作者'}"
            f"{'包含' if hit['op'] == 'contains' else '等于'}「{hit['value']}」"
        )
        if includeHidden:
            item.hiddenByRule = {"ruleId": str(hit["id"]), "reason": reason}
            kept.append(item)
        else:
            filtered_count += 1
    items = kept  # type: ignore[assignment]
    next_cursor = (
        encode_cursor(
            page.upstreamContinuation,
            effective_view,
            feedUrl,
            source_type=sourceType,
            category_id=categoryId,
        )
        if page.upstreamContinuation is not None
        else None
    )
    return EntryListResponse(items=items, nextCursor=next_cursor, filteredCount=filtered_count)


@router.get(
    "/api/v1/entries/{entry_ref}",
    response_model=EntryDetail,
    response_model_exclude_none=False,
)
async def entry_detail(
    entry_ref: str, request: Request, extractOnce: bool = False
) -> Response:
    """One entry as plain text. Invalid refs are rejected before FreshRSS;
    reading a detail never marks anything as read (read-only milestone).

    F048：来源覆盖 extract_policy='web' 时，经安全有界抓取层抓原文正文
    （article_extract + SSRF 校验，≤2MB，不执行 JS），结果缓存于
    entry_extract_cache；失败回退 RSS 正文并置 extractionFailed=true。"""
    from fastapi.responses import JSONResponse


    item_id = decode_entry_ref(entry_ref)  # raises InvalidEntryReference → 400
    adapter = _get_adapter(request)
    detail = await adapter.get_entry(item_id)
    detail.extractPolicy = "rss"
    detail.extractionFailed = False
    feed_url = getattr(detail, "feedUrl", None)
    if not feed_url:
        return JSONResponse(detail.model_dump())
    from lumirss.source_overrides import SourceOverrideStore

    policy = await SourceOverrideStore(request.app.state.db).get_extract_policy(feed_url)
    if extractOnce:
        policy = "web"  # 单篇临时预览（不改变来源策略）
    detail.extractPolicy = policy
    if policy != "web" or not detail.url:
        return JSONResponse(detail.model_dump())
    # 缓存命中优先
    row = await request.app.state.db.fetch_one(
        "SELECT content_html, fetched_at FROM entry_extract_cache WHERE entry_ref = ?",
        (entry_ref,),
    )
    if row is not None:
        detail.contentHtml = row["content_html"]
        return JSONResponse(detail.model_dump())
    try:
        from lumirss.clip_fetch import fetch_extract_sanitize

        page = await fetch_extract_sanitize(detail.url)
    except Exception:  # noqa: BLE001 — 提取失败诚实回退 RSS 正文
        detail.extractionFailed = True
        return JSONResponse(detail.model_dump())
    detail.contentHtml = page.content_html
    await request.app.state.db.execute(
        "INSERT INTO entry_extract_cache (entry_ref, content_html, fetched_at) VALUES (?, ?, ?) ON CONFLICT(entry_ref) DO UPDATE SET content_html = excluded.content_html, fetched_at = excluded.fetched_at",
        (entry_ref, page.content_html, utc_now()),
    )
    return JSONResponse(detail.model_dump())


@router.patch("/api/v1/entries/{entry_ref}/state", status_code=204)
async def entry_state(entry_ref: str, update: EntryStateUpdate, request: Request) -> Response:
    """Set the read/starred state of one entry (set semantics, not toggle).

    204 means FreshRSS accepted the write; it does not re-confirm that the
    entry exists. Invalid refs and invalid bodies are rejected before any
    FreshRSS call. The accepted state is mirrored into the derived search
    projection so its unread/starred filters stay fresh between syncs.
    """
    item_id = decode_entry_ref(entry_ref)  # raises InvalidEntryReference → 400
    adapter = _get_adapter(request)
    await adapter.set_entry_state(
        item_id, read=update.read, starred=update.starred
    )
    search = _get_search_service(request)
    if update.read is not None:
        await search.set_entry_read(entry_ref, update.read)
    if update.starred is not None:
        await search.set_entry_starred(entry_ref, update.starred)
    return Response(status_code=204)




# -- F024 积压整理助手 --------------------------------------------------------


def _backlog_condition(payload) -> dict:
    from lumirss.backlog import _condition_dict

    return _condition_dict(
        older_than_days=payload.olderThanDays,
        feed_url=payload.feedUrl,
        category_id=payload.categoryId,
    )


def _effective_exclusions(payload) -> list[str]:
    from lumirss.backlog import _EFFECTIVE_EXCLUSIONS

    # 服务端强制排除：即使传 false 也保护 starred / read-later。
    return list(_EFFECTIVE_EXCLUSIONS)


def _sample_model(row) -> "BacklogSampleItem":
    return BacklogSampleItem(
        ref=f"rss:{row['entry_ref']}",
        title=str(row["title"]),
        publishedAt=str(row["published_at"]),
    )


@router.post(
    "/api/v1/entries/backlog-preview",
    response_model=BacklogPreviewResponse,
)
async def backlog_preview(payload: BacklogPreviewRequest, request: Request) -> dict:
    """真实计数 + 前 20 条样本 + 一次性 token（30s）。零写入。"""
    from lumirss.backlog import backlog_rows, issue_preview_token

    condition = _backlog_condition(payload)
    rows = await backlog_rows(
        request.app.state.db,
        older_than_days=payload.olderThanDays,
        feed_url=payload.feedUrl,
        category_id=payload.categoryId,
        limit=None,
    )
    token = issue_preview_token(condition)
    return {
        "count": len(rows),
        "sample": [_sample_model(row) for row in rows[:20]],
        "effectiveExclusions": _effective_exclusions(payload),
        "confirmPreviewToken": token,
    }


@router.post(
    "/api/v1/entries/backlog-apply",
    response_model=BacklogApplyResponse,
)
async def backlog_apply(payload: BacklogApplyRequest, request: Request) -> dict:
    """确认执行：逐条走既有 set-read 管线（set 语义）；单条失败进
    failed[]；token 校验失败（过期/条件漂移）→ 409。"""
    import asyncio as _asyncio

    from lumirss.backlog import (
        backlog_rows,
        validate_apply_token,
    )

    condition = _backlog_condition(payload)
    validate_apply_token(payload.confirmPreviewToken, condition)  # 409 on drift/expiry
    rows = await backlog_rows(
        request.app.state.db,
        older_than_days=payload.olderThanDays,
        feed_url=payload.feedUrl,
        category_id=payload.categoryId,
        limit=_BACKLOG_APPLY_CAP,
    )
    adapter = _get_adapter(request)
    search = _get_search_service(request)
    applied = 0
    failed: list[BacklogSampleItem] = []

    async def _mark(row) -> bool:
        from lumirss.entryref import decode_entry_ref

        try:
            item_id = decode_entry_ref(row["entry_ref"])
            await adapter.set_entry_state(item_id, read=True, starred=None)
            await search.set_entry_read(row["entry_ref"], True)
            return True
        except Exception:  # noqa: BLE001 — 单条失败不中断整批
            return False

    results = await _asyncio.gather(*(_mark(row) for row in rows))
    for row, ok in zip(rows, results, strict=True):
        if ok:
            applied += 1
        else:
            failed.append(_sample_model(row))
    return {
        "applied": applied,
        "failed": failed,
        "effectiveExclusions": _effective_exclusions(payload),
    }


_ = (_BACKLOG_APPLY_CAP,)  # cap referenced above; BacklogConflict mapped via BacklogConflict import in apply
