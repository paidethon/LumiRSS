"""Agent workbench routes (phase2 G7) + tool wiring against real services.

Every read tool goes through the SAME service layer the UI uses
(FreshRSS adapter / library store / rag service); write tools
(add_to_workspace, save_bookmark) only execute after a server-side
approval decision bound to (thread, call, tool, canonical args hash).
Tool outputs enter the model's history marked untrusted — the injection
mitigation is enforced in the loop, not the prompt alone.
"""

import asyncio
import json

from fastapi import APIRouter, Request, Response

from lumirss.agent import AgentProviderUnavailable
from lumirss.agent_store import AgentStore
from lumirss.models import (
    AgentApprovalDecision,
    AgentMessageCreate,
    AgentThread,
    AgentThreadListResponse,
)

from ..deps import (
    _get_agent_loop,
    _get_agent_store,
)

router = APIRouter()


def _thread_model(thread: dict) -> AgentThread:
    return AgentThread(
        id=thread["id"], title=thread["title"], createdAt=thread["createdAt"]
    )


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
    deleted = await store.delete_thread(thread_id)
    if not deleted:
        from lumirss.agent_store import ApprovalInvalid

        raise ApprovalInvalid("会话不存在。")
    return Response(status_code=204)


@router.get("/api/v1/agent/threads/{thread_id}/messages")
async def get_messages(thread_id: str, request: Request, after: int = 0):
    store: AgentStore = _get_agent_store(request)
    messages = await store.messages_after(thread_id, after)
    return {"items": messages}


@router.post("/api/v1/agent/threads/{thread_id}/messages", status_code=202)
async def post_message(
    thread_id: str, payload: AgentMessageCreate, request: Request
):
    """Queue one user turn; the loop runs to completion or to the first
    approval suspension. Result/messages are read back via /messages or
    the SSE stream (replay-friendly)."""
    store: AgentStore = _get_agent_store(request)
    loop = _get_agent_loop(request)
    thread = await store.get_thread(thread_id)
    if thread is None:
        from lumirss.agent_store import ApprovalInvalid

        raise ApprovalInvalid("会话不存在。")

    async def run() -> None:
        try:
            await loop.run_turn(thread_id, payload.text)
        except AgentProviderUnavailable as exc:
            await store.append_message(
                thread_id, role="assistant", content={"text": str(exc)}
            )
        except Exception as exc:  # noqa: BLE001 — provider errors are data
            await store.append_message(
                thread_id,
                role="assistant",
                content={"text": f"处理失败：{exc}"},
            )

    task = asyncio.create_task(run())
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


@router.get("/api/v1/agent/threads/{thread_id}/events")
async def stream_events(thread_id: str, request: Request, after: int = 0):
    """SSE replay: streams all messages after `after` then closes — the
    client re-subscribes while a turn is processing (simple, reconnect
    safe, no server-side push state)."""
    from fastapi.responses import StreamingResponse

    store: AgentStore = _get_agent_store(request)

    async def generator():
        seq = after
        idle = 0
        while True:
            messages = await store.messages_after(thread_id, seq)
            for message in messages:
                seq = message["seq"]
                payload = json.dumps(message, ensure_ascii=False)
                yield f"id: {seq}\nevent: message\ndata: {payload}\n\n"
            if messages:
                idle = 0
                last_role = messages[-1]["role"]
                pending = await store.has_pending_approval(thread_id)
                if last_role in ("assistant",) or (last_role == "tool" and not pending):
                    return
            else:
                idle += 1
                if idle > 60:  # ~60s without events → close (client re-polls)
                    return
                yield ": keep-alive\n\n"
                await asyncio.sleep(1.0)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

