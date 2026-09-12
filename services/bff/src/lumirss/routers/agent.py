"""Agent workbench routes (phase2 G7) + tool wiring against real services.

Every read tool goes through the SAME service layer the UI uses
(FreshRSS adapter / library store / rag service); write tools
(add_to_workspace, save_bookmark) only execute after a server-side
approval decision bound to (thread, call, tool, row args).
Tool outputs enter the model's history marked untrusted — the injection
mitigation is enforced in the loop, not the prompt alone.

P0-08 recovery (this module):

- POST /messages refuses new turns while a write approval is pending
  (stable 409 ``pending_approval``) and returns 404 for missing threads;
  the turn runs via ``AgentLoop.start_turn`` (per-thread serialization +
  run markers + honest terminal states).
- POST /threads/{id}/cancel cancels the running turn server-side; the
  loop persists a partial ``cancelled`` terminal state.
- GET /events streams REAL deltas: storage replay first, then live
  ``delta``/``message``/``done`` events from the loop's per-thread
  queues. Client disconnects never abort the run (reconnect-friendly).
- Message reads carry ``citationDetails``: every citation ref resolved
  through the shared Source Registry (title/open payload in one shot).
"""

import asyncio
import json

from fastapi import APIRouter, Request, Response

from lumirss.agent_store import (
    CANCELLED_TEXT,
    AgentStore,
    NoActiveRun,
    PendingApprovalBlocked,
    ThreadNotFound,
)
from lumirss.models import (
    AgentApprovalDecision,
    AgentMessageCreate,
    AgentThread,
    AgentThreadListResponse,
)
from lumirss.sources import resolve_item

from ..deps import (
    _get_agent_loop,
    _get_agent_store,
    _get_source_registry,
)

router = APIRouter()

# Citation resolution hits real resolvers (FreshRSS for rss refs); one
# page resolves at most this many distinct refs.
_MAX_CITATION_RESOLVES = 24
_SSE_IDLE_TIMEOUT_SECONDS = 120.0


def _thread_model(thread: dict) -> AgentThread:
    return AgentThread(
        id=thread["id"], title=thread["title"], createdAt=thread["createdAt"]
    )


async def _citation_details(
    request: Request, messages: list[dict]
) -> list[dict]:
    """Resolve the page's citation refs through the shared registry."""
    cache: dict[str, dict] = {}
    details: list[dict] = []
    registry = None
    for message in messages:
        for ref in message.get("citations") or []:
            if ref in cache:
                continue
            if len(cache) >= _MAX_CITATION_RESOLVES:
                break
            if registry is None:
                registry = _get_source_registry(request)
            try:
                resolved = await resolve_item(registry, ref)
            except Exception:  # noqa: BLE001 — a bad ref never breaks reads
                continue
            detail = resolved.to_dict()
            cache[ref] = detail
            details.append(detail)
    return details


@router.post("/api/v1/agent/threads", response_model=AgentThread, status_code=201)
async def create_thread(request: Request) -> AgentThread:
    store: AgentStore = _get_agent_store(request)
    return _thread_model(await store.create_thread())


@router.get("/api/v1/agent/threads", response_model=AgentThreadListResponse)
async def list_threads(request: Request) -> AgentThreadListResponse:
    store: AgentStore = _get_agent_store(request)
    return AgentThreadListResponse(
        items=[_thread_model(thread) for thread in await store.list_threads()]
    )


@router.delete("/api/v1/agent/threads/{thread_id}", status_code=204)
async def delete_thread(thread_id: str, request: Request) -> Response:
    store: AgentStore = _get_agent_store(request)
    loop = _get_agent_loop(request)
    loop.cancel_turn(thread_id)  # best effort: stop an in-flight turn
    deleted = await store.delete_thread(thread_id)
    if not deleted:
        raise ThreadNotFound("会话不存在。")
    return Response(status_code=204)


@router.get("/api/v1/agent/threads/{thread_id}/messages")
async def get_messages(thread_id: str, request: Request, after: int = 0):
    """REST read path (polling fallback) + resolved citation details."""
    store: AgentStore = _get_agent_store(request)
    messages = await store.messages_after(thread_id, after)
    details = await _citation_details(request, messages)
    return {"items": messages, "citationDetails": details}


@router.post("/api/v1/agent/threads/{thread_id}/messages", status_code=202)
async def post_message(
    thread_id: str, payload: AgentMessageCreate, request: Request
):
    """Queue one user turn; the loop runs to completion or to the first
    approval suspension. Result/messages are read back via /messages or
    the SSE stream (real deltas; replay on reconnect)."""
    store: AgentStore = _get_agent_store(request)
    loop = _get_agent_loop(request)
    await store.ensure_swept()
    thread = await store.get_thread(thread_id)
    if thread is None:
        raise ThreadNotFound("会话不存在。")
    # Wire expire_stale + refuse interleaving with a suspended turn.
    await store.expire_stale(thread_id)
    if await store.has_pending_approval(thread_id):
        raise PendingApprovalBlocked("有等待处理的写入批准，请先批准或拒绝。")

    task = loop.start_turn(thread_id, payload.text)
    request.app.state.agent_tasks.add(task)
    task.add_done_callback(request.app.state.agent_tasks.discard)
    return {"status": "processing"}


@router.post("/api/v1/agent/threads/{thread_id}/approvals", status_code=200)
async def decide_approval(
    thread_id: str, payload: AgentApprovalDecision, request: Request
):
    loop = _get_agent_loop(request)
    return await loop.apply_approval(
        thread_id, payload.approvalId, payload.decision
    )


@router.post("/api/v1/agent/threads/{thread_id}/cancel")
async def cancel_turn(thread_id: str, request: Request):
    """Server-side cancel: the loop finalizes a partial ``cancelled``
    state in storage (never stuck ``processing``)."""
    store: AgentStore = _get_agent_store(request)
    loop = _get_agent_loop(request)
    thread = await store.get_thread(thread_id)
    if thread is None:
        raise ThreadNotFound("会话不存在。")
    if loop.cancel_turn(thread_id):
        return {"cancelled": True, "status": "cancelling"}
    if await store.is_running(thread_id):
        # Orphaned run marker (post-restart): finalize it directly.
        final = await store.append_message(
            thread_id,
            role="assistant",
            content={"text": CANCELLED_TEXT, "cancelled": True},
        )
        await store.clear_run(thread_id)
        loop.publish(thread_id, {"type": "message", "message": final})
        loop.publish(thread_id, {"type": "turn_done", "status": "cancelled"})
        return {"cancelled": True, "status": "cancelled"}
    raise NoActiveRun("当前没有正在运行的回合。")


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/api/v1/agent/threads/{thread_id}/events")
async def stream_events(thread_id: str, request: Request, after: int = 0):
    """Real-time SSE: storage replay after `after`, then live deltas from
    the running turn until it reaches a terminal state. Disconnects never
    abort the server-side run — clients reconnect with `after` and get the
    persisted rows."""
    from fastapi.responses import StreamingResponse

    store: AgentStore = _get_agent_store(request)
    loop = _get_agent_loop(request)
    queue = loop.subscribe(thread_id)

    async def generator():
        try:
            seq = after
            replayed = await store.messages_after(thread_id, seq)
            for message in replayed:
                seq = message["seq"]
                yield _sse("message", message)
            if not await store.is_running(thread_id):
                yield _sse("done", {"status": "idle"})
                return
            idle = 0.0
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=1.0)
                except TimeoutError:
                    idle += 1.0
                    if idle >= _SSE_IDLE_TIMEOUT_SECONDS:
                        return
                    yield ": keep-alive\n\n"
                    continue
                idle = 0.0
                kind = event.get("type")
                if kind == "delta":
                    yield _sse(
                        "delta",
                        {
                            "messageId": event.get("messageId"),
                            "text": event.get("text", ""),
                            "textSoFar": event.get("textSoFar", ""),
                        },
                    )
                elif kind in ("message", "message_start"):
                    message = event.get("message") or {}
                    seq = max(seq, int(message.get("seq") or seq))
                    yield _sse("message", message)
                elif kind == "turn_done":
                    yield _sse("done", {"status": event.get("status", "completed")})
                    return
        finally:
            loop.unsubscribe(thread_id, queue)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
