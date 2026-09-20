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
    AgentBranchRequest,
    AgentMessageCreate,
    AgentThread,
    AgentThreadListResponse,
    AgentThreadUpdate,
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


# ---------------------------------------------------------------------------
# W5: F094 范围 / F095 搜索 / F096 导出 / F097 预演 / F099 分支
# ---------------------------------------------------------------------------


def _session_store(request: Request):
    from lumirss.agent_session import AgentSessionStore

    return AgentSessionStore(request.app.state.db, _get_agent_store(request))


@router.get("/api/v1/agent/threads/search")
async def search_threads(request: Request, q: str):
    """F095：会话消息搜索（每线程扫描 ≤200 条、总结果 ≤50）。"""
    from lumirss.agent_session import SearchInvalid

    try:
        items = await _session_store(request).search_messages(q)
    except SearchInvalid as exc:
        from fastapi.responses import JSONResponse

        return JSONResponse(
            status_code=422,
            content={
                "error": {"type": "invalid_search_query", "message": str(exc)}
            },
        )
    return {"items": items, "truncated": len(items) >= 50}


@router.patch("/api/v1/agent/threads/{thread_id}")
async def update_thread_settings(
    thread_id: str, payload: AgentThreadUpdate, request: Request
):
    """F094/F098：会话设置（scope / toolPolicy / 标题）。下轮生效。"""
    store = _session_store(request)
    try:
        settings = await store.update_settings(
            thread_id,
            title=payload.title,
            scope=None if payload.clearScope else payload.scope,
            tool_policy=(
                None if payload.clearToolPolicy else payload.toolPolicy
            ),
        )
    except KeyError as exc:
        raise ThreadNotFound("会话不存在。") from exc
    return settings


@router.post("/api/v1/agent/threads/{thread_id}/branch")
async def branch_thread(
    thread_id: str, payload: AgentBranchRequest, request: Request
):
    """F099：从指定消息分支（可见上下文快照；工具不重放、审批不复制）。"""
    from fastapi.responses import JSONResponse

    from lumirss.agent_session import AgentSessionStore, BranchInvalid

    store = AgentSessionStore(request.app.state.db, _get_agent_store(request))
    try:
        result = await store.branch_thread(thread_id, payload.messageIndex)
    except KeyError as exc:
        raise ThreadNotFound("会话不存在。") from exc
    except BranchInvalid as exc:
        return JSONResponse(
            status_code=422,
            content={
                "error": {"type": "invalid_branch_request", "message": str(exc)}
            },
        )
    thread = await _get_agent_store(request).get_thread(result["threadId"])
    return {
        "thread": thread,
        "branchOf": result["branchOf"],
        "copiedMessages": result["copiedMessages"],
        "truncated": result["truncated"],
    }


@router.get("/api/v1/agent/threads/{thread_id}/export")
async def export_thread(
    thread_id: str, request: Request, rounds: int = 5, format: str = "md"
):
    """F096：会话导出（角色轮次 + 工具/审批标注 + 机密剥离）。"""
    from urllib.parse import quote

    from fastapi.responses import JSONResponse, Response

    from lumirss.agent_export import ExportInvalid
    from lumirss.agent_export import export_thread as build_export

    store = _get_agent_store(request)
    try:
        thread, markdown = await build_export(store, thread_id, rounds=rounds)
    except KeyError as exc:
        raise ThreadNotFound("会话不存在。") from exc
    except ExportInvalid as exc:
        return JSONResponse(
            status_code=422,
            content={
                "error": {"type": "invalid_export_request", "message": str(exc)}
            },
        )
    if format != "md":
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "type": "invalid_export_request",
                    "message": "format 仅支持 md。",
                }
            },
        )
    filename = f"agent-thread-{thread_id[:8]}.md"
    quoted = quote(filename)
    return Response(
        content=markdown,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{filename}"; filename*=UTF-8\'\'{quoted}'
            )
        },
    )


@router.post(
    "/api/v1/agent/threads/{thread_id}/approvals/{approval_id}/preview"
)
async def preview_approval(
    thread_id: str, approval_id: str, request: Request
):
    """F097：写操作预演（零业务写入；预演不改变审批流）。"""
    from datetime import datetime, timedelta

    from fastapi.responses import JSONResponse

    from lumirss.agent_export import _redact
    from lumirss.agent_store import APPROVAL_TTL_MINUTES
    from lumirss.agent_tools import DryRunUnsupported

    from ..deps import _get_agent_dry_run

    row = await _session_store(request).get_approval_row(thread_id, approval_id)
    if row is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": {"type": "approval_invalid", "message": "批准记录不存在。"}
            },
        )
    if not row["hashOk"]:
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "type": "args_mismatch",
                    "message": "审批参数已被篡改，预演拒绝。",
                }
            },
        )
    # F097：过期审批预演 → 410（诚实；批准同样会失败）。
    created = datetime.fromisoformat(row["createdAt"])
    expired = (
        row["status"] == "expired"
        or (
            row["status"] == "pending"
            and datetime.fromisoformat(
                __import__("lumirss.util", fromlist=["utc_now"]).utc_now()
            )
            - created
            > timedelta(minutes=APPROVAL_TTL_MINUTES)
        )
    )
    if expired:
        return JSONResponse(
            status_code=410,
            content={
                "error": {"type": "approval_expired", "message": "批准已超时。"}
            },
        )
    if row["status"] != "pending":
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "type": "approval_invalid",
                    "message": "批准记录已被处理。",
                }
            },
        )
    dry_run = _get_agent_dry_run(request)
    try:
        preview = await dry_run(row["tool"], row["args"])
    except DryRunUnsupported:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "type": "dry_run_unsupported",
                    "message": "只读工具没有预演。",
                }
            },
        )
    return {
        "approvalId": row["approvalId"],
        "tool": row["tool"],
        "target": preview.get("target"),
        "changes": _redact(preview.get("changes") or []),
        "uncertain": preview.get("uncertain") or [],
        "note": "预演不执行；批准后按审批行参数执行。",
    }
