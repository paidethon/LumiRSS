"""NEW-309 Webhook 投递回执路由。

- GET  /api/v1/webhooks/deliveries?subscriptionId=   回执清单（脱敏）
- POST /api/v1/webhooks/deliveries/process-due       处理到点的计划重试
- POST /api/v1/webhooks/deliveries/{id}/retry        手动重试（同一幂等标识）
"""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from lumirss.new309_delivery_receipts import (
    MAX_ATTEMPTS,
    DeliveryStore,
)

router = APIRouter()


def _store(request: Request) -> DeliveryStore:
    return DeliveryStore(request.app.state.db)


def _out_store(request: Request):
    from lumirss.deps import _user_secrets
    from lumirss.new308_outbound_subscriptions import OutboundSubscriptionStore

    return OutboundSubscriptionStore(request.app.state.db, _user_secrets(request))


def _row_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "subscriptionId": int(row["subscription_id"]),
        "eventType": str(row["event_type"]),
        "eventUuid": str(row["event_uuid"]),
        "idempotencyKey": str(row["idempotency_key"]),
        "attempt": int(row["attempt"]),
        "status": str(row["status"]),
        "responseStatus": row["response_status"],
        "responseExcerpt": row["response_excerpt"],
        "nextRetryAt": row["next_retry_at"],
        "createdAt": str(row["created_at"]),
        "finishedAt": row["finished_at"],
    }


_store_row = _row_dict


@router.get("/api/v1/webhooks/deliveries")
async def list_deliveries(request: Request, subscriptionId: int | None = None) -> Response:
    rows = await _store(request).list_deliveries(subscriptionId)
    return JSONResponse({"items": [_row_dict(row) for row in rows]})


@router.post("/api/v1/webhooks/deliveries/process-due")
async def process_due_deliveries(request: Request) -> Response:
    """处理到点的计划重试（调度入口；测试直接调用）。"""
    store = _store(request)
    out = _out_store(request)
    due = await store.due_deliveries()
    processed = 0
    for row in due:
        ok = await _retry_once(store, out, row)
        if ok is not None:
            processed += 1
    return JSONResponse({"processed": processed, "due": len(due)})


class RetryBody(BaseModel):
    model_config = {"extra": "forbid"}


@router.post("/api/v1/webhooks/deliveries/{delivery_id}/retry")
async def retry_delivery(delivery_id: int, payload: RetryBody | None = None, request: Request = None) -> Response:
    """手动重试：**同一 idempotency_key** 的下一次尝试。

    计划耗尽（exhausted）的投递也允许手动重试一次 —— 用户显式要求
    时给了第二次机会；attempt 上界仍是 MAX_ATTEMPTS 的计划内语义，
    手动重试以「新家族尝试」计数（attempt + 1，退避重新排定）。"""
    store = _store(request)
    row = await store.get(delivery_id)
    if row is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": {"type": "delivery_not_found", "message": "投递不存在。"}
            },
        )
    result = await _retry_once(store, _out_store(request), row)
    if result is None:
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "type": "retry_not_allowed",
                    "message": f"该投递已达尝试上限（{MAX_ATTEMPTS} 次计划内），无法自动重试。",
                }
            },
        )
    return JSONResponse(result)


async def _retry_once(store: DeliveryStore, out: Any, row: dict[str, Any]) -> dict[str, Any] | None:
    """执行一次重试；返回新回执，无可重试（超限/订阅不可用）→ None。

    复用原投递的 (subscription_id, event_uuid, idempotency_key) ——
    接收端凭同一幂等键去重，重试绝不产生重复副作用。原始载荷不
    持久化（回执只留脱敏响应），重试重发的是**当前重建的事件信封**
    （同一幂等键 + 新 occurredAt），如实标注。"""
    attempt = int(row["attempt"]) + 1
    if attempt > MAX_ATTEMPTS:
        return None
    subscription = await out.get(int(row["subscription_id"]))
    if subscription is None or str(subscription["state"]) != "active":
        return None
    secret = out.secret_for(int(row["subscription_id"]))
    if not secret:
        return None
    # 重发**同一幂等标识**：信封与 X-Lumi-Delivery 头一致，接收端凭
    # 该键去重 —— 重试绝不产生重复副作用。
    from lumirss.new308_outbound_subscriptions import _http_sender, sign_payload

    event_uuid = str(row["event_uuid"])
    idempotency_key = str(row["idempotency_key"])
    body, _, _ = out.build_payload(
        subscription_id=int(row["subscription_id"]),
        event_type=str(row["event_type"]),
        data={"retryOf": event_uuid, "note": "重试投递（同一幂等键）"},
        event_uuid=event_uuid,
        idempotency_key=idempotency_key,
    )
    headers = {
        "Content-Type": "application/json",
        "X-Lumi-Event": str(row["event_type"]),
        "X-Lumi-Delivery": idempotency_key,
        "X-Lumi-Signature": sign_payload(secret, body),
    }
    sender = _injectable_sender()
    try:
        status, content_type, text = await (sender or _http_sender)(
            subscription["target_url"], headers, body
        )
    except Exception as exc:
        return await store.record_attempt(
            subscription_id=int(row["subscription_id"]),
            event_type=str(row["event_type"]),
            event_uuid=event_uuid,
            idempotency_key=idempotency_key,
            attempt=attempt,
            ok=False,
            response_status=None,
            response_excerpt=f"[network] {type(exc).__name__}",
        )
    from lumirss.new309_delivery_receipts import sanitize_response_excerpt

    return await store.record_attempt(
        subscription_id=int(row["subscription_id"]),
        event_type=str(row["event_type"]),
        event_uuid=event_uuid,
        idempotency_key=idempotency_key,
        attempt=attempt,
        ok=200 <= status < 300,
        response_status=status,
        response_excerpt=sanitize_response_excerpt(content_type, text),
    )


_INJECTABLE_SENDER: Any = None


def _injectable_sender():
    return _INJECTABLE_SENDER


def set_injectable_sender(sender: Any) -> None:
    """测试注入点（假传输）。"""
    global _INJECTABLE_SENDER
    _INJECTABLE_SENDER = sender
