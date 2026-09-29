"""NEW-308 外发 Webhook 事件订阅路由。

- POST   /api/v1/webhooks/out-subscriptions                     创建（pending，秘密/verify token 仅一次）→ 201
- GET    /api/v1/webhooks/out-subscriptions                     清单（发送范围如实展示）
- POST   /api/v1/webhooks/out-subscriptions/{id}/verify {token} 验证 → active
- POST   /api/v1/webhooks/out-subscriptions/{id}/pause          暂停
- POST   /api/v1/webhooks/out-subscriptions/{id}/resume         恢复
- DELETE /api/v1/webhooks/out-subscriptions/{id}                撤销（终态；回执保留）
- POST   /api/v1/webhooks/out-subscriptions/dispatch            触发一次事件投递（8KB 内）
"""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.new308_outbound_subscriptions import (
    EVENT_TYPES,
    OutboundSubscriptionInvalid,
    OutboundSubscriptionNotFound,
    OutboundSubscriptionStore,
    dispatch_event,
)
from lumirss.new309_delivery_receipts import DeliveryStore

router = APIRouter()


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


def _store(request: Request) -> OutboundSubscriptionStore:
    return OutboundSubscriptionStore(
        request.app.state.db, _user_secrets(request)
    )


def _user_secrets(request: Request):
    from lumirss.deps import _user_secrets as _secrets_dep

    return _secrets_dep(request)


def _deliveries(request: Request) -> DeliveryStore:
    return DeliveryStore(request.app.state.db)


class SubscriptionCreate(BaseModel):
    model_config = {"extra": "forbid"}

    eventType: str = Field(min_length=1, max_length=64)
    targetUrl: str = Field(min_length=1, max_length=2048)


class SubscriptionVerify(BaseModel):
    model_config = {"extra": "forbid"}

    token: str = Field(min_length=1, max_length=128)


class DispatchBody(BaseModel):
    model_config = {"extra": "forbid"}

    eventType: str = Field(min_length=1, max_length=64)
    data: dict[str, Any] = Field(default_factory=dict)


@router.post("/api/v1/webhooks/out-subscriptions", status_code=201)
async def create_out_subscription(payload: SubscriptionCreate, request: Request) -> Response:
    try:
        created = await _store(request).create(payload.eventType, payload.targetUrl)
    except OutboundSubscriptionInvalid as exc:
        return _error(422, "invalid_out_subscription", str(exc))
    return JSONResponse(created, status_code=201)


@router.get("/api/v1/webhooks/out-subscriptions")
async def list_out_subscriptions(request: Request) -> Response:
    store = _store(request)
    items = []
    for row in await store.list_subscriptions():
        items.append(
            {
                "id": int(row["id"]),
                "eventType": str(row["event_type"]),
                "targetUrl": str(row["target_url"]),
                "targetHost": str(row["targetHost"]),
                "state": str(row["state"]),
                "createdAt": str(row["created_at"]),
                "verifiedAt": row["verified_at"],
            }
        )
    return JSONResponse({"items": items, "eventTypes": list(EVENT_TYPES)})


async def _get_or_404(request: Request, subscription_id: int) -> dict[str, Any]:
    sub = await _store(request).get(subscription_id)
    if sub is None:
        raise OutboundSubscriptionNotFound(str(subscription_id))
    return sub


@router.post("/api/v1/webhooks/out-subscriptions/{subscription_id}/verify")
async def verify_out_subscription(
    subscription_id: int, payload: SubscriptionVerify, request: Request
) -> Response:
    ok = await _store(request).verify(subscription_id, payload.token)
    if not ok:
        return _error(403, "verification_failed", "验证令牌无效或订阅不处于待验证状态。")
    return JSONResponse({"id": subscription_id, "state": "active"})


@router.post("/api/v1/webhooks/out-subscriptions/{subscription_id}/pause")
async def pause_out_subscription(subscription_id: int, request: Request) -> Response:
    return await _transition(request, subscription_id, "paused")


@router.post("/api/v1/webhooks/out-subscriptions/{subscription_id}/resume")
async def resume_out_subscription(subscription_id: int, request: Request) -> Response:
    return await _transition(request, subscription_id, "active")


async def _transition(request: Request, subscription_id: int, state: str) -> Response:
    try:
        ok = await _store(request).set_state(subscription_id, state)
    except OutboundSubscriptionInvalid as exc:
        return _error(409, "invalid_transition", str(exc))
    if not ok:
        return _error(404, "out_subscription_not_found", "订阅不存在或已是终态。")
    return JSONResponse({"id": subscription_id, "state": state})


@router.delete("/api/v1/webhooks/out-subscriptions/{subscription_id}", status_code=204)
async def revoke_out_subscription(subscription_id: int, request: Request) -> Response:
    store = _store(request)
    sub = await store.get(subscription_id)
    if sub is None:
        return _error(404, "out_subscription_not_found", "订阅不存在。")
    try:
        ok = await store.set_state(subscription_id, "revoked")
    except OutboundSubscriptionInvalid as exc:
        return _error(409, "invalid_transition", str(exc))
    if not ok:
        return _error(409, "invalid_transition", "订阅已是终态。")
    store.delete_secret(subscription_id)
    return Response(status_code=204)


@router.post("/api/v1/webhooks/out-subscriptions/dispatch")
async def dispatch_out_event(payload: DispatchBody, request: Request) -> Response:
    """触发一次事件投递到全部 active 订阅（应用事件入口；有界 8KB）。"""
    results = await dispatch_event(
        _store(request),
        _deliveries(request),
        payload.eventType,
        payload.data,
    )
    return JSONResponse({"results": results})
