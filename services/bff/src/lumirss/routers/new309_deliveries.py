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

# FIX-230：拒绝重试按真实原因上报（失败列表的操作按真实错误类型提供）。
_RETRY_REFUSALS: dict[str, tuple[int, str, str]] = {
    "attempt_cap": (
        409,
        "retry_not_allowed",
        f"该投递已达尝试上限（{MAX_ATTEMPTS} 次计划内），无法自动重试。",
    ),
    "subscription_missing": (
        409,
        "delivery_subscription_missing",
        "投递所属订阅不存在，无法重试。",
    ),
    "subscription_not_active": (
        409,
        "subscription_not_active",
        "所属订阅已撤销或暂停——权限收回后不再重试；如需继续投递，"
        "请重新创建并验证订阅。",
    ),
    "subscription_secret_missing": (
        409,
        "subscription_secret_missing",
        "订阅签名密钥缺失，无法重试；请重新创建订阅。",
    ),
}


def _refusal_response(reason: str) -> JSONResponse:
    status, error_type, message = _RETRY_REFUSALS.get(
        reason,
        (
            409,
            "retry_not_allowed",
            f"该投递已达尝试上限（{MAX_ATTEMPTS} 次计划内），无法自动重试。",
        ),
    )
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


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
        receipt, _reason = await _retry_once(store, out, row)
        if receipt is not None:
            processed += 1
    return JSONResponse({"processed": processed, "due": len(due)})


class RetryBody(BaseModel):
    model_config = {"extra": "forbid"}


@router.post("/api/v1/webhooks/deliveries/{delivery_id}/retry")
async def retry_delivery(delivery_id: int, payload: RetryBody | None = None, request: Request = None) -> Response:
    """手动重试：**同一 idempotency_key** 的下一次尝试。

    计划耗尽（exhausted）的投递也允许手动重试一次 —— 用户显式要求
    时给了第二次机会；attempt 上界仍是 MAX_ATTEMPTS 的计划内语义，
    手动重试以「新家族尝试」计数（attempt + 1，退避重新排定）。
    FIX-230：拒绝时按真实原因上报（尝试上限 / 订阅不存在 / 订阅已
    撤销暂停 / 密钥缺失），不与「尝试上限」混为一谈。"""
    store = _store(request)
    row = await store.get(delivery_id)
    if row is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": {"type": "delivery_not_found", "message": "投递不存在。"}
            },
        )
    result, refusal = await _retry_once(store, _out_store(request), row)
    if result is None:
        return _refusal_response(refusal or "attempt_cap")
    return JSONResponse(result)


async def _retry_once(
    store: DeliveryStore, out: Any, row: dict[str, Any]
) -> tuple[dict[str, Any] | None, str | None]:
    """执行一次重试；返回 (新回执, 拒绝原因)。

    复用原投递的 (subscription_id, event_uuid, idempotency_key) ——
    接收端凭同一幂等键去重，重试绝不产生重复副作用。原始载荷不
    持久化（回执只留脱敏响应），重试重发的是**当前重建的事件信封**
    （同一幂等键 + 新 occurredAt），如实标注。"""
    attempt = int(row["attempt"]) + 1
    if attempt > MAX_ATTEMPTS:
        return None, "attempt_cap"
    subscription = await out.get(int(row["subscription_id"]))
    if subscription is None:
        return None, "subscription_missing"
    if str(subscription["state"]) != "active":
        # FIX-230：撤销/暂停的订阅按真实状态拒绝——权限收回与错误
        # 配置不进入自动重试，原因如实上报而非伪装成尝试上限。
        return None, "subscription_not_active"
    secret = out.secret_for(int(row["subscription_id"]))
    if not secret:
        return None, "subscription_secret_missing"
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
        receipt = await store.record_attempt(
            subscription_id=int(row["subscription_id"]),
            event_type=str(row["event_type"]),
            event_uuid=event_uuid,
            idempotency_key=idempotency_key,
            attempt=attempt,
            ok=False,
            response_status=None,
            response_excerpt=f"[network] {type(exc).__name__}",
        )
        return receipt, None
    from lumirss.new309_delivery_receipts import sanitize_response_excerpt

    receipt = await store.record_attempt(
        subscription_id=int(row["subscription_id"]),
        event_type=str(row["event_type"]),
        event_uuid=event_uuid,
        idempotency_key=idempotency_key,
        attempt=attempt,
        ok=200 <= status < 300,
        response_status=status,
        response_excerpt=sanitize_response_excerpt(content_type, text),
    )
    return receipt, None


_INJECTABLE_SENDER: Any = None


def _injectable_sender():
    return _INJECTABLE_SENDER


def set_injectable_sender(sender: Any) -> None:
    """测试注入点（假传输）。"""
    global _INJECTABLE_SENDER
    _INJECTABLE_SENDER = sender
