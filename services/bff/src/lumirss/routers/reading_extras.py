"""F056 跨设备继续阅读 + F058 批注复习队列 + N076/N077 复习项泛化 路由。

- reading-progress：PUT upsert（updated_at 用服务器时间——同条目冲突
  latest-wins 的唯一仲裁）；GET 最近 ≤5 条。
- review-queue：到期列表（批注 JOIN annotations、卡片 JOIN
  knowledge_cards）、完成、延期、重复添加 409（done 可重新排期）；批注
  删除的级联在 annotation store 的 delete 中执行，卡片删除的级联在
  knowledge_cards.delete_card 中执行。
- N076：item_kind 泛化（annotation | knowledge_card）——知识卡片走同一
  到期/揭示流程（揭示 = concept 提问、explanation 揭示）。
- N077：来源追踪 —— 列表项带 sourceAvailable（search_entries 投影存在
  性，绝不缓存原文）与 paraId（批注锚点段落，供 deep link）；揭示时
  POST /{id}/view 记录 last_viewed_at（只记时间，不缓存内容）。
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
_ITEM_KINDS = ("annotation", "knowledge_card")


class ReadingProgressPut(BaseModel):
    """PUT /api/v1/reading-progress body。"""

    model_config = {"extra": "forbid"}

    entryRef: str
    paraId: str = Field(min_length=1, max_length=200)
    pct: float = Field(ge=0.0, le=100.0)
    deviceLabel: str = Field(default="", max_length=_MAX_DEVICE_LABEL)


class ReviewQueueAdd(BaseModel):
    """POST /api/v1/review-queue body（N076 泛化：批注或知识卡片）。

    向后兼容：缺省 kind='annotation' 且仍以 annotationId 排期。"""

    model_config = {"extra": "forbid"}

    kind: str = "annotation"
    annotationId: str | None = None
    knowledgeCardId: str | None = None
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


def _parse_due_at(raw: str) -> str | None:
    """宽松 ISO → 统一 UTC「YYYY-MM-DDTHH:MM:SSZ」；非法 → None。"""
    from datetime import UTC, datetime

    due_text = raw.strip()
    if due_text.endswith(("Z", "z")):
        due_text = due_text[:-1] + "+00:00"
    try:
        due = datetime.fromisoformat(due_text)
    except ValueError:
        return None
    if due.tzinfo is None:
        due = due.replace(tzinfo=UTC)
    return due.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@router.post("/api/v1/review-queue")
async def add_review_queue_item(payload: ReviewQueueAdd, request: Request) -> Response:
    import uuid as _uuid
    from datetime import UTC, datetime, timedelta

    await request.app.state.db.migrate()
    if payload.kind not in _ITEM_KINDS:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "invalid_request", "message": "kind 必须是 annotation 或 knowledge_card。"}},
        )
    due_iso = _parse_due_at(payload.dueAt)
    if due_iso is None:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "invalid_review_schedule", "message": "dueAt 不是有效时间。"}},
        )
    due = datetime.strptime(due_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
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

    item_id: str
    kind_column: str
    if payload.kind == "knowledge_card":
        card_id = (payload.knowledgeCardId or "").strip()
        row = await request.app.state.db.fetch_one(
            "SELECT id FROM knowledge_cards WHERE id = ?", (card_id,)
        )
        if row is None:
            return JSONResponse(
                status_code=404,
                content={
                    "error": {
                        "type": "knowledge_card_not_found",
                        "message": "知识卡片不存在。",
                    }
                },
            )
        item_id = card_id
        kind_column = "knowledge_card_id"
    else:
        annotation_id = (payload.annotationId or "").strip()
        annotation = await AnnotationStore(request.app.state.db).get(annotation_id)
        if annotation is None:
            return JSONResponse(
                status_code=404,
                content={"error": {"type": "annotation_not_found", "message": "批注不存在。"}},
            )
        item_id = annotation_id
        kind_column = "annotation_id"

    existing = await request.app.state.db.fetch_one(
        f"SELECT id, status FROM review_queue WHERE {kind_column} = ?", (item_id,)
    )
    if existing is not None:
        if existing["status"] == "due":
            return JSONResponse(
                status_code=409,
                content={
                    "error": {
                        "type": "review_already_scheduled",
                        "message": "该内容已在复习队列中。",
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
        "INSERT INTO review_queue (id, annotation_id, knowledge_card_id, item_kind, due_at, status) VALUES (?, ?, ?, ?, ?, 'due')",
        (
            queue_id,
            item_id if kind_column == "annotation_id" else None,
            item_id if kind_column == "knowledge_card_id" else None,
            payload.kind,
            due_iso,
        ),
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
        """SELECT q.id, q.item_kind, q.annotation_id, q.knowledge_card_id, q.due_at,
        q.status, q.completed_at, q.last_viewed_at,
        a.excerpt AS a_excerpt, a.note AS a_note, a.entry_ref AS a_entry_ref,
        a.anchor_json AS a_anchor,
        kc.concept AS kc_concept, kc.explanation AS kc_explanation,
        kc.entry_ref AS kc_entry_ref
        FROM review_queue q
        LEFT JOIN annotations a ON a.id = q.annotation_id
        LEFT JOIN knowledge_cards kc ON kc.id = q.knowledge_card_id
        WHERE q.status = ? ORDER BY q.due_at ASC""",
        (status,),
    )
    # N077 来源可用性：search_entries 投影存在性（无缓存内容，绝不伪造）。
    entry_refs = sorted(
        {
            str(row["a_entry_ref"] if row["item_kind"] == "annotation" else row["kc_entry_ref"])
            for row in rows
            if (row["a_entry_ref"] if row["item_kind"] == "annotation" else row["kc_entry_ref"])
        }
    )
    available: set[str] = set()
    if entry_refs:
        placeholders = ",".join("?" for _ in entry_refs)
        rows_avail = await request.app.state.db.fetch_all(
            f"SELECT entry_ref FROM search_entries WHERE entry_ref IN ({placeholders})",
            tuple(entry_refs),
        )
        available = {str(r["entry_ref"]) for r in rows_avail}

    import json as _json

    from lumirss.util import utc_now as _now

    now = _now()
    items = []
    for row in rows:
        is_annotation = row["item_kind"] == "annotation"
        entry_ref = row["a_entry_ref"] if is_annotation else row["kc_entry_ref"]
        para_id: str | None = None
        if is_annotation and entry_ref is not None:
            try:
                anchor = _json.loads(str(row["a_anchor"] or "{}"))
                para_id = str(anchor.get("paraId") or "") or None
            except (ValueError, TypeError):
                para_id = None
        source_available = None if entry_ref is None else str(entry_ref) in available
        items.append(
            {
                "id": row["id"],
                "itemKind": row["item_kind"],
                "annotationId": row["annotation_id"],
                "knowledgeCardId": row["knowledge_card_id"],
                "entryRef": entry_ref,
                "paraId": para_id,
                "dueAt": row["due_at"],
                "completedAt": row["completed_at"],
                "due": row["due_at"] <= now if status == "due" else None,
                "lastViewedAt": row["last_viewed_at"],
                "sourceAvailable": source_available,
                # 批注项：摘录 + 揭示批注
                "excerpt": row["a_excerpt"] if is_annotation else None,
                "note": row["a_note"] if is_annotation else None,
                # 卡片项：concept 提问 + explanation 揭示
                "concept": None if is_annotation else row["kc_concept"],
                "explanation": None if is_annotation else row["kc_explanation"],
            }
        )
    return JSONResponse({"items": items})


@router.post("/api/v1/review-queue/{queue_id}/view")
async def view_review_queue_item(queue_id: str, request: Request) -> Response:
    """N077：揭示答案时刻 → last_viewed_at（来源追踪；只记时间，
    不缓存任何原文内容）。"""
    await request.app.state.db.migrate()
    row = await request.app.state.db.fetch_one(
        "SELECT id FROM review_queue WHERE id = ?", (queue_id,)
    )
    if row is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "review_item_not_found", "message": "队列项不存在。"}},
        )
    viewed_at = utc_now()
    await request.app.state.db.execute(
        "UPDATE review_queue SET last_viewed_at = ? WHERE id = ?", (viewed_at, queue_id)
    )
    return JSONResponse({"id": queue_id, "lastViewedAt": viewed_at})


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
