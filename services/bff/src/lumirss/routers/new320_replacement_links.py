"""NEW-320 书签失效替代关联路由 — 指定新来源 / 变更史（引用者可见）。

- POST /api/v1/library/bookmarks/{item_uuid}/replacement {newUrl, reason} → 201
- GET  /api/v1/library/bookmarks/{item_uuid}/replacement → 变更史（旧链接 + current）
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.new320_replacement_links import (
    BookmarkReplacementStore,
    ReplacementBookmarkNotFound,
    ReplacementInvalid,
    ReplacementLinkNotFound,
)

router = APIRouter()


class ReplacementBody(BaseModel):
    model_config = {"extra": "forbid"}

    newUrl: str = Field(min_length=1, max_length=2048)
    reason: str = Field(min_length=1, max_length=1000)


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


def _store(request: Request) -> BookmarkReplacementStore:
    return BookmarkReplacementStore(request.app.state.db)


@router.post(
    "/api/v1/library/bookmarks/{item_uuid}/replacement", status_code=201
)
async def add_replacement(
    item_uuid: str, payload: ReplacementBody, request: Request
) -> Response:
    try:
        return JSONResponse(
            await _store(request).add_replacement(
                item_uuid, payload.newUrl, payload.reason
            ),
            status_code=201,
        )
    except ReplacementBookmarkNotFound:
        return _error(404, "bookmark_not_found", "书签不存在。")
    except ReplacementInvalid as exc:
        return _error(422, "invalid_replacement", str(exc))


@router.get("/api/v1/library/bookmarks/{item_uuid}/replacement")
async def get_replacements(item_uuid: str, request: Request) -> Response:
    try:
        return JSONResponse(await _store(request).list_replacements(item_uuid))
    except ReplacementBookmarkNotFound:
        return _error(404, "bookmark_not_found", "书签不存在。")
    except ReplacementLinkNotFound:
        return _error(404, "replacement_not_found", "该书签还没有替代关联。")
