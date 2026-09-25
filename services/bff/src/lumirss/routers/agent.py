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
from fastapi.responses import StreamingResponse

from lumirss.agent_store import (
    CANCELLED_TEXT,
    AgentStore,
    NoActiveRun,
    PendingApprovalBlocked,
    ThreadNotFound,
)
from lumirss.models import (
    AgentApprovalDecision,
    AgentApprovalPreview,
    AgentApprovalResult,
    AgentApprovalReviseRequest,
    AgentApprovalReviseResult,
    AgentBranchRequest,
    AgentBranchResult,
    AgentCancelResult,
    AgentCitationDetail,
    AgentMessage,
    AgentMessageCreate,
    AgentMessageListResponse,
    AgentPauseResult,
    AgentRecipe,
    AgentRecipeCreate,
    AgentRecipeListResponse,
    AgentRecipePreview,
    AgentRecipeRunResult,
    AgentResumeResult,
    AgentRetryResult,
    AgentScopePreviewRequest,
    AgentScopeSummary,
    AgentThread,
    AgentThreadListResponse,
    AgentThreadSearchHit,
    AgentThreadSearchResponse,
    AgentThreadSettings,
    AgentThreadUpdate,
    AgentToolPolicy,
    AgentTurnAccepted,
    AgentUndoRequest,
    AgentUndoResult,
)
from lumirss.sources import resolve_item

from ..deps import (
    _get_agent_loop,
    _get_agent_store,
    _get_agent_undo,
    _get_source_registry,
)

router = APIRouter()


class MarkdownResponse(Response):
    """Response class so OpenAPI documents the export payload as a
    markdown string (E04 contract repair); the route still builds its
    own Response with the attachment headers."""

    media_type = "text/markdown; charset=utf-8"


# Citation resolution hits real resolvers (FreshRSS for rss refs); one
# page resolves at most this many distinct refs.
_MAX_CITATION_RESOLVES = 24
_SSE_IDLE_TIMEOUT_SECONDS = 120.0


def _thread_model(thread: dict) -> AgentThread:
    return AgentThread(
        id=thread["id"], title=thread["title"], createdAt=thread["createdAt"]
    )


def _message_model(message: dict):
    """Storage row → wire model (content dict validates against the
    per-role union; a mismatch fails loudly instead of drifting)."""
    return AgentMessage(
        id=message["id"],
        threadId=message["threadId"],
        seq=message["seq"],
        role=message["role"],
        content=message["content"],
        citations=message["citations"],
        createdAt=message["createdAt"],
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


@router.get(
    "/api/v1/agent/threads/{thread_id}/messages",
    response_model=AgentMessageListResponse,
)
async def get_messages(thread_id: str, request: Request, after: int = 0):
    """REST read path (polling fallback) + resolved citation details."""
    store: AgentStore = _get_agent_store(request)
    messages = await store.messages_after(thread_id, after)
    details = await _citation_details(request, messages)
    return AgentMessageListResponse(
        items=[_message_model(message) for message in messages],
        citationDetails=[AgentCitationDetail(**detail) for detail in details],
    )


@router.post(
    "/api/v1/agent/threads/{thread_id}/messages",
    status_code=202,
    response_model=AgentTurnAccepted,
)
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
    return AgentTurnAccepted(status="processing")


@router.post(
    "/api/v1/agent/threads/{thread_id}/approvals",
    status_code=200,
    response_model=AgentApprovalResult,
)
async def decide_approval(
    thread_id: str, payload: AgentApprovalDecision, request: Request
):
    loop = _get_agent_loop(request)
    result = await loop.apply_approval(
        thread_id, payload.approvalId, payload.decision
    )
    return AgentApprovalResult(
        status=result["status"],
        message=result.get("message"),
        reason=result.get("reason"),
    )


@router.post(
    "/api/v1/agent/threads/{thread_id}/cancel",
    response_model=AgentCancelResult,
)
async def cancel_turn(thread_id: str, request: Request):
    """Server-side cancel: the loop finalizes a partial ``cancelled``
    state in storage (never stuck ``processing``)."""
    store: AgentStore = _get_agent_store(request)
    loop = _get_agent_loop(request)
    thread = await store.get_thread(thread_id)
    if thread is None:
        raise ThreadNotFound("会话不存在。")
    if loop.cancel_turn(thread_id):
        return AgentCancelResult(cancelled=True, status="cancelling")
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
        return AgentCancelResult(cancelled=True, status="cancelled")
    raise NoActiveRun("当前没有正在运行的回合。")


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get(
    "/api/v1/agent/threads/{thread_id}/events",
    response_class=StreamingResponse,
    responses={
        200: {
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
            "description": (
                "SSE stream: message/delta/done events; keep-alive comments"
            ),
        }
    },
)
async def stream_events(thread_id: str, request: Request, after: int = 0):
    """Real-time SSE: storage replay after `after`, then live deltas from
    the running turn until it reaches a terminal state. Disconnects never
    abort the server-side run — clients reconnect with `after` and get the
    persisted rows. (``response_class``/``responses`` are for OpenAPI
    documentation only; the hand-rolled generator below owns
    replay/keep-alive.)"""
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
                elif kind == "budget_exhausted":
                    yield _sse(
                        "budget_exhausted",
                        {"summary": event.get("summary") or {}},
                    )
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


@router.get(
    "/api/v1/agent/threads/search",
    response_model=AgentThreadSearchResponse,
)
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
    return AgentThreadSearchResponse(
        items=[AgentThreadSearchHit(**item) for item in items],
        truncated=len(items) >= 50,
    )


@router.patch(
    "/api/v1/agent/threads/{thread_id}",
    response_model=AgentThreadSettings,
)
async def update_thread_settings(
    thread_id: str, payload: AgentThreadUpdate, request: Request
):
    """F094/F098/N165：会话设置（scope / toolPolicy / budget / 标题）。下轮生效。"""
    store = _session_store(request)
    try:
        settings = await store.update_settings(
            thread_id,
            title=payload.title,
            scope=None if payload.clearScope else payload.scope,
            tool_policy=(
                None if payload.clearToolPolicy else payload.toolPolicy
            ),
            budget=None if payload.clearBudget else payload.budget,
        )
    except KeyError as exc:
        raise ThreadNotFound("会话不存在。") from exc
    return AgentThreadSettings(**settings)


@router.post(
    "/api/v1/agent/scope-preview",
    response_model=AgentScopeSummary,
)
async def preview_scope(payload: AgentScopePreviewRequest, request: Request):
    """N151：授权范围摘要（kind × refCount × toolCount）——工作台范围
    选择器保存前的服务端预览；refCount 查询时解析（有界），toolCount
    与回合执行前的权限评估同口径（白名单 ∩ policy，readonly 剔除写）。"""
    from lumirss.agent_scope import effective_scope

    from ..deps import _get_agent_loop, _get_workspace_store

    tool_policy = (
        {
            "mode": payload.toolPolicy.mode,
            "allowedTools": payload.toolPolicy.allowedTools,
            "maxOpsPerTurn": payload.toolPolicy.maxOpsPerTurn,
        }
        if payload.toolPolicy is not None
        else None
    )
    scope: dict | None = None
    if payload.scope is not None:
        scope = (
            payload.scope.model_dump()
            if hasattr(payload.scope, "model_dump")
            else dict(payload.scope)
        )
    effective = await effective_scope(
        request.app.state.db,
        _get_workspace_store(request),
        scope,
    )
    loop = _get_agent_loop(request)
    return AgentScopeSummary(
        kind=effective["kind"],
        refCount=effective["refCount"],
        toolCount=len(loop.effective_tool_names(tool_policy)),
    )


@router.post(
    "/api/v1/agent/threads/{thread_id}/branch",
    response_model=AgentBranchResult,
)
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
    return AgentBranchResult(
        thread=_thread_model(thread),
        branchOf=result["branchOf"],
        copiedMessages=result["copiedMessages"],
        truncated=result["truncated"],
    )


@router.get(
    "/api/v1/agent/threads/{thread_id}/export",
    response_class=MarkdownResponse,
)
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
    "/api/v1/agent/threads/{thread_id}/approvals/{approval_id}/preview",
    response_model=AgentApprovalPreview,
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
    return AgentApprovalPreview(
        approvalId=row["approvalId"],
        tool=row["tool"],
        target=preview.get("target"),
        changes=_redact(preview.get("changes") or []),
        uncertain=preview.get("uncertain") or [],
        note="预演不执行；批准后按审批行参数执行。",
    )


# ---------------------------------------------------------------------------
# N164–N170 agent ops: pause/resume / revise / retry / undo / recipes
# ---------------------------------------------------------------------------


def _approval_content_model(content: dict, thread_id: str | None = None):
    """Approval store/get dict → wire model (normalizes shapes from
    different producers: create_approval rows vs get_approval rows)."""
    from lumirss.models import AgentApprovalContent

    return AgentApprovalContent(
        approvalId=str(content.get("approvalId") or ""),
        threadId=str(content.get("threadId") or thread_id or ""),
        callId=str(content.get("callId") or ""),
        tool=str(content.get("tool") or ""),
        args=dict(content.get("args") or {}),
        status=str(content.get("status") or "pending"),
        expiresInMinutes=content.get("expiresInMinutes"),
        reconfirmOf=content.get("reconfirmOf"),
    )


@router.post(
    "/api/v1/agent/threads/{thread_id}/pause",
    response_model=AgentPauseResult,
)
async def pause_turn(thread_id: str, request: Request):
    """N164：任务暂停。运行中的回合在下一个工具间检查点冻结为快照
    （{completedSteps, pendingPlan}）；仅停留在批准上的回合同样可暂停
    （批准 id 进入快照）。二者皆无 → 409 no_active_run。"""
    store: AgentStore = _get_agent_store(request)
    loop = _get_agent_loop(request)
    thread = await store.get_thread(thread_id)
    if thread is None:
        raise ThreadNotFound("会话不存在。")
    if loop.pause_turn(thread_id):
        return AgentPauseResult(paused=True, status="pausing")
    await loop.pause_suspended_on_approval(thread_id)
    return AgentPauseResult(paused=True, status="paused")


@router.post(
    "/api/v1/agent/threads/{thread_id}/resume",
    response_model=AgentResumeResult,
)
async def resume_turn(thread_id: str, request: Request):
    """N164：任务续接。已执行的步骤绝不重复执行（transcript 结果复用）；
    暂停期间过期的批准 → 重新确认（铸造新批准行，旧批准作废）。"""
    store: AgentStore = _get_agent_store(request)
    loop = _get_agent_loop(request)
    thread = await store.get_thread(thread_id)
    if thread is None:
        raise ThreadNotFound("会话不存在。")
    prepare = await loop.resume_prepare(thread_id)
    if prepare["action"] == "awaiting_approval":
        approval = prepare.get("approval") or {}
        return AgentResumeResult(
            status="awaiting_approval",
            approval=_approval_content_model(approval, thread_id),
            reconfirmRequired=bool(prepare.get("reconfirm")),
        )
    task = loop.start_resume(thread_id)
    request.app.state.agent_tasks.add(task)
    task.add_done_callback(request.app.state.agent_tasks.discard)
    return AgentResumeResult(status="processing")


@router.post(
    "/api/v1/agent/threads/{thread_id}/approvals/{approval_id}/revise",
    response_model=AgentApprovalReviseResult,
)
async def revise_approval(
    thread_id: str, approval_id: str, payload: AgentApprovalReviseRequest, request: Request
):
    """N167：批准内容修改——修订产生 NEW 审批行（绑定新 args_hash），
    旧行标记 superseded（take → 410）。"""
    store: AgentStore = _get_agent_store(request)
    fresh = await store.revise_approval(thread_id, approval_id, dict(payload.newArgs))
    await store.append_message(thread_id, role="approval", content=fresh)
    return AgentApprovalReviseResult(
        approval=_approval_content_model(fresh, thread_id),
        supersededApprovalId=approval_id,
    )


@router.post(
    "/api/v1/agent/threads/{thread_id}/retry",
    response_model=AgentRetryResult,
)
async def retry_failed_steps(thread_id: str, request: Request):
    """N168：失败步骤单独重试——只重跑失败/未完成的步骤；已完成步骤
    的结果从 transcript 复用；写工具经幂等台账（args_hash+turn）防止
    重复副作用（需重新批准）。"""
    store: AgentStore = _get_agent_store(request)
    loop = _get_agent_loop(request)
    thread = await store.get_thread(thread_id)
    if thread is None:
        raise ThreadNotFound("会话不存在。")
    await store.expire_stale(thread_id)
    if await store.has_pending_approval(thread_id):
        raise PendingApprovalBlocked("有等待处理的写入批准，请先批准或拒绝。")
    if loop.is_turn_active(thread_id) or await store.is_running(thread_id):
        raise NoActiveRun("回合正在运行，无法重试。")
    result = await loop.retry_failed_steps(thread_id)
    approval = result.get("approval")
    return AgentRetryResult(
        status=result["status"],
        retried=result.get("retried") or [],
        skipped=result.get("skipped") or [],
        approval=_approval_content_model(approval, thread_id) if approval else None,
    )


@router.post(
    "/api/v1/agent/threads/{thread_id}/undo",
    response_model=AgentUndoResult,
)
async def undo_step(thread_id: str, payload: AgentUndoRequest, request: Request):
    """N169：任务结果差异撤销——按写台账前后快照回滚；对象在写入后
    又被修改过 → 冲突报告并跳过；不支持撤销的工具 → 422。"""
    from fastapi.responses import JSONResponse

    from lumirss.agent_store import StepNotFound, UndoConflict, UndoUnsupported

    store: AgentStore = _get_agent_store(request)
    loop = _get_agent_loop(request)
    thread = await store.get_thread(thread_id)
    if thread is None:
        raise ThreadNotFound("会话不存在。")
    row = await store.get_tool_write(thread_id, payload.stepId)
    if row is None:
        raise StepNotFound("没有找到该写入步骤的台账记录。")
    if not row["undoable"]:
        raise UndoUnsupported(f"工具 {row['tool']} 不支持差异撤销。")
    if row["undoneAt"]:
        return AgentUndoResult(
            undone=False,
            stepId=payload.stepId,
            tool=row["tool"],
            conflictReason="该步骤已被撤销过。",
        )
    undo_service = _get_agent_undo(request)
    try:
        result = await undo_service["undo"](row["tool"], row["args"], row["before"], row["after"])
    except UndoConflict as exc:
        # N169: objects modified since the write — conflict report, skip.
        return AgentUndoResult(
            undone=False,
            stepId=payload.stepId,
            tool=row["tool"],
            conflictReason=exc.reason,
        )
    except UndoUnsupported as exc:
        return JSONResponse(
            status_code=422,
            content={
                "error": {"type": "undo_unsupported", "message": str(exc)}
            },
        )
    await store.mark_tool_write_undone(payload.stepId)
    undo_row = await store.append_message(
        thread_id,
        role="tool",
        content={
            "name": row["tool"],
            "undoOf": payload.stepId,
            "result": _untrusted_envelope(result),
            "resultType": "result",
        },
    )
    loop.publish(thread_id, {"type": "message", "message": undo_row})
    return AgentUndoResult(
        undone=True,
        stepId=payload.stepId,
        tool=row["tool"],
        result=result,
    )


def _untrusted_envelope(result: dict) -> dict:
    return {"untrusted": True, "payload": result}


# -- N170 任务配方 --------------------------------------------------------------


def _recipe_store(request: Request):
    from lumirss.agent_recipes import AgentRecipeStore

    return AgentRecipeStore(request.app.state.db)


def _recipe_model(recipe: dict) -> AgentRecipe:
    return AgentRecipe(
        id=recipe["id"],
        name=recipe["name"],
        input=recipe["input"],
        toolWhitelist=recipe["toolWhitelist"],
        scope=recipe["scope"],
        createdAt=recipe["createdAt"],
        updatedAt=recipe["updatedAt"],
    )


@router.post("/api/v1/agent/recipes", response_model=AgentRecipe, status_code=201)
async def create_recipe(payload: AgentRecipeCreate, request: Request):
    """N170：保存配方（白名单校验：unknown → 422，绝不支持越权）。"""
    from lumirss.agent_recipes import validate_recipe

    clean = validate_recipe(
        name=payload.name,
        input_text=payload.input,
        tool_whitelist=payload.toolWhitelist,
        scope=payload.scope,
    )
    loop = _get_agent_loop(request)
    unknown = [t for t in clean["toolWhitelist"] if t not in set(loop.tool_names())]
    if unknown:
        from lumirss.agent_recipes import RecipeInvalid

        raise RecipeInvalid(f"未知工具：{', '.join(sorted(unknown))}")
    recipe = await _recipe_store(request).create_recipe(
        name=clean["name"],
        input_text=clean["input"],
        tool_whitelist=clean["toolWhitelist"],
        scope=clean["scope"],
    )
    return _recipe_model(recipe)


@router.get("/api/v1/agent/recipes", response_model=AgentRecipeListResponse)
async def list_recipes(request: Request):
    store = _recipe_store(request)
    return AgentRecipeListResponse(
        items=[_recipe_model(r) for r in await store.list_recipes()]
    )


@router.delete("/api/v1/agent/recipes/{recipe_id}", status_code=204)
async def delete_recipe(recipe_id: str, request: Request) -> Response:
    from lumirss.agent_recipes import RecipeNotFound

    deleted = await _recipe_store(request).delete_recipe(recipe_id)
    if not deleted:
        raise RecipeNotFound("配方不存在。")
    return Response(status_code=204)


@router.post(
    "/api/v1/agent/recipes/{recipe_id}/preview",
    response_model=AgentRecipePreview,
)
async def preview_recipe(recipe_id: str, request: Request):
    """N170：运行前预览（零写入）：将创建的会话设置 + 首条消息概要。"""
    from lumirss.agent_recipes import RecipeInvalid

    store = _recipe_store(request)
    recipe = await store.get_recipe(recipe_id)
    loop = _get_agent_loop(request)
    known = set(loop.tool_names())
    unknown = [t for t in recipe["toolWhitelist"] if t not in known]
    if unknown:
        raise RecipeInvalid(f"配方白名单含未知工具：{', '.join(sorted(unknown))}")
    return AgentRecipePreview(
        recipeId=recipe["id"],
        name=recipe["name"],
        input=recipe["input"],
        toolWhitelist=recipe["toolWhitelist"],
        unknownTools=[],
        scope=recipe["scope"],
        toolPolicy=AgentToolPolicy(allowedTools=recipe["toolWhitelist"]),
        threadTitle=recipe["name"],
        note="运行将创建新会话并以配方输入开启第一回合；白名单之外的工具将被服务端拒绝。",
    )


@router.post(
    "/api/v1/agent/recipes/{recipe_id}/run",
    response_model=AgentRecipeRunResult,
    status_code=202,
)
async def run_recipe(recipe_id: str, request: Request):
    """N170：运行配方 = 创建新会话（scope + 白名单 toolPolicy 落库）
    + 首条消息开启回合。白名单在服务端 evaluate_policy 强制执行。"""
    store = _recipe_store(request)
    recipe = await store.get_recipe(recipe_id)
    loop = _get_agent_loop(request)
    known = set(loop.tool_names())
    unknown = [t for t in recipe["toolWhitelist"] if t not in known]
    if unknown:
        from lumirss.agent_recipes import RecipeInvalid

        raise RecipeInvalid(f"配方白名单含未知工具：{', '.join(sorted(unknown))}")
    agent_store: AgentStore = _get_agent_store(request)
    thread = await agent_store.create_thread(recipe["name"])
    session_store = _session_store(request)
    await session_store.update_settings(
        thread["id"],
        scope=recipe["scope"],
        tool_policy={
            "mode": "all",
            "allowedTools": recipe["toolWhitelist"],
        },
    )
    task = loop.start_turn(thread["id"], recipe["input"])
    request.app.state.agent_tasks.add(task)
    task.add_done_callback(request.app.state.agent_tasks.discard)
    return AgentRecipeRunResult(
        recipeId=recipe["id"],
        thread=_thread_model(thread),
        status="processing",
    )
