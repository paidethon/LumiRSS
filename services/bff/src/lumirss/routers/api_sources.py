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
    atom_base,
    atom_path,
    compute_feed_updated,
    feed_etag,
    fetch_json,
    generate_atom,
    map_items,
    secrets_match,
)
from lumirss.models import (
    ApiSource,
    ApiSourceCreate,
    ApiSourceListResponse,
    ApiSourcePreviewRequest,
    ApiSourcePreviewResult,
    ApiSourceUpdate,
)

from ..deps import _get_api_source_store, _get_control_adapter

router = APIRouter()

_PREVIEW_ITEM_LIMIT = 5


class ApiSourcePreviewError(ApiSourceExpressionError):
    """Preview-level expression failure (keeps 400 mapping readable)."""


def _model(record, *, with_secret: bool = False) -> ApiSource:
    import json as _json

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
        atom_path_value = atom_path(record.uuid, record.secret)
        for subscription in await adapter.list_subscriptions():
            if subscription.feed_url.endswith(atom_path_value):
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
    )
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
    )
    if record is None:
        raise ApiSourceNotFound(source_uuid)
    return _model(record)


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
    """Fetch + map WITHOUT saving anything; ≤5 items, honest errors."""
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
    )


@router.get("/feeds/{source_uuid}.{secret}.atom")
async def serve_atom(source_uuid: str, secret: str, request: Request) -> Response:
    """The FreshRSS-facing feed. Constant-time secret check, ETag/304,
    bounded fetch + mapping on every pull, honest error status marking.

    Last-known-good (P0-05d): success persists the rendered Atom, a
    content-derived monotonic feed updated and the matching ETag; an
    upstream failure serves that body with ``X-Lumi-Stale: 1`` (FreshRSS
    keeps its cached copy functional) and only a source with no last-good
    body falls back to the 502 stub."""
    store: ApiSourceStore = _get_api_source_store(request)
    record = await store.get(source_uuid)
    if record is None or not secrets_match(secret, record):
        raise ApiSourceNotFound(source_uuid)
    if not record.enabled:
        return Response(status_code=404, media_type="application/xml")
    try:
        data = await fetch_json(request.app.state.http_client, record.endpoint)
        items = map_items(data, record.items_expr, record.field_map)
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
    feed_updated = compute_feed_updated(
        items, record.feed_updated, record.created_at
    )
    atom = generate_atom(record, items, feed_updated, atom_base())
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
