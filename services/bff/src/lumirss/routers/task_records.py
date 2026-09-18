"""F35 用户任务记录路由（只读聚合）。"""

from fastapi import APIRouter, Request

from lumirss.models import TaskRecord, TaskRecordList
from lumirss.task_records import TaskRecordStore

router = APIRouter()


@router.get("/api/v1/tasks/recent", response_model=TaskRecordList)
async def recent_tasks(request: Request, limit: int = 20) -> TaskRecordList:
    """最近的本应用后台任务结果（备份/日报/邮件摘要；新→旧，有界）。"""
    items = await TaskRecordStore(request.app.state.db).recent_tasks(limit)
    return TaskRecordList(items=[TaskRecord(**item) for item in items])
