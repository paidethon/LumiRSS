"""NEW-266 分段翻译优先队列路由 — 章节先行/选段先行与显式补翻。

- GET    /api/v1/entries/{ref}/translation/priority-queue
- PUT    /api/v1/entries/{ref}/translation/priority-queue   body {indexes}
- DELETE /api/v1/entries/{ref}/translation/priority-queue            清空
- DELETE /api/v1/entries/{ref}/translation/priority-queue/{index}     移出一块
- POST   /api/v1/entries/{ref}/translation/priority-queue/run  body {blocks}
      按队列顺序只发「队列 ∩ 提交块集合」；缓存规则沿用生成路径 ——
      已有结果/不翻译标记/修订段零 provider 调用（不重复收费）。

索引越界/队列超上限 → 422；移出未知块 → 404。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.ai_translation_segments import SegmentInput
from lumirss.deps import _get_segment_service
from lumirss.entryref import decode_entry_ref
from lumirss.new266_priority_queue import (
    QueueCapExceeded,
    QueueIndexInvalid,
    clear_queue,
    enqueue,
    list_queue,
    remove,
    run_queue,
)

router = APIRouter()


class QueuePutBody(BaseModel):
    model_config = {"extra": "forbid"}

    indexes: list[int] = Field(min_length=1, max_length=64)


class QueueRunBlockIn(BaseModel):
    index: int = Field(ge=0, le=63)
    text: str = Field(min_length=1, max_length=20000)


class QueueRunBody(BaseModel):
    model_config = {"extra": "forbid"}

    blocks: list[QueueRunBlockIn] = Field(min_length=1, max_length=64)


def _invalid(exc: Exception, type_name: str) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": {"type": type_name, "message": str(exc)}},
    )


def _queue_view(entries) -> list[dict[str, object]]:
    return [{"index": e.index, "addedAt": e.added_at} for e in entries]


@router.get("/api/v1/entries/{entry_ref}/translation/priority-queue")
async def get_priority_queue(entry_ref: str, request: Request) -> dict[str, object]:
    """当前队列（登记顺序）。"""
    decode_entry_ref(entry_ref)
    entries = await list_queue(request.app.state.db, entry_ref)
    return {"queue": _queue_view(entries)}


@router.put(
    "/api/v1/entries/{entry_ref}/translation/priority-queue",
    response_model=None,
)
async def put_priority_queue(
    entry_ref: str, payload: QueuePutBody, request: Request
) -> dict[str, object] | JSONResponse:
    """按序追加（重复索引 no-op 保位）；超每篇上限 → 422。"""
    decode_entry_ref(entry_ref)
    try:
        entries = await enqueue(request.app.state.db, entry_ref, payload.indexes)
    except QueueIndexInvalid as exc:
        return _invalid(exc, "queue_index_invalid")
    except QueueCapExceeded as exc:
        return _invalid(exc, "queue_cap_exceeded")
    return {"queue": _queue_view(entries)}


@router.delete(
    "/api/v1/entries/{entry_ref}/translation/priority-queue",
    response_model=None,
)
async def delete_priority_queue(entry_ref: str, request: Request) -> dict[str, object]:
    """清空某篇队列。"""
    decode_entry_ref(entry_ref)
    removed = await clear_queue(request.app.state.db, entry_ref)
    return {"removed": removed}


@router.delete(
    "/api/v1/entries/{entry_ref}/translation/priority-queue/{block_index}",
    response_model=None,
)
async def delete_priority_queue_item(
    entry_ref: str, block_index: int, request: Request
) -> dict[str, object] | JSONResponse:
    """移出一块；未知 → 404。"""
    decode_entry_ref(entry_ref)
    try:
        removed = await remove(request.app.state.db, entry_ref, block_index)
    except QueueIndexInvalid as exc:
        return _invalid(exc, "queue_index_invalid")
    if not removed:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "type": "queue_item_not_found",
                    "message": "队列中没有这一块。",
                }
            },
        )
    return {"removed": True}


@router.post(
    "/api/v1/entries/{entry_ref}/translation/priority-queue/run",
    response_model=None,
)
async def post_priority_queue_run(
    entry_ref: str, payload: QueueRunBody, request: Request
) -> dict[str, object] | JSONResponse:
    """显式执行队列：按登记顺序翻「队列 ∩ 提交块集合」。

    缓存语义由生成路径保证：已有成功缓存行 / 不翻译标记 / 人工修订
    段零 provider 调用 —— 已有结果不重复收费。"""
    decode_entry_ref(entry_ref)
    service = _get_segment_service(request)
    blocks = [
        SegmentInput(index=b.index, text=b.text) for b in payload.blocks
    ]
    result = await run_queue(request.app.state.db, service, entry_ref, blocks)
    return {
        "queuedCount": result["queuedCount"],
        "skippedMissingText": result["skippedMissingText"],
        "queuedStates": [
            {
                "index": s.index,
                "status": s.status,
                "translatedText": s.translated_text,
                "failureType": s.failure_type,
                "cached": s.cached,
            }
            for s in result["queuedStates"]
        ],
    }
