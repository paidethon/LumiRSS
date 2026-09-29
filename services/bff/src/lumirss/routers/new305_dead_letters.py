"""NEW-305 接入死信处理页路由。

- GET  /api/v1/webhooks/dead-letters?status=     脱敏摘要清单
- POST /api/v1/webhooks/dead-letters/{id}/replay 修正映射后重放选定事件
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from lumirss.new305_dead_letters import DeadLetterStore

router = APIRouter()


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


class ReplayBody(BaseModel):
    model_config = {"extra": "forbid"}

    rawPayload: str | None = None


@router.get("/api/v1/webhooks/dead-letters")
async def list_dead_letters(request: Request, status: str | None = None) -> Response:
    store = DeadLetterStore(request.app.state.db)
    return JSONResponse({"items": await store.list_dead_letters(status=status)})


@router.post("/api/v1/webhooks/dead-letters/{dead_letter_id}/replay")
async def replay_dead_letter(dead_letter_id: int, payload: ReplayBody | None = None, request: Request = None) -> Response:
    """重放 = 用当前接收映射重跑接入管线（与 NEW-303 同一入口）。

    - 重放成功（stored / duplicate）→ 死信标记 replayed；duplicate 时
      注明「已成功的副作用不重放」；
    - 仍失败 → 死信保持 pending，原因更新为新一次的失败原因。"""
    store = DeadLetterStore(request.app.state.db)
    letter = await store.get(dead_letter_id)
    if letter is None:
        return _error(404, "dead_letter_not_found", "死信不存在。")
    if str(letter["status"]) == "replayed":
        return _error(409, "dead_letter_already_replayed", "该死信已重放过。")
    raw_text = (
        payload.rawPayload
        if payload is not None and payload.rawPayload
        else str(letter["payload_raw"])
    )
    from lumirss.new303_webhook_inbox import (
        WebhookInboxInvalid,
        WebhookInboxStore,
        body_digest,
        parse_event_items,
    )

    inbox = WebhookInboxStore(request.app.state.db)
    endpoint_uuid = str(letter["endpoint_uuid"])
    try:
        event_id, items = parse_event_items(raw_text.encode("utf-8"))
    except WebhookInboxInvalid as exc:
        await store.record(
            endpoint_uuid=endpoint_uuid,
            event_id=str(letter["event_id"]),
            reason=f"重放仍不可解析：{exc}",
            raw_text=raw_text,
        )
        return JSONResponse(
            {
                "replayed": False,
                "reason": f"重放仍不可解析：{exc}",
                "note": "死信保持待处理；修正事件内容或映射后可再次重放。",
            }
        )
    if not event_id or not items:
        await store.record(
            endpoint_uuid=endpoint_uuid,
            event_id=str(letter["event_id"]),
            reason="重放仍无可纳入条目（缺 eventId 或全部条目缺 id/title）。",
            raw_text=raw_text,
        )
        return JSONResponse(
            {
                "replayed": False,
                "reason": "重放仍无可纳入条目。",
                "note": "死信保持待处理。",
            }
        )
    results = await inbox.ingest(
        endpoint_uuid, event_id, items, body_digest(raw_text.encode("utf-8"))
    )
    stored = sum(1 for r in results if r["result"] == "stored")
    already = any(r.get("alreadyDecided") for r in results)
    await store.mark_replayed(dead_letter_id)
    note = None
    if already and stored == 0:
        note = "该事件的副作用早已成功（已裁决/已纳入）；未重放任何新副作用。"
    return JSONResponse(
        {"replayed": True, "stored": stored, "results": results, "note": note}
    )


