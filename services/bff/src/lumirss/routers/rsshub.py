"""Rsshub routes (moved verbatim from main.py)."""


import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Literal

import httpx
from fastapi import APIRouter, Query, Request, Response
from pydantic import BaseModel, Field

from lumirss.config import LumiSettings, _validate_service_base_url
from lumirss.deps import (
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
    RssHubPreviewResult,
    RssHubRecentItem,
    RssHubRefreshResult,
    RssHubRouteRuns,
)
from lumirss.routers.ai_settings import SecretValuePut
from lumirss.rsshub import (
    FAILURE_BAD_CONTENT,
    FAILURE_NO_NEW_CONTENT,
    NO_NEW_CONTENT_WINDOW,
    RssHubFetchError,
    RssHubInvalidParameters,
    RssHubNotConfigured,
    RssHubRefreshRateLimited,
    RssHubRouteNotFound,
)
from lumirss.rsshub_control import (
    RssHubInvalidValue,
    config_view,
)
from lumirss.rsshub_route_store import (
    RssHubRouteStore,
    compute_route_key,
    parse_route_key,
)
from lumirss.user_scope import require_user_id
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
    if override is None:
        hit = cache.get(user_id, route_key)
        if hit is not None:
            cached_preview, age_s = hit
            data = _preview_json(cached_preview)
            data["routeKey"] = route_key
            data["cache"] = {"ageS": age_s, "fresh": False}
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


