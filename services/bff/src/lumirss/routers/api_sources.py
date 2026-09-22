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
    ApiSourceExpressionError,
    ApiSourceFetchFailed,
    ApiSourceInvalid,
    ApiSourceNotFound,
    ApiSourcePreviewError,
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
    validate_pagination,
)
from lumirss.models import (
    ApiSource,
    ApiSourceConfirmSchemaResult,
    ApiSourceCreate,
    ApiSourceListResponse,
    ApiSourcePaginationDryRun,
    ApiSourcePreviewRequest,
    ApiSourcePreviewResult,
    ApiSourceUpdate,
)
from lumirss.token_hash import verify_token

from ..deps import _get_api_source_store, _get_control_adapter

router = APIRouter()

_PREVIEW_ITEM_LIMIT = 5


def _model(record, *, with_secret: bool = False) -> ApiSource:
    import json as _json

    drift = None
    if record.schema_drift:
        try:
            drift = _json.loads(record.schema_drift)
        except _json.JSONDecodeError:
            drift = None
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
    body falls back to the 502 stub."""
    from lumirss.machine_auth import resolve_machine_user

    uid = await resolve_machine_user(request, secret)
    if uid is None:
        # session 模式下未知 token：与「源不存在」同一 404，不泄露存在性
        raise ApiSourceNotFound(source_uuid)
    store: ApiSourceStore = _get_api_source_store(request)
    record = await store.get(source_uuid)
    if record is None or not verify_token(secret, record.secret):
        raise ApiSourceNotFound(source_uuid)
    if not record.enabled:
        return Response(status_code=404, media_type="application/xml")
    try:
        if parse_pagination(record.pagination).get("mode", "none") == "none":
            payloads = [await fetch_json(request.app.state.http_client, record.endpoint)]
        else:
            payloads, _stop_reason = await fetch_json_pages(
                request.app.state.http_client,
                record.endpoint,
                record.pagination,
                record.items_expr,
            )
        items: list[dict[str, object]] = []
        for payload in payloads:
            items.extend(map_items(payload, record.items_expr, record.field_map))
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
