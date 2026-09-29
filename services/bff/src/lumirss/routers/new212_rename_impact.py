"""NEW-212 标签改名影响图路由 —— 预览（POST /rename-impact）与确认应用
（POST /rename-with-sync）。改名不再是「只改标签文字」：同义词字典的
canonical 指向随改名同步改写；id 键引用（互斥组/绑定）自动跟随并在
影响图中如实列出。422 invalid_tag（复用 tags 域稳定错误类型）。"""

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.new212_tag_rename_impact import TagRenameImpactStore
from lumirss.tags import TagInvalid

router = APIRouter()


class TagRenameImpactRequest(BaseModel):
    model_config = {"extra": "forbid"}

    tagId: int
    newName: str = Field(min_length=1, max_length=50)


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


def _store(request: Request) -> TagRenameImpactStore:
    return TagRenameImpactStore(request.app.state.db)


@router.post("/api/v1/tags/rename-impact")
async def tag_rename_impact(payload: TagRenameImpactRequest, request: Request) -> Response:
    """只读影响图：会改写的引用 / 自动跟随的引用 / 受影响绑定数。"""
    try:
        result = await _store(request).impact(payload.tagId, payload.newName)
    except TagInvalid as exc:
        return _error(422, "invalid_tag", str(exc))
    return JSONResponse(result)


@router.post("/api/v1/tags/rename-with-sync")
async def tag_rename_with_sync(payload: TagRenameImpactRequest, request: Request) -> Response:
    """确认应用：单事务改名 + 同步名字键引用。"""
    try:
        result = await _store(request).rename_with_sync(payload.tagId, payload.newName)
    except TagInvalid as exc:
        return _error(422, "invalid_tag", str(exc))
    return JSONResponse(result)
