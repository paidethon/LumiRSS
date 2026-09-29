"""NEW-276 AI 失败重放诊断路由 — 诊断 / 重放 / 血缘。

- GET  /api/v1/ai/tasks/{task_id}/replay-diagnostic → 脱敏结构诊断
- POST /api/v1/ai/tasks/{task_id}/replay {mode, maxChars?, question?}
- GET  /api/v1/ai/tasks/{task_id}/replays → 重放血缘
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.new276_task_replays import (
    ReplayNotAvailable,
    ReplayNotFound,
    ReplayStore,
)

router = APIRouter()


class ReplayBody(BaseModel):
    model_config = {"extra": "forbid"}

    mode: str
    maxChars: int | None = Field(default=None, ge=512, le=50000)
    question: str | None = Field(default=None, min_length=1, max_length=4000)


def _store(request: Request) -> ReplayStore:
    return ReplayStore(request.app.state.db)


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


def _guard(exc: Exception) -> JSONResponse | None:
    if isinstance(exc, ReplayNotFound):
        return _error(404, "task_not_found", "任务不存在。")
    if isinstance(exc, ReplayNotAvailable):
        return JSONResponse(
            status_code=422,
            content={"error": {"type": exc.reason, "message": str(exc)}},
        )
    return None


@router.get("/api/v1/ai/tasks/{task_id}/replay-diagnostic")
async def get_replay_diagnostic(task_id: str, request: Request) -> Response:
    try:
        diagnostic = await _store(request).diagnostic(task_id)
    except Exception as exc:  # noqa: BLE001
        denial = _guard(exc)
        if denial is not None:
            return denial
        raise
    return JSONResponse(diagnostic)


@router.post("/api/v1/ai/tasks/{task_id}/replay")
async def replay_task(task_id: str, payload: ReplayBody, request: Request) -> Response:
    """按 mode 重放：same = 相同配置重试；modified = 修改后新建。

    run 回调复用既有生成端点的服务与埋点；conversation 的 same 在
    服务层被诚实拒绝（问题正文不入库，无法原样重建）。"""
    from lumirss.ai_quota import quota_denial

    try:
        store = _store(request)
        await store.diagnostic(task_id)  # 提前验证（404/422 → 稳定错误）
    except Exception as exc:  # noqa: BLE001
        denial = _guard(exc)
        if denial is not None:
            return denial
        raise

    async def run(diag: dict) -> str:
        from lumirss.ai_task_log import record_best_effort
        from lumirss.deps import _get_conversation_service, _get_summary_service

        kind = diag["kind"]
        denial = await quota_denial(
            request, purpose="summary" if kind == "summary" else "chat"
        )
        if denial is not None:
            raise ReplayNotAvailable("quota_exceeded", "配额不足，重放未执行。")
        if kind == "summary":
            state = await _get_summary_service(request).generate_summary(
                diag["entryRef"], max_chars=payload.maxChars
            )
            if state.status != "success":
                raise ReplayNotAvailable(
                    "replay_failed", f"重放未成功：{state.failure_type or state.status}。"
                )
            new_id = await record_best_effort(
                request.app.state.db, kind="summary", status="done",
                entry_ref=diag["entryRef"], input_chars=state.input_chars,
            )
            return new_id or diag["id"]
        if kind == "conversation":
            if not payload.question or not payload.question.strip():
                raise ReplayNotAvailable(
                    "question_required",
                    "conversation 重放必须提供新问题（mode=modified）。",
                )
            state = await _get_conversation_service(request).send_message(
                diag["entryRef"], payload.question
            )
            new_id = await record_best_effort(
                request.app.state.db, kind="conversation", status="done",
                entry_ref=diag["entryRef"], input_chars=state.input_chars,
            )
            return new_id or diag["id"]
        raise ReplayNotAvailable(
            "kind_not_replayable", f"{kind} 没有通用重放路径。"
        )

    try:
        result = await store.replay(task_id, mode=payload.mode, run=run)
    except Exception as exc:  # noqa: BLE001
        denial = _guard(exc)
        if denial is not None:
            return denial
        raise
    return JSONResponse(result, status_code=201)


@router.get("/api/v1/ai/tasks/{task_id}/replays")
async def list_task_replays(task_id: str, request: Request) -> Response:
    replays = await _store(request).list_replays(task_id)
    return JSONResponse({"items": replays, "total": len(replays)})
