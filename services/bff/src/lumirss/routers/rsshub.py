"""Rsshub routes (moved verbatim from main.py)."""


import asyncio
import logging
import time
import urllib.parse
from datetime import UTC, datetime
from typing import Literal

import httpx
from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.config import LumiSettings, _validate_service_base_url
from lumirss.deps import (
    _get_control_adapter,
    _get_rsshub_control_store,
    _get_rsshub_credentials_store,
    _get_rsshub_preview_cache,
    _get_rsshub_service,
    _preview_json,
)
from lumirss.feed_preview import FeedTooLarge, NotAFeedError
from lumirss.models import (
    RssHubCatalog,
    RssHubConfigView,
    RssHubFavoriteItem,
    RssHubParamPresetApply,
    RssHubParamPresetItem,
    RssHubParamsDiffRequest,
    RssHubParamsDiffResult,
    RssHubParamsDiffSide,
    RssHubPreviewResult,
    RssHubRecentItem,
    RssHubRefreshResult,
    RssHubRouteMySources,
    RssHubRouteRuns,
    RssHubRouteSourceEntry,
    RssHubRouteUsage,
    RssHubUpgradeCheckReport,
    RssHubUpgradeChecks,
)
from lumirss.routers.ai_settings import SecretValuePut
from lumirss.rsshub import (
    FAILURE_BAD_CONTENT,
    FAILURE_NO_NEW_CONTENT,
    NO_NEW_CONTENT_WINDOW,
    ZERO_ENTRY_HINT,
    RssHubFetchError,
    RssHubInvalidParameters,
    RssHubNotConfigured,
    RssHubRefreshRateLimited,
    RssHubRouteNotFound,
    build_path,
    count_feed_entries,
    diff_title_sets,
    extract_entry_titles,
    requires_json,
    safe_rsshub_path,
)
from lumirss.rsshub_control import (
    RssHubInvalidValue,
    config_view,
)
from lumirss.rsshub_param_presets import (
    RssHubParamPresetStore,
    RssHubPresetNotFound,
    _validate_preset_params,
)
from lumirss.rsshub_route_store import (
    RssHubRouteStore,
    compute_route_key,
    mask_params,
    parse_route_key,
)
from lumirss.user_scope import require_user_id, user_context
from lumirss.util import utc_now

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_route_store(request: Request) -> RssHubRouteStore:
    """N021/N025 store over the routing database (per-user by context)."""
    return RssHubRouteStore(request.app.state.db)


def _catalog_route(route_id: str):
    from lumirss.rsshub import _CATALOG_BY_ID

    route = _CATALOG_BY_ID.get(route_id)
    if route is None:
        raise RssHubRouteNotFound(f"Unknown RSSHub route '{route_id}'.")
    return route


class RssHubPreviewRequest(BaseModel):
    """POST /api/v1/rsshub/preview body (0014): route + parameter values.

    ``baseUrl`` is an E2E-ONLY fetch-base override — see
    ``_e2e_base_override`` for the gate contract. The Web client never
    sends it.
    """

    routeId: str = Field(min_length=1)
    params: dict[str, str] = Field(default_factory=dict)
    baseUrl: str | None = Field(default=None, min_length=1, max_length=2000)


@router.get("/api/v1/rsshub/routes", response_model=RssHubCatalog)
async def rsshub_routes(request: Request) -> dict[str, object]:
    """Lumi-owned RSSHub route catalog (static, always available).

    ``configured`` reports whether the server has an RSSHUB_BASE_URL —
    the catalog itself is independent of the instance. Route descriptors
    carry enough metadata for the Web to render parameter forms; path
    construction happens server-side on preview.
    """
    service = _get_rsshub_service(request)
    try:
        service.load_settings()
        configured = True
    except RssHubNotConfigured:
        configured = False
    return {
        "configured": configured,
        "routes": [
            {
                "id": route.id,
                "title": route.title,
                "description": route.description,
                "pathTemplate": route.path_template,
                "parameters": [
                    {
                        "key": parameter.key,
                        "label": parameter.label,
                        "required": parameter.required,
                        "pattern": parameter.pattern,
                        "example": parameter.example,
                        "help": parameter.help,
                    }
                    for parameter in route.parameters
                ],
                # N023：依赖元数据（未标注 → null，UI 显示「未知」chips）。
                "requires": requires_json(route),
            }
            for route in service.list_routes()
        ],
    }


def _e2e_base_override(base_url: str | None) -> str | None:
    """Validate the E2E-only preview fetch-base override (or pass None).

    The cross-service smoke (e2e/stack/run-smoke.sh) pins a dead endpoint
    via ``baseUrl`` to assert the stable 502 ``rsshub_fetch_error`` class.
    The override exists ONLY for that stack: it is honored exclusively
    when the BFF itself runs with ``LUMIRSS_E2E=1`` (set only in the e2e
    compose); every other deployment raises 400 before any dial. The URL
    must pass the same structural rules as the configured base, and it
    never leaks into the returned subscription feedUrl.
    """
    if base_url is None:
        return None
    import os

    if os.environ.get("LUMIRSS_E2E") != "1":
        raise RssHubInvalidParameters(
            "baseUrl override is only honored in the E2E stack "
            "(LUMIRSS_E2E=1)."
        )
    try:
        _validate_service_base_url(base_url, "baseUrl override")
    except ValueError as exc:
        raise RssHubInvalidParameters(str(exc)) from exc
    return base_url


@router.post(
    "/api/v1/rsshub/preview",
    response_model=RssHubPreviewResult,
    response_model_exclude_none=False,
)
async def rsshub_preview(
    body: RssHubPreviewRequest, request: Request
) -> dict[str, object]:
    """Preview one configured RSSHub route — NON-MUTATING.

    Constructs the path server-side (validated + encoded parameters),
    fetches the generated feed from the server-configured RSSHub
    instance, parses offline and reads the subscription list for
    alreadySubscribed. The returned feedUrl is the FreshRSS-facing
    subscription URL; subscribing is POST /api/v1/subscriptions (0013).

    N021: a SUCCESSFUL preview upserts the route into the per-user
    最近使用 list. N025: every attempt that reaches the fetch stage is
    written to the route health timeline (last 20 kept per route).
    Sensitive parameter values are masked to '***' before anything is
    stored. Failed previews never record a 最近使用 entry.

    N027: successful previews are cached per (user, route_key) with a
    short TTL; a cache hit reports ``cache: {ageS > 0, fresh: false}``
    and does NOT re-fetch, re-record a timeline row, or touch 最近使用 —
    it was not an upstream attempt. The E2E base override always
    bypasses the cache.
    """
    override = _e2e_base_override(body.baseUrl)
    route_key = compute_route_key(body.routeId, body.params)
    user_id = require_user_id()
    cache = _get_rsshub_preview_cache(request)
    # N023：依赖元数据来自静态 catalog（未知路由 → None，诚实呈现）。
    from lumirss.rsshub import _CATALOG_BY_ID

    catalog_route = _CATALOG_BY_ID.get(body.routeId)
    route_requires = requires_json(catalog_route) if catalog_route else None
    if override is None:
        hit = cache.get(user_id, route_key)
        if hit is not None:
            cached_preview, age_s = hit
            data = _preview_json(cached_preview)
            data["routeKey"] = route_key
            data["cache"] = {"ageS": age_s, "fresh": False}
            data["requires"] = route_requires
            data["zeroEntryHint"] = (
                ZERO_ENTRY_HINT if cached_preview.entry_count == 0 else None
            )
            return data
    started = time.monotonic()
    try:
        preview = await _do_preview(
            request, body.routeId, body.params, base_override=override
        )
    except (RssHubFetchError, NotAFeedError, FeedTooLarge) as exc:
        # Fetch-stage failure → timeline row (N025) with the N026 stable
        # failure class. Request/validation errors (unknown route, bad
        # params, not configured) never reached the wire and are NOT
        # route health events.
        failure_class = getattr(exc, "failure_class", None)
        if failure_class is None and isinstance(exc, (NotAFeedError, FeedTooLarge)):
            # Fetched content was unusable — F050 vocabulary for that.
            failure_class = FAILURE_BAD_CONTENT
        await _record_run(
            request,
            route_key,
            status="failed",
            duration_ms=_elapsed_ms(started),
            entry_count=None,
            failure_class=failure_class,
        )
        raise
    failure_class = await _no_new_content_class(
        request, route_key, preview.entry_count
    )
    await _record_run(
        request,
        route_key,
        status="ok",
        duration_ms=_elapsed_ms(started),
        entry_count=preview.entry_count,
        failure_class=failure_class,
    )
    await _record_recent(request, body.routeId, body.params)
    if override is None:
        cache.put(user_id, route_key, preview)
    data = _preview_json(preview)
    data["routeKey"] = route_key
    data["cache"] = {"ageS": 0.0, "fresh": True}
    # N023：依赖 chips + 0 条目诚实提示（依赖可能未满足，非健康状态）。
    data["requires"] = route_requires
    data["zeroEntryHint"] = ZERO_ENTRY_HINT if preview.entry_count == 0 else None
    return data


async def _do_preview(
    request: Request,
    route_id: str,
    params: dict[str, str],
    *,
    base_override: str | None,
):
    """One preview attempt — real service, or the injected probe.

    ``app.state.rsshub_route_probe`` (N026 fault injection, F050
    health_probe pattern): an async callable(route_id, params,
    base_override) returning a FeedPreview or raising a classified
    RssHubFetchError, so tests can drive the full route path (error
    surface + timeline classification) without touching the network.
    The real service (and its control adapter) is only built when no
    probe is installed.
    """
    probe = getattr(request.app.state, "rsshub_route_probe", None)
    if probe is not None:
        return await probe(route_id, params, base_override=base_override)
    return await _get_rsshub_service(request).preview(
        route_id, params, base_override=base_override
    )


async def _no_new_content_class(
    request: Request, route_key: str, entry_count: int | None
) -> str | None:
    """N026: feed ok but 0 entries on a route that HAD entries inside the
    window → no_new_content. A new route's first 0-entry fetch is normal
    (status ok, no failure class)."""
    if entry_count != 0:
        return None
    since = (datetime.now(UTC) - NO_NEW_CONTENT_WINDOW).isoformat()
    had_entries = await _get_route_store(request).last_success_with_entries(
        route_key, since_iso=since
    )
    return FAILURE_NO_NEW_CONTENT if had_entries else None


def _elapsed_ms(started: float) -> int:
    return max(0, int((time.monotonic() - started) * 1000))


async def _record_run(
    request: Request,
    route_key: str,
    *,
    status: str,
    duration_ms: int,
    entry_count: int | None,
    failure_class: str | None,
) -> None:
    """N025: best-effort timeline write — a metadata failure must never
    turn an already-completed route use into an error response."""
    try:
        await _get_route_store(request).record_run(
            route_key=route_key,
            status=status,
            duration_ms=duration_ms,
            entry_count=entry_count,
            failure_class=failure_class,
        )
    except Exception:  # noqa: BLE001 — metadata only, never fail the use
        logger.exception("rsshub route run-recording failed for %s", route_key)


async def _record_recent(
    request: Request, route_id: str, params: dict[str, str]
) -> None:
    """N021: best-effort 最近使用 upsert after a successful route use.

    The route use itself already succeeded — a metadata write failure
    must not turn it into an error response; it is logged instead.
    Storage is masked upstream (``mask_params``), so no sensitive value
    can reach this call site's arguments anyway.
    """
    try:
        await _get_route_store(request).record_recent(
            template_id=route_id, params=params, success=True
        )
    except Exception:  # noqa: BLE001 — metadata only, never fail the use
        logger.exception("rsshub route recent-recording failed for %s", route_id)


# ---- N021: route favorites & 最近使用 ---------------------------------------


class RssHubFavoritePut(BaseModel):
    """PUT /api/v1/rsshub/routes/favorites body (route id + params + label)."""

    routeId: str = Field(min_length=1)
    params: dict[str, str] = Field(default_factory=dict)
    label: str = Field(default="", max_length=120)


@router.get(
    "/api/v1/rsshub/routes/favorites",
    response_model=list[RssHubFavoriteItem],
    response_model_exclude_none=False,
)
async def list_rsshub_favorites(request: Request) -> list[dict[str, object]]:
    """N021 favorites (per-user, cross-device). Sensitive parameter
    values are stored as '***' sentinels and are the only thing that can
    come back here."""
    return await _get_route_store(request).list_favorites()


@router.put(
    "/api/v1/rsshub/routes/favorites",
    response_model=RssHubFavoriteItem,
    response_model_exclude_none=False,
)
async def put_rsshub_favorite(
    body: RssHubFavoritePut, request: Request
) -> dict[str, object]:
    """Star (or re-label) one route — upsert on route_key.

    routeId must exist in the Lumi catalog; params are stored MASKED
    (F047 敏感键 → '***'), so a favorite never carries a secret."""
    _catalog_route(body.routeId)
    return await _get_route_store(request).put_favorite(
        template_id=body.routeId, params=body.params, label=body.label
    )


@router.delete("/api/v1/rsshub/routes/favorites/{route_key}", status_code=204)
async def delete_rsshub_favorite(
    route_key: str, request: Request
) -> Response:
    """Unstar one favorite; 404 when the user has no such favorite."""
    deleted = await _get_route_store(request).delete_favorite(route_key)
    if not deleted:
        from lumirss.rsshub import RssHubFavoriteNotFound

        raise RssHubFavoriteNotFound("Route favorite not found.")
    return Response(status_code=204)


@router.get(
    "/api/v1/rsshub/routes/recent",
    response_model=list[RssHubRecentItem],
    response_model_exclude_none=False,
)
async def list_rsshub_recent(request: Request) -> list[dict[str, object]]:
    """N021 最近使用 — rows appear here only after a SUCCESSFUL preview
    or subscribe (failed attempts never record)."""
    return await _get_route_store(request).list_recent()


@router.get(
    "/api/v1/rsshub/routes/history",
    response_model=RssHubRouteRuns,
    response_model_exclude_none=False,
)
async def rsshub_route_history(
    request: Request,
    routeKey: str = Query(min_length=1, max_length=500),
    limit: int = Query(default=20, ge=1, le=20),
) -> dict[str, object]:
    """N025 最近运行 — bounded health timeline for ONE route key
    (newest first; the table itself prunes to the last 20 per route)."""
    return {"items": await _get_route_store(request).list_runs(routeKey, limit=limit)}


# ---- N027: 预览缓存控制（强制刷新 + 每用户限速） -----------------------------

_REFRESH_RATE_LIMIT = 6
_REFRESH_RATE_WINDOW_S = 60.0
# 每用户令牌桶：uid -> (tokens, last_refill_monotonic)。进程内状态——
# 重启即重置，与预览缓存同一生命周期。
_refresh_buckets: dict[str, tuple[float, float]] = {}


class RssHubRefreshRequest(BaseModel):
    """POST /api/v1/rsshub/refresh body (server-derived route key)."""

    routeKey: str = Field(min_length=1, max_length=500)


def _refresh_retry_after(request: Request, user_id: str) -> int:
    """Per-user token bucket. 0 = allowed (consumes one token), else the
    number of seconds until the next token. Tests override the rate via
    ``app.state.rsshub_refresh_rate = (limit, window_s)``."""
    limit, window_s = getattr(
        request.app.state,
        "rsshub_refresh_rate",
        None,
    ) or (_REFRESH_RATE_LIMIT, _REFRESH_RATE_WINDOW_S)
    refill_per_s = limit / window_s
    now = time.monotonic()
    tokens, last = _refresh_buckets.get(user_id, (float(limit), now))
    tokens = min(float(limit), tokens + (now - last) * refill_per_s)
    if tokens < 1.0:
        _refresh_buckets[user_id] = (tokens, now)
        import math

        return max(1, math.ceil((1.0 - tokens) / refill_per_s))
    tokens -= 1.0
    _refresh_buckets[user_id] = (tokens, now)
    return 0


@router.post(
    "/api/v1/rsshub/refresh",
    response_model=RssHubRefreshResult,
    response_model_exclude_none=False,
)
async def rsshub_refresh(
    body: RssHubRefreshRequest, request: Request
) -> dict[str, object]:
    """N027: force a re-fetch of exactly ONE route (per-user rate limited).

    The route key is parsed server-side back into template id + params.
    Sensitive parameter values were never stored ('***' sentinel only),
    so refreshing such a route is refused — the user re-enters them in a
    normal preview. Rate limit: 6 refreshes/minute/user, then a stable
    429 with Retry-After. Only THIS route's cache entry is dropped;
    other routes and any global caches are untouched.
    """
    parsed = parse_route_key(body.routeKey)
    if parsed is None:
        raise RssHubInvalidParameters("Malformed RSSHub route key.")
    template_id, params = parsed
    _catalog_route(template_id)
    if any(value == "***" for value in params.values()):
        raise RssHubInvalidParameters(
            "This route has sensitive parameter values that are never "
            "stored; run a new preview with the values instead."
        )
    retry_after = _refresh_retry_after(request, require_user_id())
    if retry_after > 0:
        raise RssHubRefreshRateLimited(retry_after)
    user_id = require_user_id()
    _get_rsshub_preview_cache(request).invalidate(user_id, body.routeKey)
    started = time.monotonic()
    try:
        preview = await _do_preview(
            request, template_id, params, base_override=None
        )
    except (RssHubFetchError, NotAFeedError, FeedTooLarge) as exc:
        failure_class = getattr(exc, "failure_class", None)
        if failure_class is None and isinstance(exc, (NotAFeedError, FeedTooLarge)):
            failure_class = FAILURE_BAD_CONTENT
        await _record_run(
            request,
            body.routeKey,
            status="failed",
            duration_ms=_elapsed_ms(started),
            entry_count=None,
            failure_class=failure_class,
        )
        raise
    failure_class = await _no_new_content_class(
        request, body.routeKey, preview.entry_count
    )
    await _record_run(
        request,
        body.routeKey,
        status="ok",
        duration_ms=_elapsed_ms(started),
        entry_count=preview.entry_count,
        failure_class=failure_class,
    )
    await _record_recent(request, template_id, params)
    _get_rsshub_preview_cache(request).put(user_id, body.routeKey, preview)
    return {
        "routeKey": body.routeKey,
        "title": preview.title,
        "entryCount": preview.entry_count,
        "ranAt": utc_now(),
        "durationMs": _elapsed_ms(started),
        "cache": {"ageS": 0.0, "fresh": True},
    }


# ---- N024：路由变更差异预览（旧/新参数两侧有界抓取，严格只读） --------------


@router.post(
    "/api/v1/rsshub/params-diff",
    response_model=RssHubParamsDiffResult,
    response_model_exclude_none=False,
)
async def rsshub_params_diff(
    body: RssHubParamsDiffRequest, request: Request
) -> dict[str, object]:
    """N024：编辑既有 RSSHub 来源参数前的差异对照（零写入）。

    同一次请求内有界抓取旧参数 feed 与新参数 feed（都走实例配置 origin
    的 origin-locked 路径），离线解析标题并做集合 diff：
    - added = 仅新 feed 有的标题；removed = 仅旧 feed 有的标题；
      duplicates = 两侧都有（标题为对照键——entry id 不跨参数稳定）；
    - 一侧抓取/解析失败 → 该侧 error 如实说明，titles=null，diff 基于
      可用一侧诚实计算（绝不臆造空 = 全量增删的假差异）；
    - newUrl 是 FreshRSS 面向的订阅地址（与 preview 同一构造）；
    - 应用语义与 F047 相同：确认走迁移端点（新建订阅 + 旧源保留），
      本端点本身绝不改任何状态（取消 = 什么都没发生）。"""
    import urllib.parse

    route = _catalog_route(body.routeId)  # 未知路由 → 404 类稳定错误
    new_path = build_path(route, body.newParams)  # 非法参数 → 稳定错误
    service = _get_rsshub_service(request)
    settings = service.load_settings()

    parts = urllib.parse.urlsplit(body.oldFeedUrl)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise RssHubInvalidParameters("oldFeedUrl must be an absolute http(s) URL.")
    if not safe_rsshub_path(parts.path):
        raise RssHubInvalidParameters("oldFeedUrl path is not a usable RSSHub path.")
    old_path = parts.path + (f"?{parts.query}" if parts.query else "")

    async def _side(path: str) -> RssHubParamsDiffSide:
        try:
            document = await service.fetch_document(path)
        except RssHubFetchError as exc:
            return RssHubParamsDiffSide(url=path, titles=None, error=str(exc))
        return RssHubParamsDiffSide(
            url=path,
            entryCount=count_feed_entries(document),
            titles=extract_entry_titles(document),
        )

    old_side = await _side(old_path)
    new_side = await _side(new_path)
    diff = diff_title_sets(old_side.titles or [], new_side.titles or [])
    return {
        "old": old_side,
        "new": new_side,
        **diff,
        "newUrl": f"{settings.freshrss_base_url}{new_path}",
        "note": (
            "对照为只读预览；取消不产生任何变更。确认应用后新建订阅并保留旧订阅"
            "（可自行退订）。"
        ),
    }


async def _probe_rsshub(client: httpx.AsyncClient, url: str, source: str) -> dict[str, object]:
    """One bounded /healthz probe (2s timeout, honest latency or failure)."""
    import time as _time

    started = _time.monotonic()
    try:
        response = await client.get(f"{url}/healthz", timeout=2.0)
        reachable = response.status_code == 200
    except Exception:
        reachable = False
    latency = int((_time.monotonic() - started) * 1000)
    return {
        "url": url,
        "source": source,
        "reachable": reachable,
        "latencyMs": latency if reachable else None,
    }


def _rsshub_runtime_configured() -> bool:
    from pydantic import ValidationError as _ValidationError

    from lumirss.config import RssHubSettings

    try:
        return bool(RssHubSettings().RSSHUB_BASE_URL)
    except _ValidationError:
        return False


class RssHubConfigPatch(BaseModel):
    """PATCH /api/v1/rsshub/config body: allow-listed non-secret values."""

    values: dict[str, object] = Field(default_factory=dict)


async def _rsshub_config_view_async(request: Request) -> dict[str, object]:
    store = _get_rsshub_control_store(request)
    desired = await store.desired()
    flags = await store.restart_required_flags()
    return {
        "schemaVersion": 1,
        "configured": _rsshub_runtime_configured(),
        "pendingCount": flags["count"],
        "pendingSecrets": flags["pendingSecrets"],
        "groups": config_view(store, desired, flags),
    }


@router.get(
    "/api/v1/rsshub/config",
    response_model=RssHubConfigView,
    # Historical wire format: secret items carry "configured" (no "value"),
    # non-secret items carry "value" (no "configured"), "options" is always
    # present (null for non-enum items) — exclude_unset reproduces exactly that.
    response_model_exclude_none=False,
    response_model_exclude_unset=True,
)
async def get_rsshub_config(request: Request) -> dict[str, object]:
    return await _rsshub_config_view_async(request)


@router.patch(
    "/api/v1/rsshub/config",
    response_model=RssHubConfigView,
    response_model_exclude_none=False,
    response_model_exclude_unset=True,
)
async def patch_rsshub_config(
    body: RssHubConfigPatch, request: Request
) -> dict[str, object]:
    """Update allow-listed non-secret desired values (validated + typed).

    Secrets are never accepted here — use the secret endpoints. Saving only
    updates the DESIRED config; the UI reports restartRequired honestly.
    """
    store = _get_rsshub_control_store(request)
    await store.patch_desired({k: v for k, v in body.values.items()})
    return await _rsshub_config_view_async(request)


@router.get("/api/v1/rsshub/config/export")
async def export_rsshub_config(request: Request) -> Response:
    """Render the desired config as an env fragment (secrets never echoed)."""
    from lumirss.rsshub_control import export_env

    store = _get_rsshub_control_store(request)
    desired = await store.desired()
    return Response(
        content=export_env(store, desired),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="rsshub.env"'},
    )


# ---- Gate: auto-detect, custom credentials, server-side env file ----


class RssHubDetectCandidate(BaseModel):
    url: str
    source: str
    reachable: bool
    latencyMs: int | None = None


class RssHubDetectResult(BaseModel):
    """GET /api/v1/rsshub/detect — bounded candidate probing."""

    configured: bool
    candidates: list[RssHubDetectCandidate] = []


@router.get("/api/v1/rsshub/detect", response_model=RssHubDetectResult)
async def detect_rsshub(request: Request) -> dict[str, object]:
    """Auto-identify the RSSHub instance within BOUNDED candidates only:
    the configured URL, this project's compose DNS name, and the host
    loopback. Never a LAN scan; never any authenticated read-back."""
    from lumirss.config import RssHubSettings

    configured = RssHubSettings().RSSHUB_BASE_URL
    candidates: list[dict[str, object]] = []
    probes: list[tuple[str, str]] = []
    if configured:
        probes.append((configured, "configured"))
    probes.append(("http://rsshub:1200", "compose-dns"))
    probes.append(("http://127.0.0.1:1200", "host-loopback"))
    client = request.app.state.http_client
    results = await asyncio.gather(
        *(_probe_rsshub(client, url, source) for url, source in probes),
        return_exceptions=True,
    )
    for item in results:
        if isinstance(item, BaseException):
            continue
        candidates.append(item)  # type: ignore[arg-type]
    return {"configured": bool(configured), "candidates": candidates}


class RssHubCredentialCreate(BaseModel):
    """POST /api/v1/rsshub/credentials body (value is write-only)."""

    name: str = Field(min_length=1, max_length=80)
    domain: str = Field(min_length=1, max_length=253)
    envKey: str = Field(min_length=1, max_length=64)
    kind: Literal["cookie", "token", "api_key", "bearer", "other"]
    value: str = Field(min_length=1, max_length=10000)
    route: str = Field(default="", max_length=200)


class RssHubCredentialValuePut(BaseModel):
    """PUT /api/v1/rsshub/credentials/{id}/value body."""

    value: str = Field(min_length=1, max_length=10000)


@router.get("/api/v1/rsshub/credentials", response_model=list[dict[str, object]])
async def list_rsshub_credentials(request: Request) -> list[dict[str, object]]:
    """Custom site/route credentials (values are write-only; configured
    flags only). Adding one NEVER fabricates an RSSHub route."""
    return await _get_rsshub_credentials_store(request).list_entries()


@router.post("/api/v1/rsshub/credentials", response_model=dict[str, object], status_code=201)
async def create_rsshub_credential(
    body: RssHubCredentialCreate, request: Request
) -> dict[str, object]:
    return await _get_rsshub_credentials_store(request).create(
        name=body.name,
        domain=body.domain,
        env_key=body.envKey,
        kind=body.kind,
        value=body.value,
        route=body.route,
    )


class RssHubCredentialMetadataPatch(BaseModel):
    """PATCH /api/v1/rsshub/credentials/{id} body (metadata only)."""

    name: str | None = None
    route: str | None = None


@router.patch("/api/v1/rsshub/credentials/{credential_id}", response_model=dict[str, object])
async def patch_rsshub_credential(
    credential_id: str, body: RssHubCredentialMetadataPatch, request: Request
) -> dict[str, object]:
    return await _get_rsshub_credentials_store(request).update_metadata(
        credential_id,
        name=body.name,
        route=body.route,
    )


@router.put("/api/v1/rsshub/credentials/{credential_id}/value", status_code=204)
async def put_rsshub_credential_value(
    credential_id: str, body: RssHubCredentialValuePut, request: Request
) -> Response:
    if not body.value.strip():
        raise RssHubInvalidValue("value must not be blank.")
    await _get_rsshub_credentials_store(request).set_value(credential_id, body.value)
    return Response(status_code=204)


@router.delete("/api/v1/rsshub/credentials/{credential_id}", status_code=204)
async def delete_rsshub_credential(credential_id: str, request: Request) -> Response:
    await _get_rsshub_credentials_store(request).delete(credential_id)
    return Response(status_code=204)


@router.post("/api/v1/rsshub/config/env-file")
async def materialize_rsshub_env_file(request: Request) -> dict[str, object]:
    """Write the FULL env file (secret values included) server-side to a
    0600 file under the BFF data dir for apply_rsshub_config.py. The file
    content never passes through the browser; the response carries only
    counts and the file name."""
    import os as _os

    from lumirss.rsshub_control import render_env_file

    store = _get_rsshub_control_store(request)
    credentials = _get_rsshub_credentials_store(request)
    desired = await store.desired()
    custom_values = await credentials.collect_values()
    content = render_env_file(store, desired, custom_values)
    settings = LumiSettings()
    target_dir = settings.data_dir / "rsshub"
    # 0700 目录 + 建文件即 0600：secrets 不经默认权限暴露出窗口期
    target_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    _os.chmod(target_dir, 0o700)
    target = target_dir / "rsshub.env"
    tmp = target_dir / ".rsshub.env.tmp"
    fd = _os.open(tmp, _os.O_WRONLY | _os.O_CREAT | _os.O_TRUNC, 0o600)
    with _os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(content)
    _os.chmod(tmp, 0o600)
    _os.replace(tmp, target)
    _os.chmod(target, 0o600)
    secret_count = len(store.secret_configured_map()) and sum(
        1 for configured in store.secret_configured_map().values() if configured
    )
    return {
        "fileName": "rsshub.env",
        "dirName": "rsshub",
        "lineCount": len(content.splitlines()),
        "secretCount": secret_count,
        "customCredentialCount": len(custom_values),
        "note": "Written server-side (0600). Apply with apply_rsshub_config.py.",
    }


@router.put("/api/v1/rsshub/config/secrets/{key}", status_code=204)
async def put_rsshub_secret(
    key: str, body: SecretValuePut, request: Request
) -> Response:
    """Write one route credential / secret (write-only, never read back)."""
    store = _get_rsshub_control_store(request)
    await store.set_secret(key, body.value)
    return Response(status_code=204)


@router.delete("/api/v1/rsshub/config/secrets/{key}", status_code=204)
async def delete_rsshub_secret(key: str, request: Request) -> Response:
    """Clear one secret (explicit action)."""
    store = _get_rsshub_control_store(request)
    await store.delete_secret(key)
    return Response(status_code=204)


@router.post("/api/v1/rsshub/config/apply", status_code=204)
async def apply_rsshub_config(request: Request) -> Response:
    """Operator confirms the desired config has been applied after restart."""
    store = _get_rsshub_control_store(request)
    await store.mark_applied()
    return Response(status_code=204)




# ---- N029: 路由与来源关系图（我的来源 + 管理员计数聚合） ---------------------

_MAX_RECENT_ENTRIES_PER_SOURCE = 5


def _parsed_route_key_or_400(route_key: str) -> tuple[str, dict[str, str]]:
    """route_key → (template_id, 脱敏参数签名)；畸形 → 稳定 400。"""
    parsed = parse_route_key(route_key)
    if parsed is None:
        raise RssHubInvalidParameters("Malformed RSSHub route key.")
    return parsed


def _matches_route_key(
    feed_url: str, template_id: str, signature: dict[str, str]
) -> bool:
    """feed_url 是否由该 route_key（模板 + 脱敏参数）生成。

    反向映射：BFF 组合的 RSSHub feed URL = base + 模板路径（+ 可选
    query 参数）。路径段反解出模板与占位符参数，query 参数一并并入
    （订阅时刻的 route_key 同样包含 query 参数），与 route_key 的
    脱敏签名比对——敏感值两侧都是 '***' 哨兵，因此含凭据的路由也能
    匹配，而服务端从不触碰真实凭据值。"""
    from lumirss.rsshub import match_route_path

    parts = urllib.parse.urlsplit(feed_url)
    matched = match_route_path(parts.path)
    if matched is None:
        return False
    route, path_params = matched
    if route.id != template_id:
        return False
    query_pairs = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    merged = {**path_params, **dict(query_pairs)}
    return mask_params(merged) == signature


async def _projection_stats(
    request: Request, feed_url: str
) -> tuple[int, list[dict[str, str]]]:
    """(unreadCount, recentEntries≤5) —— search_entries 派生投影（可重建）。

    投影为空时返回 (0, [])：诚实口径是「投影没有该来源的数据」，UI
    文案不得把它表述成「确认没有未读」。"""
    db = request.app.state.db
    await db.migrate()
    unread_row = await db.fetch_one(
        "SELECT COUNT(*) AS n FROM search_entries WHERE feed_url = ? AND read = 0",
        (feed_url,),
    )
    recent_rows = await db.fetch_all(
        "SELECT entry_ref, title, published_at FROM search_entries "
        "WHERE feed_url = ? ORDER BY published_at DESC, id DESC LIMIT ?",
        (feed_url, _MAX_RECENT_ENTRIES_PER_SOURCE),
    )
    recent = [
        {
            "ref": str(row["entry_ref"]),
            "title": str(row["title"]),
            "published": str(row["published_at"]),
        }
        for row in recent_rows
    ]
    unread = int(unread_row["n"]) if unread_row is not None else 0
    return unread, recent


@router.get(
    "/api/v1/rsshub/routes/{route_key}/my-sources",
    response_model=RssHubRouteMySources,
    response_model_exclude_none=False,
)
async def rsshub_route_my_sources(
    route_key: str, request: Request
) -> dict[str, object]:
    """N029：该路由模板生成的**本人**订阅（路由 → 来源关系图）。

    仅当前用户作用域：control 适配器的订阅列表 + search_entries 投影
    都按请求身份路由，其他账户的数据在这里结构上不可达。"""
    template_id, signature = _parsed_route_key_or_400(route_key)
    items: list[dict[str, object]] = []
    control = _get_control_adapter(request)
    for subscription in await control.list_subscriptions():
        if not _matches_route_key(subscription.feed_url, template_id, signature):
            continue
        unread, recent = await _projection_stats(request, subscription.feed_url)
        items.append(
            {
                "feedUrl": subscription.feed_url,
                "title": subscription.title,
                "unreadCount": unread,
                "recentEntries": [
                    RssHubRouteSourceEntry(**entry) for entry in recent
                ],
            }
        )
    return {
        "routeKey": route_key,
        "templateId": template_id,
        "items": [
            {
                "feedUrl": item["feedUrl"],
                "title": item["title"],
                "unreadCount": item["unreadCount"],
                "recentEntries": item["recentEntries"],
            }
            for item in items
        ],
    }


@router.get(
    "/api/v1/admin/rsshub/routes/{route_key}/usage",
    response_model=RssHubRouteUsage,
    response_model_exclude_none=False,
)
async def rsshub_route_usage_admin(
    route_key: str, request: Request
) -> dict[str, object]:
    """N029 管理员聚合：一个路由模板在**全体活跃用户**中的使用计数。

    隐私边界（结构保证，非靠 UI 隐藏）：响应只含计数——绝不返回其他
    用户的订阅标题 / feed URL / 用户名。跨用户读取仅限派生投影的
    feed_url 匹配与条目计数（投影本就是可重建的本地派生数据）。
    member 403；遍历每用户库（邀请制小规模部署，行数有界）。"""
    guard = _admin_guard(request)
    if guard is not None:
        return guard
    template_id, signature = _parsed_route_key_or_400(route_key)
    from lumirss.accounts_store import AccountsStore

    db = request.app.state.db
    user_count = 0
    source_count = 0
    total_entries = 0
    for uid in await AccountsStore(request.app.state.control_db).active_user_ids():
        with user_context(uid):
            await db.migrate()
            feed_rows = await db.fetch_all("SELECT feed_url FROM search_feeds", ())
            user_sources = 0
            user_entries = 0
            for row in feed_rows:
                feed_url = str(row["feed_url"])
                if not _matches_route_key(feed_url, template_id, signature):
                    continue
                user_sources += 1
                count_row = await db.fetch_one(
                    "SELECT COUNT(*) AS n FROM search_entries WHERE feed_url = ?",
                    (feed_url,),
                )
                user_entries += int(count_row["n"]) if count_row else 0
        if user_sources > 0:
            user_count += 1
            source_count += user_sources
            total_entries += user_entries
    return {
        "routeKey": route_key,
        "templateId": template_id,
        "userCount": user_count,
        "sourceCount": source_count,
        "totalEntries": total_entries,
        "basis": (
            "search_feeds/search_entries 派生投影（可重建）；"
            "userCount = 拥有至少一条该路由来源的用户数；投影落后 ≠ 没有使用。"
        ),
    }


# ---- N030: 路由可复用参数方案 -------------------------------------------------


class RssHubParamPresetCreate(BaseModel):
    """POST /api/v1/rsshub/param-presets body（方案名 + 参数组合）。"""

    routeId: str = Field(min_length=1)
    params: dict[str, str] = Field(default_factory=dict)
    name: str = Field(min_length=1, max_length=80)


def _preset_store(request: Request) -> RssHubParamPresetStore:
    return RssHubParamPresetStore(request.app.state.db)


@router.get(
    "/api/v1/rsshub/param-presets",
    response_model=list[RssHubParamPresetItem],
    response_model_exclude_none=False,
)
async def list_rsshub_param_presets(request: Request) -> list[dict[str, object]]:
    """N030 我的方案（每用户私有；敏感值只以 '***' 哨兵出现）。"""
    return await _preset_store(request).list_presets()


@router.post(
    "/api/v1/rsshub/param-presets",
    status_code=201,
    response_model=RssHubParamPresetItem,
    response_model_exclude_none=False,
)
async def create_rsshub_param_preset(
    body: RssHubParamPresetCreate, request: Request
) -> dict[str, object]:
    """保存当前参数组合为方案（cap 20/用户；敏感值入库前哨兵化）。

    校验在**真实值**上做（与 preview 同 pattern 规则），存储一律
    mask_params——DB 与响应里都查不到敏感原文。"""
    route = _catalog_route(body.routeId)
    clean_params = _validate_preset_params(route, body.params)
    return await _preset_store(request).create(
        template_id=body.routeId,
        params=clean_params,
        name=body.name.strip(),
    )


@router.delete("/api/v1/rsshub/param-presets/{preset_id}", status_code=204)
async def delete_rsshub_param_preset(
    preset_id: str, request: Request
) -> Response:
    """删除一个方案；404 当该用户没有此方案（跨用户即 404）。"""
    deleted = await _preset_store(request).delete(preset_id)
    if not deleted:
        raise RssHubPresetNotFound("Parameter preset not found.")
    return Response(status_code=204)


@router.post(
    "/api/v1/rsshub/param-presets/{preset_id}/apply",
    response_model=RssHubParamPresetApply,
    response_model_exclude_none=False,
)
async def apply_rsshub_param_preset(
    preset_id: str, request: Request
) -> dict[str, object]:
    """N030 应用方案 → 参数表单回填数据（create-draft；纯只读）。

    hasSensitive 方案要求敏感键重新输入（requiresRebind=true +
    sensitiveKeys）——服务端从未存过真实值，哨兵回填本就会被 preview
    的 pattern 校验拒绝；这里把契约显式化，UI 据此标「需重新绑定」。"""
    return await _preset_store(request).apply(preset_id)


# ---- N028: 管理员级路由升级兼容检查 -------------------------------------------


def _admin_guard(request: Request) -> JSONResponse | None:
    """O167 同一 admin 语义：服务端角色判定，绝不信任请求体。"""
    from lumirss.user_scope import principal_of

    principal = principal_of(request.scope)
    if principal is None or principal.get("role") not in ("owner", "admin"):
        return JSONResponse(
            status_code=403,
            content={
                "error": {
                    "type": "forbidden",
                    "message": "Administrator role required.",
                }
            },
            headers={"Cache-Control": "no-store"},
        )
    return None


class RssHubUpgradeCheckRequest(BaseModel):
    """POST /api/v1/admin/rsshub/upgrade-check body。"""

    targetImage: str | None = Field(default=None, min_length=1, max_length=300)


@router.post(
    "/api/v1/admin/rsshub/upgrade-check",
    response_model=RssHubUpgradeCheckReport,
    response_model_exclude_none=False,
)
async def run_rsshub_upgrade_check(
    body: RssHubUpgradeCheckRequest, request: Request
) -> dict[str, object]:
    """N028 预升级路由兼容基线（admin-gated；只读探测 + 报告落库）。

    诚实范围（测试固定）：
    - 探测对象 = **管理员本人**用户库可见的路由键（订阅 URL 反推 +
      本人收藏/最近使用），每次最多 12 条真实 preview（其余 skipped）；
    - 只对**当前运行实例**探测——targetImage 恒记 pending（Lumi 无
      Docker 视角，绝不臆造「新镜像已生效」）；逐路由状态锚定到
      checkedImage（目录快照的固定镜像 sha）；
    - keep-old = 默认：本端点零镜像/容器操作，只写报告（keep-last-3）。
    """
    guard = _admin_guard(request)
    if guard is not None:
        return guard
    from lumirss.rsshub_upgrade_check import run_upgrade_check

    return await run_upgrade_check(request, target_image=body.targetImage)


@router.get(
    "/api/v1/admin/rsshub/upgrade-check",
    response_model=RssHubUpgradeChecks,
    response_model_exclude_none=False,
)
async def list_rsshub_upgrade_checks(request: Request) -> dict[str, object]:
    """N028 最近检查报告（新→旧，≤3；admin-gated，存本人用户库）。"""
    guard = _admin_guard(request)
    if guard is not None:
        return guard
    from lumirss.rsshub_upgrade_check import RssHubUpgradeCheckStore

    reports = await RssHubUpgradeCheckStore(request.app.state.db).list_reports()
    return {"items": reports}
