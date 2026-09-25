"""API source routes (phase2 M3, recovery P0-05).

Config CRUD + unsaved preview + the Atom feed endpoint. The Atom URL
lives OUTSIDE /api/* on purpose: FreshRSS dials it directly over the
docker network, where browser-session and internal-token middlewares do
not apply; the per-source secret in the path (constant-time compared)
is the credential. Auto-subscribe is best-effort with honest status —
FreshRSS being unconfigured never blocks config management. Unsubscribe,
however, is part of DELETE (P0-05e): a failed unsubscribe blocks the
delete with a stable 409 (unsubscribe_failed) so no dead subscription
keeps polling; FreshRSS-unconfigured and already-absent feeds pass
(idempotent retries converge). No force escape hatch on purpose.

Serving (P0-05b/d): every successful fetch persists the rendered Atom
plus a content-derived monotonic feed updated + ETag (migration 0019).
Upstream failures serve the last-good body with ``X-Lumi-Stale: 1`` and
the honest lastStatus in the model; 502 only when no last-good exists.
"""

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from lumirss.api_source_store import ApiSourceStore
from lumirss.api_sources import (
    ApiSourceBudgetExhausted,
    ApiSourceExpressionError,
    ApiSourceFetchFailed,
    ApiSourceInvalid,
    ApiSourceNotFound,
    ApiSourcePreviewError,
    ApiSourceRateLimited,
    atom_base,
    atom_path,
    compute_feed_updated,
    diff_schema,
    feed_etag,
    fetch_json,
    fetch_json_pages,
    generate_atom,
    map_items,
    observe_schema,
    parse_pagination,
    preview_atom_entries,
    validate_field_map,
    validate_items_expr,
    validate_pagination,
)
from lumirss.credential_rotation import (
    API_SOURCE_KIND,
    CredentialTestFailed,
    match_fallback,
    store_fallback,
)
from lumirss.models import (
    ApiSource,
    ApiSourceConfirmSchemaResult,
    ApiSourceCreate,
    ApiSourceCredentialResult,
    ApiSourceCredentialTestRequest,
    ApiSourceListResponse,
    ApiSourcePaginationDryRun,
    ApiSourcePreviewRequest,
    ApiSourcePreviewResult,
    ApiSourceSamplePreviewRequest,
    ApiSourceUpdate,
)
from lumirss.token_hash import verify_token

from ..deps import _get_api_source_store, _get_control_adapter, _user_secrets

router = APIRouter()

_PREVIEW_ITEM_LIMIT = 5
# N130: the credential probe runs the real request shape under a tight
# bound (bounded 5s) and never persists anything it sees.
_PROBE_TIMEOUT_SECONDS = 5.0


def _model(record, *, with_secret: bool = False) -> ApiSource:
    import json as _json
    from datetime import UTC, datetime

    drift = None
    if record.schema_drift:
        try:
            drift = _json.loads(record.schema_drift)
        except _json.JSONDecodeError:
            drift = None
    # N129: only a FUTURE next_allowed_run is worth showing — a past one
    # means the source may run again right now, so report None honestly.
    next_allowed = record.next_allowed_run
    if next_allowed is not None:
        try:
            target = datetime.fromisoformat(next_allowed.replace("Z", "+00:00"))
            if target.tzinfo is None:
                target = target.replace(tzinfo=UTC)
            if target <= datetime.now(UTC):
                next_allowed = None
        except ValueError:
            next_allowed = None
    return ApiSource(
        uuid=record.uuid,
        name=record.name,
        endpoint=record.endpoint,
        itemsExpr=record.items_expr,
        fieldMap=_json.loads(record.field_map),
        enabled=record.enabled,
        lastStatus=record.last_status,
        lastSuccessAt=record.last_success_at,
        lastError=record.last_error,
        createdAt=record.created_at,
        secret=record.secret if with_secret else None,
        atomPath=atom_path(record.uuid, record.secret) if with_secret else None,
        pagination=_json.loads(record.pagination),
        confirmedSchema=bool(record.confirmed_schema),
        schemaDrift=drift,
        maxRunsPerHour=record.max_runs_per_hour,
        respectRetryAfter=record.respect_retry_after,
        nextAllowedRun=next_allowed,
    )


async def _subscribe_best_effort(request: Request, record, atom_url: str) -> str | None:
    """Auto-subscribe FreshRSS; returns None on success, error text else."""
    try:
        adapter = _get_control_adapter(request)
    except Exception:  # FreshRSS not configured — honest status, no crash
        return "FreshRSS 未配置：未自动订阅"
    try:
        await adapter.subscribe(atom_url, title=record.name)
        return None
    except Exception as exc:  # noqa: BLE001 — best-effort by contract
        return f"自动订阅失败：{exc}"


async def _unsubscribe_required(request: Request, record) -> str | None:
    """Unsubscribe is part of delete (P0-05e), not best-effort.

    Returns None when the FreshRSS subscription is gone (unsubscribed,
    already absent, or FreshRSS unconfigured so none can exist — delete
    retries stay idempotent); otherwise an honest error text that BLOCKS
    the delete, keeping the source alive so the operator can retry."""
    try:
        adapter = _get_control_adapter(request)
    except Exception:  # FreshRSS not configured — no subscription can exist
        return None
    try:
        # §13.4：存储值已是哈希——不能再用其拼 URL 匹配（订阅时用的是
        # 创建时刻的一次性明文）。与本文件同构的 mail 域同解：按 uuid
        # 路径段匹配本 source 的身份（相近 uuid/不同 host 均不误判）。
        from urllib.parse import urlsplit

        prefix = f"/feeds/{record.uuid}."
        for subscription in await adapter.list_subscriptions():
            path = urlsplit(subscription.feed_url).path
            if path.startswith(prefix) and path.endswith(".atom"):
                await adapter.unsubscribe(subscription.stream_id)
                return None
        return None  # already absent → idempotent success
    except Exception as exc:  # noqa: BLE001 — honest blocking error
        return f"取消订阅失败：{exc}"


@router.post("/api/v1/api-sources", response_model=ApiSource, status_code=201)
async def create_source(payload: ApiSourceCreate, request: Request) -> ApiSource:
    store: ApiSourceStore = _get_api_source_store(request)
    record = await store.create(
        name=payload.name,
        endpoint=payload.endpoint,
        items_expr=payload.itemsExpr,
        field_map=payload.fieldMap,
        pagination=payload.pagination,
        max_runs_per_hour=payload.maxRunsPerHour,
    )
    from lumirss.machine_auth import index_machine_token

    await index_machine_token(request, record.secret, "api_source")
    base = atom_base()
    atom_url = base + atom_path(record.uuid, record.secret)
    subscribe_error = None
    if payload.subscribe:
        subscribe_error = await _subscribe_best_effort(request, record, atom_url)
        if subscribe_error is not None:
            await store.mark_error(record.uuid, "subscribe_failed", subscribe_error)
    response = _model(record, with_secret=True)
    response.subscribeError = subscribe_error
    return response


@router.get("/api/v1/api-sources", response_model=ApiSourceListResponse)
async def list_sources(request: Request) -> ApiSourceListResponse:
    store: ApiSourceStore = _get_api_source_store(request)
    records = await store.list_sources()
    return ApiSourceListResponse(items=[_model(record) for record in records])


@router.patch("/api/v1/api-sources/{source_uuid}", response_model=ApiSource)
async def update_source(
    source_uuid: str, payload: ApiSourceUpdate, request: Request
) -> ApiSource:
    store: ApiSourceStore = _get_api_source_store(request)
    record = await store.update(
        source_uuid,
        name=payload.name,
        endpoint=payload.endpoint,
        items_expr=payload.itemsExpr,
        field_map=payload.fieldMap,
        enabled=payload.enabled,
        pagination=payload.pagination,
        max_runs_per_hour=payload.maxRunsPerHour,
    )
    if record is None:
        raise ApiSourceNotFound(source_uuid)
    return _model(record)


@router.post(
    "/api/v1/api-sources/{source_uuid}/confirm-schema",
    response_model=ApiSourceConfirmSchemaResult,
)
async def confirm_schema(
    source_uuid: str, request: Request
) -> ApiSourceConfirmSchemaResult:
    """F043: re-snapshot the user-confirmed structure baseline.

    Fetches the upstream once (single-shot, bounded), maps with the
    saved mapping and stores the observed field schema as the baseline;
    drift warnings clear with it. Nothing else changes."""
    store: ApiSourceStore = _get_api_source_store(request)
    record = await store.get(source_uuid)
    if record is None:
        raise ApiSourceNotFound(source_uuid)
    data = await fetch_json(request.app.state.http_client, record.endpoint)
    items = map_items(data, record.items_expr, record.field_map)
    await store.confirm_schema(source_uuid, items)
    return ApiSourceConfirmSchemaResult(confirmed=bool(items), sampledItems=len(items))


@router.delete("/api/v1/api-sources/{source_uuid}", status_code=204)
async def delete_source(source_uuid: str, request: Request) -> Response:
    """Delete requires a successful FreshRSS unsubscribe first (P0-05e).

    A failed unsubscribe returns the stable 409 ``unsubscribe_failed``
    envelope and keeps the source, so no dead subscription keeps polling
    a removed URL. No ``force`` param by design: FreshRSS-unconfigured
    and already-absent feeds already pass (idempotent), and decommissioning
    FreshRSS (unsetting its env) re-enables deletion."""
    store: ApiSourceStore = _get_api_source_store(request)
    record = await store.get(source_uuid)
    if record is None:
        raise ApiSourceNotFound(source_uuid)
    unsubscribe_error = await _unsubscribe_required(request, record)
    if unsubscribe_error is not None:
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "type": "unsubscribe_failed",
                    "message": unsubscribe_error,
                }
            },
        )
    await store.delete(source_uuid)
    return Response(status_code=204)


@router.post(
    "/api/v1/api-sources/preview",
    response_model=ApiSourcePreviewResult,
)
async def preview_source(
    payload: ApiSourcePreviewRequest, request: Request
) -> ApiSourcePreviewResult:
    """Fetch + map WITHOUT saving anything; ≤5 items, honest errors.

    F041: ``atomPreview`` shows the first ≤3 entries in their final
    Atom-rendered shape (stable urn ids, RFC 3339 timestamps, bounded
    content excerpts) via the exact production pipeline. F042:
    ``dryRunPagination`` walks the configured pagination against the
    live upstream and reports {pages, stopReason} — still zero writes.
    Upstream response headers are never echoed (the response model has
    no such field by construction)."""
    validate_field_map(payload.fieldMap)
    validate_pagination(payload.pagination)
    if payload.dryRunPagination:
        return await _dry_run_pagination(payload, request)
    data = await fetch_json(request.app.state.http_client, payload.endpoint.strip())
    try:
        items = map_items(data, payload.itemsExpr.strip(), payload.fieldMap)
    except ApiSourceExpressionError as exc:
        raise ApiSourcePreviewError(str(exc)) from exc
    return ApiSourcePreviewResult(
        items=[
            {key: item.get(key) for key in item}
            for item in items[:_PREVIEW_ITEM_LIMIT]
        ],
        totalAvailable=len(items),
        atomPreview=preview_atom_entries(items),
    )


@router.post(
    "/api/v1/api-sources/preview-sample",
    response_model=ApiSourcePreviewResult,
)
async def preview_sample_source(
    payload: ApiSourceSamplePreviewRequest, request: Request
) -> ApiSourcePreviewResult:
    """N128 离线样例预览：the SAME mapping + Atom-preview pipeline as the
    live preview, run on the PASTED sample.

    Zero network (the endpoint is never dialed), zero storage (nothing
    about the request — payload, expressions, and there are no auth
    headers in play at all — is written anywhere), and no header echo by
    construction (the response model has no such field). ``sampleMode``
    marks the response honestly as offline. A sample that maps to ZERO
    items (missing id/title fields, wrong items expression) is surfaced
    as a stable 422 — missing data is never fabricated."""
    validate_items_expr(payload.itemsExpr)
    validate_field_map(payload.fieldMap)
    try:
        items = map_items(payload.samplePayload, payload.itemsExpr.strip(), payload.fieldMap)
    except ApiSourceExpressionError as exc:
        raise ApiSourcePreviewError(str(exc)) from exc
    if not items:
        raise ApiSourcePreviewError(
            "样例映射结果为空：请检查 items 表达式与 id/title 字段映射"
            "（样例中缺失的字段不会被编造）。"
        )
    return ApiSourcePreviewResult(
        items=[
            {key: item.get(key) for key in item}
            for item in items[:_PREVIEW_ITEM_LIMIT]
        ],
        totalAvailable=len(items),
        atomPreview=preview_atom_entries(items),
        sampleMode=True,
    )


# -- N130 来源秘密轮换预演 -----------------------------------------------------


async def _probe_api_source_endpoint(record, request: Request) -> ApiSourceCredentialResult:
    """Read-only dry probe of the source's endpoint (same request shape
    as a real fetch, bounded 5s). No persistence: the probe writes
    nothing to last_status/last-good — it is a rehearsal, not a run."""
    import time

    from lumirss.adapters.freshrss import (
        AuthenticationError,
        UpstreamConnectionError,
    )

    started = time.monotonic()

    def _result(ok: bool, status_class: str) -> ApiSourceCredentialResult:
        return ApiSourceCredentialResult(
            ok=ok,
            statusClass=status_class,
            latencyMs=max(0, int((time.monotonic() - started) * 1000)),
        )

    try:
        await fetch_json(
            request.app.state.http_client,
            record.endpoint,
            timeout_seconds=_PROBE_TIMEOUT_SECONDS,
        )
    except ApiSourceRateLimited:
        # A 429 IS a reachable, answering endpoint — the credential is
        # not the problem. Honest class, probe not counted as failure.
        return _result(True, "rate_limited")
    except ApiSourceFetchFailed as exc:
        if "HTTP 4" in str(exc) or "HTTP 5" in str(exc):
            return _result(False, "http_error")
        if "JSON" in str(exc):
            return _result(False, "invalid_payload")
        return _result(False, "network_error")
    except (AuthenticationError, UpstreamConnectionError):
        return _result(False, "network_error")
    return _result(True, "ok")


def _secrets(request: Request):
    return _user_secrets(request)


@router.post(
    "/api/v1/api-sources/{source_uuid}/credentials/test",
    response_model=ApiSourceCredentialResult,
)
async def test_api_source_credential(
    source_uuid: str, payload: ApiSourceCredentialTestRequest, request: Request
) -> ApiSourceCredentialResult:
    """N130 轮换预演（API 来源）：shape check + read-only endpoint probe.

    Nothing is swapped; the current credential stays live no matter the
    outcome. The response is masked ({ok, statusClass, latencyMs}) — the
    credential and every header stay unechoed."""
    store: ApiSourceStore = _get_api_source_store(request)
    record = await store.get(source_uuid)
    if record is None:
        raise ApiSourceNotFound(source_uuid)
    return await _run_credential_test(payload, record, request)


@router.post(
    "/api/v1/api-sources/{source_uuid}/credentials/rotate",
    response_model=ApiSourceCredentialResult,
)
async def rotate_api_source_credential(
    source_uuid: str, payload: ApiSourceCredentialTestRequest, request: Request
) -> ApiSourceCredentialResult:
    """N130 测试并轮换（API 来源）：test first, then one-statement swap.

    The probe (shape + endpoint reachability, read-only) runs INSIDE the
    same request boundary before any write: a failure raises the stable
    422 ``credential_test_failed`` and the current credential is
    UNTOUCHED. On success the stored hash is swapped atomically, the new
    token is indexed for the machine channel, and the OLD hash is parked
    in the user's SecretsStore for a 10-minute fallback window (reads
    prefer the new credential; a fallback hit is flagged on the source)
    until the lazy sweep prunes it. The response is masked — no secret,
    no atom path echo."""
    store: ApiSourceStore = _get_api_source_store(request)
    record = await store.get(source_uuid)
    if record is None:
        raise ApiSourceNotFound(source_uuid)
    probe = await _run_credential_test(payload, record, request)
    if not probe.ok:
        raise CredentialTestFailed(
            probe.statusClass,
            f"新凭据预演未通过（{probe.statusClass}），当前凭据未改动。请先解决端点问题再轮换。",
        )
    from lumirss.machine_auth import index_machine_token

    old_hash = await store.swap_secret_hash(source_uuid, payload.newCredential)
    await index_machine_token(request, payload.newCredential, "api_source")
    if old_hash is not None:
        store_fallback(_secrets(request), API_SOURCE_KIND, source_uuid, old_hash)
    return ApiSourceCredentialResult(
        ok=True,
        statusClass="ok",
        latencyMs=probe.latencyMs,
        note=(
            "已轮换。新 Atom 地址 = /feeds/"
            f"{source_uuid}.<新凭据>.atom（请在宽限期内替换 FreshRSS 订阅；"
            "旧地址保留 10 分钟，之后失效）。"
        ),
    )


async def _run_credential_test(
    payload: ApiSourceCredentialTestRequest, record, request: Request
) -> ApiSourceCredentialResult:
    """Shared test-first step: shape gate then endpoint probe."""
    try:
        from lumirss.credential_rotation import validate_credential_shape

        validate_credential_shape(payload.newCredential)
    except CredentialTestFailed as exc:
        raise CredentialTestFailed(exc.status_class, str(exc)) from exc
    return await _probe_api_source_endpoint(record, request)


async def _dry_run_pagination(
    payload: ApiSourcePreviewRequest, request: Request
) -> ApiSourcePreviewResult:
    """Walk pagination page by page; report counts + stop reason, no writes."""
    from lumirss.api_sources import parse_pagination

    config = parse_pagination(validate_pagination(payload.pagination))
    max_pages = int(config.get("max_pages", 5))
    max_items = int(config.get("max_items", 200))
    try:
        payloads, stop_reason = await fetch_json_pages(
            request.app.state.http_client,
            payload.endpoint.strip(),
            validate_pagination(payload.pagination),
            payload.itemsExpr.strip(),
        )
        pages: list[dict[str, object]] = []
        total = 0
        for index, data in enumerate(payloads):
            try:
                items = map_items(data, payload.itemsExpr.strip(), payload.fieldMap)
            except ApiSourceExpressionError as exc:
                raise ApiSourcePreviewError(str(exc)) from exc
            total += len(items)
            pages.append({"index": index + 1, "mappedItems": len(items)})
        return ApiSourcePreviewResult(
            items=[],  # dry-run reports page stats only; items stay bounded above
            totalAvailable=total,
            paginationDryRun=ApiSourcePaginationDryRun(
                pages=pages, stopReason=stop_reason
            ),
        )
    except ApiSourceFetchFailed as exc:
        _ = (max_pages, max_items)
        raise ApiSourcePreviewError(f"分页试跑失败：{exc}") from exc


@router.get("/feeds/{source_uuid}.{secret}.atom")
async def serve_atom(source_uuid: str, secret: str, request: Request) -> Response:
    """The FreshRSS-facing feed. Constant-time secret check, ETag/304,
    bounded fetch + mapping on every pull, honest error status marking.

    Last-known-good (P0-05d): success persists the rendered Atom, a
    content-derived monotonic feed updated and the matching ETag; an
    upstream failure serves that body with ``X-Lumi-Stale: 1`` (FreshRSS
    keeps its cached copy functional) and only a source with no last-good
    body falls back to the 502 stub.

    N129 限额友好：every upstream run consults a persisted per-source
    token bucket (api_source_runs, trailing hour, pruned on consult);
    over budget → 429 ``budget_exhausted`` + Retry-After (FreshRSS
    backs off — that is the point). An upstream 429 with Retry-After
    stores ``next_allowed_run`` and serves the last-good body. Lumi
    never works around a rate limit (no alternate credentials, no
    retries that dodge the upstream's verdict)."""
    from lumirss.machine_auth import resolve_machine_user

    uid = await resolve_machine_user(request, secret)
    if uid is None:
        # session 模式下未知 token：与「源不存在」同一 404，不泄露存在性
        raise ApiSourceNotFound(source_uuid)
    store: ApiSourceStore = _get_api_source_store(request)
    record = await store.get(source_uuid)
    used_fallback = False
    if record is None or not verify_token(secret, record.secret):
        # N130 fallback window: a just-rotated source honors the OLD
        # credential for 10 minutes — the hit is flagged below (after the
        # run outcome is recorded, so the flag survives mark_success).
        # Existence never leaks (same 404 as an unknown token when
        # neither matches).
        if record is not None and match_fallback(
            _secrets(request), API_SOURCE_KIND, source_uuid, secret
        ):
            used_fallback = True
        else:
            raise ApiSourceNotFound(source_uuid)
    if not record.enabled:
        return Response(status_code=404, media_type="application/xml")
    # N129: the persisted token bucket decides whether this pull may
    # hit the upstream at all.
    blocked_until = await store.exhausted_until(
        source_uuid, record.max_runs_per_hour
    )
    if blocked_until is not None:
        await store.set_next_allowed_run(source_uuid, blocked_until)
        raise ApiSourceBudgetExhausted(blocked_until)
    try:
        if parse_pagination(record.pagination).get("mode", "none") == "none":
            await store.record_run(source_uuid)
            payloads = [await fetch_json(request.app.state.http_client, record.endpoint)]
        else:
            await store.record_run(source_uuid)
            payloads, _stop_reason = await fetch_json_pages(
                request.app.state.http_client,
                record.endpoint,
                record.pagination,
                record.items_expr,
            )
        items: list[dict[str, object]] = []
        for payload in payloads:
            items.extend(map_items(payload, record.items_expr, record.field_map))
    except ApiSourceRateLimited as exc:
        # N129: honor the upstream's Retry-After — persist the verdict,
        # serve the last-known-good body, never dodge the limit.
        from datetime import UTC, datetime, timedelta

        seconds = exc.retry_after_seconds if exc.retry_after_seconds is not None else 3600
        next_allowed = (
            datetime.now(UTC) + timedelta(seconds=seconds)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
        await store.set_next_allowed_run(source_uuid, next_allowed)
        await store.mark_error(
            source_uuid,
            "rate_limited",
            f"上游限流（HTTP 429），下次允许运行时间：{next_allowed}。遇限流将等待，不使用替代密钥规避。",
        )
        if record.atom_body:
            return _stale_atom_response(record, request)
        return Response(
            status_code=502,
            media_type="application/xml",
            content="<error>upstream rate limited</error>",
        )
    except ApiSourceFetchFailed as exc:
        await store.mark_error(record.uuid, "fetch_failed", str(exc))
        if record.atom_body:
            return _stale_atom_response(record, request)
        return Response(
            status_code=502,
            media_type="application/xml",
            content="<error>upstream fetch failed</error>",
        )
    except ApiSourceExpressionError as exc:
        await store.mark_error(record.uuid, "bad_expression", str(exc))
        if record.atom_body:
            return _stale_atom_response(record, request)
        return Response(
            status_code=502,
            media_type="application/xml",
            content="<error>bad expression</error>",
        )
    # F043: structure drift against the user-confirmed baseline is
    # advisory — recorded, never blocks serving. Empty mapped responses
    # never overwrite the last-known-good feed (honest stale instead).
    if not items and record.atom_body:
        await store.mark_error(
            record.uuid, "empty_response", "上游响应映射结果为空，保留上次内容。"
        )
        return _stale_atom_response(record, request)
    drift = diff_schema(record.confirmed_schema, observe_schema(items))
    if drift is not None:
        await store.mark_drift(record.uuid, drift)
    pagination = parse_pagination(record.pagination)
    max_entries = int(pagination.get("max_items", 100)) if pagination.get("mode", "none") != "none" else 100
    feed_updated = compute_feed_updated(
        items, record.feed_updated, record.created_at
    )
    atom = generate_atom(record, items, feed_updated, atom_base(), max_entries=max_entries)
    etag = feed_etag(atom)
    await store.mark_success(record.uuid, etag, atom, feed_updated)
    if used_fallback:
        # N130: flag AFTER mark_success so the fallback warning survives
        # as the source's latest honest status.
        await store.mark_error(
            record.uuid,
            "fallback_used",
            "旧凭据在宽限期内被使用：请尽快更新 FreshRSS 订阅地址为新 Atom URL。",
        )
    if_none_match = request.headers.get("if-none-match")
    if if_none_match is not None and if_none_match.strip() == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return Response(
        content=atom,
        media_type="application/atom+xml; charset=utf-8",
        headers={"ETag": etag},
    )


def _stale_atom_response(record, request: Request) -> Response:
    """Serve the persisted last-good body with honest stale marking
    (conditional GET honored against the persisted ETag)."""
    etag = record.etag or feed_etag(record.atom_body)
    if_none_match = request.headers.get("if-none-match")
    if if_none_match is not None and if_none_match.strip() == etag:
        return Response(status_code=304, headers={"ETag": etag, "X-Lumi-Stale": "1"})
    return Response(
        content=record.atom_body,
        media_type="application/atom+xml; charset=utf-8",
        headers={"ETag": etag, "X-Lumi-Stale": "1"},
    )


_ = (ApiSourceInvalid, ApiSourceNotFound, ApiSourceFetchFailed)
