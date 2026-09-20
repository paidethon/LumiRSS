"""F063 AI 任务中心路由 — 最近任务列表 + 失败任务重试。

- GET /api/v1/ai/tasks?limit=50：最近任务（默认/上限 50）。
- POST /api/v1/ai/tasks/{id}/retry：按 kind 重新调用对应生成端点。
  诚实边界：仅 summary 可服务端重建输入（正文在 FreshRSS/提取缓存）；
  其余 kind 的输入由客户端会话持有（译文分段块、对话问题、多选范围）
  → 422 retry_not_supported，绝不假装重试。原记录不变（审计），
  重试产生新任务记录并返回。
"""

from typing import Any

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import JSONResponse

from lumirss.ai_task_log import AiTaskLogStore

router = APIRouter()

_RETRYABLE_KINDS = ("summary",)


@router.get("/api/v1/ai/tasks")
async def list_ai_tasks(
    request: Request, limit: int = Query(default=50, ge=1, le=50)
) -> dict[str, Any]:
    store = AiTaskLogStore(request.app.state.db)
    return {"items": await store.list_tasks(limit)}


@router.post("/api/v1/ai/tasks/{task_id}/retry", response_model=None)
async def retry_ai_task(task_id: str, request: Request) -> Response | dict[str, Any]:
    from lumirss.routers.entry_ai import generate_summary_tracked

    store = AiTaskLogStore(request.app.state.db)
    task = await store.get(task_id)
    if task is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "ai_task_not_found", "message": "任务不存在。"}},
        )
    if task["kind"] not in _RETRYABLE_KINDS or not task["entryRef"]:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "type": "retry_not_supported",
                    "message": "该类任务的输入由页面会话持有，无法从任务中心直接重试。",
                }
            },
        )
    entry_ref = str(task["entryRef"])
    from lumirss.entryref import decode_entry_ref

    decode_entry_ref(entry_ref)  # 非法 ref → 400（与生成端点同一契约）
    # 埋点在 generate_summary_tracked 内完成：成功/失败都产生新任务记录。
    await generate_summary_tracked(request, entry_ref)
    items = await store.list_tasks(10)
    new_task = next(
        (
            item
            for item in items
            if item["kind"] == "summary" and item["entryRef"] == entry_ref
        ),
        None,
    )
    return {"task": new_task, "originalId": task["id"], "originalUnchanged": True}
