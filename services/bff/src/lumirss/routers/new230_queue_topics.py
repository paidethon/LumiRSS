"""NEW-230 队列重复主题提醒路由（自选主题标注 + 集中度报告）。

主题由用户手动标注；报告纯建议，绝无自动重排路径。稳定错误信封：
invalid_queue_topic。
"""

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from lumirss.new230_queue_topics import QueueTopicStore, TopicInvalid

router = APIRouter()


def _store(request: Request) -> QueueTopicStore:
    return QueueTopicStore(request.app.state.db)


class TopicSetRequest(BaseModel):
    model_config = {"extra": "forbid"}

    itemRef: str
    topics: list[str] = Field(max_length=5)
    """自选主题（整体替换；空表 = 清除）。"""


class TopicViewResponse(BaseModel):
    itemRef: str
    topics: list[str]


class TopicMemberView(BaseModel):
    itemRef: str
    position: int
    segment: str | None = None
    status: str


class TopicReportEntry(BaseModel):
    topic: str
    itemCount: int
    positions: list[int]
    minGap: int | None = None
    segments: list[str]
    members: list[TopicMemberView]


class TopicReportResponse(BaseModel):
    queueDate: str
    topics: list[TopicReportEntry]
    duplicatedTopics: list[TopicReportEntry]
    advisory: bool
    note: str


@router.put("/api/v1/queue/topics", response_model=TopicViewResponse)
async def set_queue_topics(payload: TopicSetRequest, request: Request) -> TopicViewResponse:
    """标注/替换某队列成员的自选主题（set 语义；空表清除）。"""
    return TopicViewResponse(**await _store(request).set_topics(payload.itemRef, payload.topics))


@router.get("/api/v1/queue/topics", response_model=TopicViewResponse)
async def get_queue_topics(request: Request, itemRef: str) -> TopicViewResponse:
    """某队列成员今日的自选主题。"""
    return TopicViewResponse(**await _store(request).get_topics(itemRef))


@router.get("/api/v1/queue/topics/report", response_model=TopicReportResponse)
async def queue_topics_report(request: Request) -> TopicReportResponse:
    """今日队列主题集中度（用户主动整理时看；advisory only）。"""
    return TopicReportResponse(**await _store(request).report())


__all__ = ["router", "TopicInvalid"]
