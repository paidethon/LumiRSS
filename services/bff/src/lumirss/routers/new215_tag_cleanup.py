"""NEW-215 标签使用清理台路由 —— 三桶报告 + 受保护删除。

409 tag_cleanup_blocked：带引用未确认的删除被整批拦截，响应里如实
列出被拦的标签与引用数——「禁止一键误删被规则依赖的标签」的服务端
执行点。422 invalid_tag_cleanup。
"""

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.new215_tag_cleanup import (
    TagCleanupBlocked,
    TagCleanupInvalid,
    TagCleanupStore,
)

router = APIRouter()


class TagCleanupDeleteRequest(BaseModel):
    model_config = {"extra": "forbid"}

    tagIds: list[int] = Field(min_length=1, max_length=50)
    acknowledgeReferences: bool = False


def _error(status: int, error_type: str, message: str, extra: dict | None = None) -> JSONResponse:
    content: dict = {"error": {"type": error_type, "message": message}}
    if extra:
        content["error"].update(extra)
    return JSONResponse(status_code=status, content=content)


def _store(request: Request) -> TagCleanupStore:
    return TagCleanupStore(request.app.state.db)


@router.get("/api/v1/tags/cleanup/report")
async def tag_cleanup_report(request: Request) -> JSONResponse:
    return JSONResponse(await _store(request).report())


@router.post("/api/v1/tags/cleanup/delete")
async def tag_cleanup_delete(payload: TagCleanupDeleteRequest, request: Request) -> Response:
    try:
        result = await _store(request).delete_tags(
            payload.tagIds, acknowledge_references=payload.acknowledgeReferences
        )
    except TagCleanupInvalid as exc:
        return _error(422, "invalid_tag_cleanup", str(exc))
    except TagCleanupBlocked as exc:
        return _error(
            409,
            "tag_cleanup_blocked",
            f"标签「{exc.name}」仍被 {exc.references} 处引用（同义词/互斥组），"
            "确认同步清理这些引用后才能删除。",
            extra={"tagId": exc.tag_id, "name": exc.name, "references": exc.references},
        )
    return JSONResponse(result)
