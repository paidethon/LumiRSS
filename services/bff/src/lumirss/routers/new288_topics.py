"""NEW-288 跨期主题追踪路由 — 主题 CRUD + 跨期链。

- POST /api/v1/briefings/topics                 → 同建同取（名字幂等）
- GET  /api/v1/briefings/topics                 → 列表（含条目计数）
- GET  /api/v1/briefings/topics/{topic_id}      → 跨期链（期次位置 +
          后续更新链；静态路由先于 new281 的 /{issue_id} 注册）
- POST /api/v1/briefings/topics/{topic_id}/entries {briefingId,itemId}
          → 把某期条目挂到主题（条目必须真实属于该期）。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from lumirss.new281_briefings import BriefingNotFound
from lumirss.new288_topics import TopicInvalid, TopicStore

router = APIRouter()


class TopicCreateBody(BaseModel):
    model_config = {"extra": "forbid"}

    name: str


class TopicAttachBody(BaseModel):
    model_config = {"extra": "forbid"}

    briefingId: str
    itemId: str


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


def _store(request: Request) -> TopicStore:
    return TopicStore(request.app.state.db)


@router.post("/api/v1/briefings/topics")
async def create_topic(payload: TopicCreateBody, request: Request) -> Response:
    try:
        topic = await _store(request).get_or_create(payload.name)
    except TopicInvalid as exc:
        return _error(422, "invalid_topic_payload", str(exc))
    return JSONResponse(topic, status_code=201 if topic["created"] else 200)


@router.get("/api/v1/briefings/topics")
async def list_topics(request: Request) -> Response:
    topics = await _store(request).list_topics()
    return JSONResponse({"topics": topics, "count": len(topics)})


@router.get("/api/v1/briefings/topics/{topic_id}")
async def get_topic(topic_id: str, request: Request) -> Response:
    try:
        return JSONResponse(await _store(request).chain(topic_id))
    except BriefingNotFound as exc:
        return _error(404, "topic_not_found", str(exc))


@router.post("/api/v1/briefings/topics/{topic_id}/entries")
async def attach_entry(
    topic_id: str, payload: TopicAttachBody, request: Request
) -> Response:
    try:
        result = await _store(request).attach(
            topic_id,
            briefing_id=payload.briefingId,
            item_id=payload.itemId,
        )
    except TopicInvalid as exc:
        return _error(422, "invalid_topic_payload", str(exc))
    except BriefingNotFound as exc:
        return _error(404, "briefing_not_found", str(exc))
    return JSONResponse(result, status_code=201 if result["attached"] else 200)
