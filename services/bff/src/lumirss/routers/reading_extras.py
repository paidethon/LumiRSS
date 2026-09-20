"""F056 跨设备继续阅读 + F058 批注复习队列 路由。

- reading-progress：PUT upsert（updated_at 用服务器时间——同条目冲突
  latest-wins 的唯一仲裁）；GET 最近 ≤5 条。
- review-queue：到期列表（JOIN annotations 取摘录/批注）、完成、延期、
  重复添加 409（对 done 的可重新排期）；批注删除的级联在 annotation
  store 的 delete 中执行。
"""

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.annotation_store import AnnotationStore
from lumirss.util import utc_now

router = APIRouter()

_MAX_DEVICE_LABEL = 32
_MAX_PCT = 100.0
_MAX_DUE_DAYS = 365


class ReadingProgressPut(BaseModel):
    """PUT /api/v1/reading-progress body。"""

    model_config = {"extra": "forbid"}

    entryRef: str
    paraId: str = Field(min_length=1, max_length=200)
    pct: float = Field(ge=0.0, le=100.0)
    deviceLabel: str = Field(default="", max_length=_MAX_DEVICE_LABEL)


class ReviewQueueAdd(BaseModel):
    """POST /api/v1/review-queue body。"""

    model_config = {"extra": "forbid"}

    annotationId: str
    dueAt: str = Field(min_length=1)


class ReviewQueuePostpone(BaseModel):
    """POST /api/v1/review-queue/{id}/postpone body。"""

    model_config = {"extra": "forbid"}

    dueAt: str


@router.put("/api/v1/reading-progress", status_code=204)
async def put_reading_progress(payload: ReadingProgressPut, request: Request) -> Response:
    await request.app.state.db.migrate()
    await request.app.state.db.execute(
        "INSERT INTO reading_progress (entry_ref, para_id, pct, device_label, updated_at) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(entry_ref) DO UPDATE SET para_id = excluded.para_id, pct = excluded.pct, device_label = excluded.device_label, updated_at = excluded.updated_at",
        (payload.entryRef, payload.paraId, payload.pct, payload.deviceLabel, utc_now()),
    )
    return Response(status_code=204)


@router.get("/api/v1/reading-progress")
async def list_reading_progress(request: Request, limit: int = 5) -> Response:
    await request.app.state.db.migrate()
    limit = max(1, min(limit, 5))
    rows = await request.app.state.db.fetch_all(
        "SELECT entry_ref, para_id, pct, device_label, updated_at FROM reading_progress ORDER BY updated_at DESC LIMIT ?",
        (limit,),
    )
    items = [
        {
            "entryRef": row["entry_ref"],
            "paraId": row["para_id"],
            "pct": row["pct"],
            "deviceLabel": row["device_label"],
            "updatedAt": row["updated_at"],
        }
        for row in rows
    ]
    return JSONResponse({"items": items})


@router.post("/api/v1/review-queue")
async def add_review_queue_item(payload: ReviewQueueAdd, request: Request) -> Response:
    from datetime import UTC, datetime, timedelta

    await request.app.state.db.migrate()

    annotation = await AnnotationStore(request.app.state.db).get(payload.annotationId)
    if annotation is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "annotation_not_found", "message": "批注不存在。"}},
        )
    due_text = payload.dueAt.strip()
    if due_text.endswith(("Z", "z")):
        due_text = due_text[:-1] + "+00:00"
    try:
        due = datetime.fromisoformat(due_text)
    except ValueError:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "invalid_review_schedule", "message": "dueAt 不是有效时间。"}},
        )
    if due.tzinfo is None:
        due = due.replace(tzinfo=UTC)
    if due - datetime.now(UTC) > timedelta(days=_MAX_DUE_DAYS):
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "type": "invalid_review_schedule",
                    "message": f"dueAt 最多提前 {_MAX_DUE_DAYS} 天。",
                }
            },
        )
    existing = await request.app.state.db.fetch_one(
        "SELECT id, status FROM review_queue WHERE annotation_id = ?",
        (payload.annotationId,),
    )
    due_iso = due.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    import uuid as _uuid

    if existing is not None:
        if existing["status"] == "due":
            return JSONResponse(
                status_code=409,
                content={
                    "error": {
                        "type": "review_already_scheduled",
                        "message": "该批注已在复习队列中。",
                    }
                },
            )
        # done 的可重新排期
        await request.app.state.db.execute(
            "UPDATE review_queue SET status = 'due', due_at = ?, completed_at = NULL WHERE id = ?",
            (due_iso, existing["id"]),
        )
        return JSONResponse(status_code=200, content={"id": existing["id"], "rescheduled": True})
    queue_id = str(_uuid.uuid4())
    await request.app.state.db.execute(
        "INSERT INTO review_queue (id, annotation_id, due_at, status) VALUES (?, ?, ?, 'due')",
        (queue_id, payload.annotationId, due_iso),
    )
    return JSONResponse(status_code=201, content={"id": queue_id, "rescheduled": False})


@router.get("/api/v1/review-queue")
async def list_review_queue(request: Request, status: str = "due") -> Response:
    await request.app.state.db.migrate()
    if status not in ("due", "done"):
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "invalid_request", "message": "status 必须是 due 或 done。"}},
        )
    rows = await request.app.state.db.fetch_all(
        "SELECT q.id, q.annotation_id, q.due_at, q.status, q.completed_at, a.excerpt, a.note, a.entry_ref FROM review_queue q JOIN annotations a ON a.id = q.annotation_id WHERE q.status = ? ORDER BY q.due_at ASC",
        (status,),
    )
    from lumirss.util import utc_now as _now

    now = _now()
    items = [
        {
            "id": row["id"],
            "annotationId": row["annotation_id"],
            "entryRef": row["entry_ref"],
            "dueAt": row["due_at"],
            "completedAt": row["completed_at"],
            "due": row["due_at"] <= now if status == "due" else None,
            "excerpt": row["excerpt"],
            "note": row["note"],
        }
        for row in rows
    ]
    return JSONResponse({"items": items})


@router.post("/api/v1/review-queue/{queue_id}/complete")
async def complete_review_queue_item(queue_id: str, request: Request) -> Response:
    await request.app.state.db.migrate()
    row = await request.app.state.db.fetch_one(
        "SELECT id FROM review_queue WHERE id = ?", (queue_id,)
    )
    if row is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "review_item_not_found", "message": "队列项不存在。"}},
        )
    await request.app.state.db.execute(
        "UPDATE review_queue SET status = 'done', completed_at = ? WHERE id = ?",
        (utc_now(), queue_id),
    )
    return JSONResponse({"id": queue_id, "status": "done"})


@router.post("/api/v1/review-queue/{queue_id}/postpone")
async def postpone_review_queue_item(
    queue_id: str, payload: ReviewQueuePostpone, request: Request
) -> Response:
    await request.app.state.db.migrate()
    row = await request.app.state.db.fetch_one(
        "SELECT id, status FROM review_queue WHERE id = ?", (queue_id,)
    )
    if row is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "review_item_not_found", "message": "队列项不存在。"}},
        )
    due_text = payload.dueAt.strip()
    if due_text.endswith(("Z", "z")):
        due_text = due_text[:-1] + "+00:00"
    try:
        from datetime import UTC, datetime

        due = datetime.fromisoformat(due_text)
        due_iso = due.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "invalid_review_schedule", "message": "dueAt 不是有效时间。"}},
        )
    await request.app.state.db.execute(
        "UPDATE review_queue SET due_at = ?, status = 'due' WHERE id = ?",
        (due_iso, queue_id),
    )
    return JSONResponse({"id": queue_id, "dueAt": due_iso})
