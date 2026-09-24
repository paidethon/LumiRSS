"""Source lifecycle tools router: N011 bundle / N016 staging / N017 cleanup.

One router for the three "own your source list" flows:

- N011 来源组合包：POST /api/v1/sources/bundle/export (credential-free
  JSON download) and POST /api/v1/sources/bundle/import (dry-run preview
  by default, ``?apply=true`` commits; credential-needing types import
  as DISABLED drafts, never with copied secrets; re-import is idempotent).
- N016 暂存待评估来源：POST /api/v1/sources/staging parks a URL with a
  bounded preview sample (NOT subscribed, never counted unread); the
  subscribe endpoint runs the normal subscribe path exactly once and
  removes the row; DELETE discards.
- N017 来源清理建议：GET /api/v1/sources/cleanup-suggestions lists
  long-unopened high-yield sources (advisory only); POST .../apply
  executes ONLY the explicitly selected feeds' actions (mute via the
  source-overrides hiddenUntil channel; demote via the existing
  move-to-category control path). No auto-unsubscribe, ever.
"""

import contextlib

import feedparser
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response

from lumirss.adapters.freshrss import AdapterError
from lumirss.adapters.freshrss_control import SubscriptionConflict
from lumirss.feed_preview import (
    FeedFetchError,
    FeedTooLarge,
    NotAFeedError,
    UnsafeFeedUrl,
    parse_feed_document,
    safe_fetch,
    validate_feed_url,
)
from lumirss.models import (
    BundleDocument,
    BundleExportRequest,
    BundleImportRequest,
    BundleImportResult,
    CleanupApplyRequest,
    CleanupApplyResult,
    CleanupSuggestionsResponse,
    StagedSourceCreateRequest,
    StagedSourceListResponse,
    StagedSourceSubscribeResult,
)
from lumirss.source_bundle import SourceBundleService
from lumirss.source_cleanup import (
    DEFAULT_MIN_WEEKLY_YIELD,
    DEFAULT_STALE_DAYS,
    build_suggestions,
)
from lumirss.staged_source_store import (
    StagedSourceConflict,
    StagedSourceInvalid,
    StagedSourceNotFound,
    StagedSourceStore,
)
from lumirss.util import utc_now

router = APIRouter()

_STAGING_SAMPLE_LIMIT = 10
_SUMMARY_EXCERPT = 280


def _staged_store(request: Request) -> StagedSourceStore:
    from lumirss.deps import _cached_on_app_state

    return _cached_on_app_state(
        request,
        "staged_source_store",
        lambda: StagedSourceStore(request.app.state.db),
    )


def _bundle_service(request: Request) -> SourceBundleService:
    from lumirss.deps import _cached_on_app_state, _get_control_adapter

    return _cached_on_app_state(
        request,
        "source_bundle_service",
        lambda: SourceBundleService(
            _get_control_adapter(request), request.app.state.db
        ),
    )


# -- N011 来源组合包 -----------------------------------------------------------


@router.post("/api/v1/sources/bundle/export", response_model=BundleDocument)
async def export_source_bundle(
    payload: BundleExportRequest, request: Request
) -> dict[str, object]:
    """Credential-free bundle of the requested subscriptions (download).

    Lumi-generated feeds (api/mail) are sanitized to stable URNs — the
    FreshRSS-side Atom URLs embed per-source secrets that must never
    leave the server. URLs matching no subscription are reported in
    ``missing`` (honest, no fabrication)."""
    if not payload.feedUrls:
        return BundleDocument(version=1, generatedAt=utc_now(), sources=[], missing=[])
    for url in payload.feedUrls:
        if not isinstance(url, str) or len(url) > 2048:
            from lumirss.source_bundle import BundleInvalid

            raise BundleInvalid("feedUrls 含无效条目。")
    return await _bundle_service(request).export_bundle(payload.feedUrls)


@router.post("/api/v1/sources/bundle/import", response_model=BundleImportResult)
async def import_source_bundle(
    payload: BundleImportRequest,
    request: Request,
    apply: bool = Query(default=False),
) -> dict[str, object]:
    """Import a bundle — dry-run preview BY DEFAULT.

    ``?apply=true`` commits: RSS rows subscribe once (merge-only, same
    channel as OPML import), types needing credentials land as disabled
    drafts in the staging pool. Existing rows report ``exists`` —
    re-importing the same bundle converges (idempotent). Secrets are
    never copied: a bundle cannot carry them, so nothing can leak."""
    service = _bundle_service(request)
    document = payload.model_dump()
    if apply:
        return await service.apply(document)
    return await service.preview(document)


# -- N016 暂存待评估来源 ---------------------------------------------------------


def _extract_sample_entries(body: bytes) -> tuple[list[dict[str, object]], str]:
    """Bounded preview snapshot (≤10 entries, metadata only) + feed title.

    Same safe-fetch family as feed preview; the parse is OFFLINE
    (feedparser never networks). Summaries are plain text excerpts —
    no full-content copy lands in the staging table."""
    title, _site_url, _description, _fmt = parse_feed_document(body)
    parsed = feedparser.parse(body)
    entries: list[dict[str, object]] = []
    for entry in (parsed.entries or [])[:_STAGING_SAMPLE_LIMIT]:
        link = entry.get("link")
        entries.append(
            {
                "title": (entry.get("title") or "").strip()[:300],
                "link": link if isinstance(link, str) and link.startswith(("http://", "https://")) else None,
                "published": entry.get("published") if isinstance(entry.get("published"), str) else None,
                "summary": " ".join(str(entry.get("summary") or "").split())[:_SUMMARY_EXCERPT],
            }
        )
    return entries, title


@router.post("/api/v1/sources/staging", status_code=201)
async def stage_source(
    payload: StagedSourceCreateRequest, request: Request
) -> dict[str, object]:
    """Park a URL for later evaluation: one bounded preview fetch, then a
    staging row. NOT subscribed, NOT counted in unread — nothing in the
    RSS domain changes at all."""
    url = payload.url.strip()
    validate_feed_url(url)
    store = _staged_store(request)
    if await store.find_by_url(url) is not None:
        raise StagedSourceConflict("该 URL 已在暂存列表中。")
    # already subscribed? Honest 409: staging a subscription is a no-op.
    control = None
    with contextlib.suppress(Exception):
        from lumirss.deps import _get_control_adapter

        control = _get_control_adapter(request)
    if control is not None:
        with contextlib.suppress(AdapterError):
            existing = await control.list_subscriptions()
            if any(subscription.feed_url == url for subscription in existing):
                return JSONResponse(
                    status_code=409,
                    content={
                        "error": {
                            "type": "already_subscribed",
                            "message": "该 URL 已是订阅来源，无需暂存评估。",
                        }
                    },
                )
    sample_entries: list[dict[str, object]] = []
    title = ""
    note = payload.note
    try:
        document = await safe_fetch(url)
        sample_entries, title = _extract_sample_entries(document.body)
    except NotAFeedError as exc:
        raise StagedSourceInvalid("该 URL 未返回 RSS/Atom feed，无法暂存评估。") from exc
    except UnsafeFeedUrl as exc:
        raise StagedSourceInvalid("该 URL 指向非公开地址，已拒绝。") from exc
    except FeedTooLarge as exc:
        raise StagedSourceInvalid("该来源文档超过 2MB 上限。") from exc
    except FeedFetchError as exc:
        # An unreachable URL can still be worth staging — keep it, note why
        # the sample is empty (honest), never fabricate entries.
        note = f"预览抓取失败：{exc}" if not note else f"{note}（预览抓取失败：{exc}）"
    stored = await store.add(url=url, title=title, note=note, sample_entries=sample_entries)
    stored["sample"] = sample_entries
    stored["subscribed"] = False  # 已订阅的 URL 在上面就被 409 挡下
    return stored


@router.get("/api/v1/sources/staging", response_model=StagedSourceListResponse)
async def list_staged_sources(request: Request) -> StagedSourceListResponse:
    """The staging pool (staging rows first-class; bundle drafts included
    and honestly flagged with origin/enabled)."""
    from lumirss.deps import _get_control_adapter

    store = _staged_store(request)
    rows = await store.list_all()
    subscribed: set[str] = set()
    with contextlib.suppress(Exception):
        control = _get_control_adapter(request)
        subscribed = {
            subscription.feed_url for subscription in await control.list_subscriptions()
        }
    for row in rows:
        row["subscribed"] = row["url"] in subscribed
    return StagedSourceListResponse(items=rows)


@router.post("/api/v1/sources/staging/{source_id}/subscribe", response_model=StagedSourceSubscribeResult)
async def subscribe_staged_source(
    source_id: str, request: Request
) -> dict[str, object]:
    """Promote a staged row through the NORMAL subscribe path — exactly
    once. An existing subscription converges to ``exists`` (idempotent
    retries); either way the staging row is removed after the outcome."""
    from lumirss.deps import _get_control_adapter

    store = _staged_store(request)
    row = await store.get(source_id)
    if row is None:
        raise StagedSourceNotFound(source_id)
    if row["origin"] != "staging":
        raise StagedSourceConflict(
            "组合包凭据草稿不能直接订阅：请先在 Lumi 中重建该来源。"
        )
    control = _get_control_adapter(request)
    status = "subscribed"
    try:
        await control.subscribe(
            row["url"], title=row["title"] or None
        )
    except SubscriptionConflict:
        status = "exists"
    await store.remove(source_id)
    return {"status": status, "feedUrl": row["url"]}


@router.delete("/api/v1/sources/staging/{source_id}", status_code=204)
async def discard_staged_source(source_id: str, request: Request) -> Response:
    deleted = await _staged_store(request).remove(source_id)
    if not deleted:
        raise StagedSourceNotFound(source_id)
    return Response(status_code=204)


# -- N017 来源清理建议 -----------------------------------------------------------


@router.get(
    "/api/v1/sources/cleanup-suggestions",
    response_model=CleanupSuggestionsResponse,
)
async def cleanup_suggestions(
    request: Request,
    minWeeklyYield: float = Query(default=DEFAULT_MIN_WEEKLY_YIELD, ge=0.1, le=1000),
    staleDays: int = Query(default=DEFAULT_STALE_DAYS, ge=7, le=365),
) -> dict[str, object]:
    """Advisory list: long-unopened sources that still deliver entries.

    Own-data stats only (read recency projection × projection yield);
    nothing here mutates anything. Unknown read history is reported as
    such — absence of a read timestamp is NOT claimed as "never read"."""
    from lumirss.deps import _get_control_adapter

    control = _get_control_adapter(request)
    subscriptions = await control.list_subscriptions()
    return await build_suggestions(
        request.app.state.db,
        subscriptions,
        min_weekly_yield=minWeeklyYield,
        stale_days=staleDays,
    )


@router.post(
    "/api/v1/sources/cleanup-suggestions/apply",
    response_model=CleanupApplyResult,
)
async def apply_cleanup_suggestions(
    payload: CleanupApplyRequest, request: Request
) -> dict[str, object]:
    """Apply ONLY the user-confirmed (feedUrl, action) pairs.

    mute → source_overrides hiddenUntil far future (the existing
    timeline-hide channel — reversible by clearing the override).
    demote_category → the existing move-to-category control path with a
    NEW named category (create-on-move, same as OPML import). Everything
    else is rejected; unknown feeds are reported per item. There is no
    auto-unsubscribe and no batch-everything mode."""
    if payload.action not in ("mute", "demote_category"):
        from lumirss.library import BookmarkInvalid

        raise BookmarkInvalid("action 必须是 mute 或 demote_category。")
    if payload.action == "demote_category" and not (
        payload.targetCategoryLabel or ""
    ).strip():
        from lumirss.library import BookmarkInvalid

        raise BookmarkInvalid("demote_category 需要 targetCategoryLabel。")
    if not payload.feedUrls:
        return {"items": [], "applied": 0}
    if len(payload.feedUrls) > 200:
        from lumirss.library import BookmarkInvalid

        raise BookmarkInvalid("单次最多应用 200 个来源。")
    from lumirss.deps import _get_control_adapter
    from lumirss.source_overrides import SourceOverrideStore

    control = _get_control_adapter(request)
    subscriptions = await control.list_subscriptions()
    by_url = {subscription.feed_url: subscription for subscription in subscriptions}
    override_store = SourceOverrideStore(request.app.state.db)
    items: list[dict[str, object]] = []
    applied = 0
    target_label = (payload.targetCategoryLabel or "").strip()
    for feed_url in dict.fromkeys(payload.feedUrls):
        subscription = by_url.get(feed_url)
        if subscription is None:
            items.append(
                {"feedUrl": feed_url, "ok": False, "error": "not_subscribed"}
            )
            continue
        try:
            if payload.action == "mute":
                await override_store.set_fields(
                    feed_url, hidden_until="9999-12-31T00:00:00Z"
                )
            else:
                await control.move_to_new_category(subscription.stream_id, target_label)
        except Exception as exc:  # noqa: BLE001 — per-item honest report
            items.append(
                {"feedUrl": feed_url, "ok": False, "error": str(exc)[:120]}
            )
            continue
        applied += 1
        items.append({"feedUrl": feed_url, "ok": True, "error": None})
    return {"items": items, "applied": applied}
