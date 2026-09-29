"""NEW-303 Webhook 接收收件箱路由。

机器侧（不持会话；中间件对 bearer 请求放行到路由边界）：
- POST /api/v1/webhooks/ingest/{uuid}   Bearer + X-Lumi-Signature → 202

用户侧（会话授权）：
- POST   /api/v1/webhooks/endpoints                      创建端点（秘密仅一次）→ 201
- GET    /api/v1/webhooks/endpoints                      端点清单（无秘密）
- DELETE /api/v1/webhooks/endpoints/{uuid}               删除端点 + 收件箱 → 204
- GET    /api/v1/webhooks/inbox?status=                  收件箱清单
- POST   /api/v1/webhooks/inbox/{id}/accept              审阅通过 → 纳入
- POST   /api/v1/webhooks/inbox/{id}/reject              审阅拒绝
"""

import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.new303_webhook_inbox import (
    WebhookInboxInvalid,
    WebhookInboxStore,
    _authorized_endpoint_or_none,
    body_digest,
    parse_event_items,
)
from lumirss.new305_dead_letters import DeadLetterStore

router = APIRouter()

_MAX_BODY_BYTES = 512 * 1024


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


def _store(request: Request) -> WebhookInboxStore:
    return WebhookInboxStore(request.app.state.db)


class EndpointCreate(BaseModel):
    model_config = {"extra": "forbid"}

    label: str = Field(min_length=1, max_length=100)


@router.post("/api/v1/webhooks/endpoints", status_code=201)
async def create_webhook_endpoint(payload: EndpointCreate, request: Request) -> Response:
    store = _store(request)
    try:
        created = await store.create_endpoint(payload.label)
    except WebhookInboxInvalid as exc:
        return _error(422, "invalid_webhook_endpoint", str(exc))
    from lumirss.machine_auth import index_machine_token

    await index_machine_token(request, created["secret"], "webhook_ingest")
    return JSONResponse(created, status_code=201)


@router.get("/api/v1/webhooks/endpoints")
async def list_webhook_endpoints(request: Request) -> Response:
    return JSONResponse({"items": await _store(request).list_endpoints()})


@router.delete("/api/v1/webhooks/endpoints/{endpoint_uuid}", status_code=204)
async def delete_webhook_endpoint(endpoint_uuid: str, request: Request) -> Response:
    if not await _store(request).delete_endpoint(endpoint_uuid):
        return _error(404, "webhook_endpoint_not_found", "端点不存在。")
    return Response(status_code=204)


@router.post("/api/v1/webhooks/ingest/{endpoint_uuid}", status_code=202)
async def ingest_webhook(endpoint_uuid: str, request: Request) -> Response:
    """机器接收：bearer 归属 + HMAC 验签 → 待确认区（绝不直入主库）。

    不可解析事件：能归属事件 id 的 → NEW-305 死信（脱敏，可修映射
    后重放）；连归属都没有 → 400。秘密/签名头从不进入日志或响应。"""
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > _MAX_BODY_BYTES:
            return _error(413, "payload_too_large", "载荷超过 512KB 上限。")
        chunks.append(chunk)
    body = b"".join(chunks)
    # 归属作用域必须覆盖**全部**后续 per-user 读写（RoutingDatabase
    # 依赖 user_context）—— authenticate 在路由内展开为 async with。
    from lumirss.machine_auth import machine_user_context

    auth = request.headers.get("authorization", "")
    supplied = auth[7:] if auth.lower().startswith("bearer ") else ""
    async with machine_user_context(request, supplied) as uid:
        if uid is not None:
            endpoint = await _authorized_endpoint_or_none(
                request, endpoint_uuid, body
            )
        else:
            endpoint = None
        if endpoint is None:
            return _error(404, "not_found", "未知端点或签名无效。")
        # —— 以下全部在归属作用域内（per-user RoutingDatabase） ——
        digest = body_digest(body)
        dead_letters = DeadLetterStore(request.app.state.db)
        try:
            event_id, items = parse_event_items(body)
        except WebhookInboxInvalid as exc:
            raw_text = body.decode("utf-8", "replace")
            await dead_letters.record(
                endpoint_uuid=endpoint_uuid,
                event_id="(unparseable)",
                reason=f"结构不可解析：{exc}",
                raw_text=raw_text,
            )
            return JSONResponse(
                status_code=400,
                content={"error": {"type": "invalid_payload", "message": str(exc)}},
            )
        if not event_id:
            await dead_letters.record(
                endpoint_uuid=endpoint_uuid,
                event_id="(no-event-id)",
                reason="缺少 eventId，无法归属事件。",
                raw_text=body.decode("utf-8", "replace"),
            )
            return JSONResponse(
                status_code=400,
                content={"error": {"type": "invalid_payload", "message": "缺少 eventId。"}},
            )
        if not items:
            await dead_letters.record(
                endpoint_uuid=endpoint_uuid,
                event_id=event_id,
                reason="载荷中没有可用的条目（缺 id 或 title）。",
                raw_text=body.decode("utf-8", "replace"),
            )
            return JSONResponse(
                status_code=202,
                content={"eventId": event_id, "stored": 0, "deadLettered": True},
            )
        store = _store(request)
        results = await store.ingest(endpoint_uuid, event_id, items, digest)
        stored = sum(1 for r in results if r["result"] == "stored")
        return JSONResponse(
            {"eventId": event_id, "endpoint": endpoint["uuid"], "stored": stored, "results": results},
            status_code=202,
        )


@router.get("/api/v1/webhooks/inbox")
async def list_webhook_inbox(request: Request, status: str | None = None) -> Response:
    return JSONResponse({"items": await _store(request).list_inbox(status=status)})


async def _decide(request: Request, inbox_id: int, accept: bool) -> Response:
    decided = await _store(request).decide(inbox_id, accept)
    if decided is None:
        return _error(404, "inbox_item_not_decidable", "条目不存在或已裁决。")
    return JSONResponse(decided)


@router.post("/api/v1/webhooks/inbox/{inbox_id}/accept")
async def accept_inbox_item(inbox_id: int, request: Request) -> Response:
    """审阅通过 = 纳入主资料库（accepted，记录裁决时刻）。"""
    return await _decide(request, inbox_id, True)


@router.post("/api/v1/webhooks/inbox/{inbox_id}/reject")
async def reject_inbox_item(inbox_id: int, request: Request) -> Response:
    return await _decide(request, inbox_id, False)


_ = json
