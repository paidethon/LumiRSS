"""API source routes (phase2 M3).

Config CRUD + unsaved preview + the Atom feed endpoint. The Atom URL
lives OUTSIDE /api/* on purpose: FreshRSS dials it directly over the
docker network, where browser-session and internal-token middlewares do
not apply; the per-source secret in the path (constant-time compared)
is the credential. Auto-subscribe is best-effort with honest status —
FreshRSS being unconfigured never blocks config management.
"""

from fastapi import APIRouter, Request, Response

from lumirss.api_source_store import ApiSourceStore
from lumirss.api_sources import (
    ApiSourceExpressionError,
    ApiSourceFetchFailed,
    ApiSourceInvalid,
    ApiSourceNotFound,
    atom_path,
    feed_etag,
    fetch_json,
    generate_atom,
    map_items,
    secrets_match,
)
from lumirss.config import LumiSettings
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


async def _unsubscribe_best_effort(request: Request, record) -> str | None:
    try:
        adapter = _get_control_adapter(request)
    except Exception:
        return None
    try:
        atom_path_value = atom_path(record.uuid, record.secret)
        for subscription in await adapter.list_subscriptions():
            if subscription.feed_url.endswith(atom_path_value):
                await adapter.unsubscribe(subscription.stream_id)
                return None
        return None
    except Exception as exc:  # noqa: BLE001
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
    base = LumiSettings().LUMIRSS_ATOM_BASE_URL or "http://127.0.0.1:8000"
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
    store: ApiSourceStore = _get_api_source_store(request)
    record = await store.get(source_uuid)
    if record is None:
        raise ApiSourceNotFound(source_uuid)
    await _unsubscribe_best_effort(request, record)
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
    bounded fetch + mapping on every pull, honest error status marking."""
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
        return Response(
            status_code=502,
            media_type="application/xml",
            content="<error>upstream fetch failed</error>",
        )
    except ApiSourceExpressionError as exc:
        await store.mark_error(record.uuid, "bad_expression", str(exc))
        return Response(
            status_code=502,
            media_type="application/xml",
            content="<error>bad expression</error>",
        )
    atom = generate_atom(record, items, self_base="")
    etag = feed_etag(atom)
    await store.mark_success(record.uuid, etag)
    if_none_match = request.headers.get("if-none-match")
    if if_none_match is not None and if_none_match.strip() == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return Response(
        content=atom,
        media_type="application/atom+xml; charset=utf-8",
        headers={"ETag": etag},
    )


_ = (ApiSourceInvalid, ApiSourceNotFound, ApiSourceFetchFailed)
