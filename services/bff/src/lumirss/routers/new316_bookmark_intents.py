"""NEW-316 书签意图字段路由 — 意图读写 / 按意图筛选。

- PUT    /api/v1/library/bookmarks/{item_uuid}/intent {reason, whenToUse} → 200
- GET    /api/v1/library/bookmarks/{item_uuid}/intent → 200 | 404（无意图）
- DELETE /api/v1/library/bookmarks/{item_uuid}/intent → 204
- GET    /api/v1/library/bookmark-intents?q=&when=    → 按意图筛选列表
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.new316_bookmark_intents import (
    BookmarkIntentStore,
    IntentBookmarkNotFound,
    IntentInvalid,
)

router = APIRouter()


class IntentBody(BaseModel):
    model_config = {"extra": "forbid"}

    reason: str = Field(default="", max_length=500)
    whenToUse: str = Field(default="", max_length=500)


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


def _store(request: Request) -> BookmarkIntentStore:
    return BookmarkIntentStore(request.app.state.db)


@router.put("/api/v1/library/bookmarks/{item_uuid}/intent")
async def put_intent(item_uuid: str, payload: IntentBody, request: Request) -> Response:
    try:
        return JSONResponse(
            await _store(request).set_intent(
                item_uuid, payload.reason, payload.whenToUse
            )
        )
    except IntentBookmarkNotFound:
        return _error(404, "bookmark_not_found", "书签不存在。")
    except IntentInvalid as exc:
        return _error(422, "invalid_intent", str(exc))


@router.get("/api/v1/library/bookmarks/{item_uuid}/intent")
async def get_intent(item_uuid: str, request: Request) -> Response:
    try:
        result = await _store(request).get_intent(item_uuid)
    except IntentBookmarkNotFound:
        return _error(404, "bookmark_not_found", "书签不存在。")
    if result is None:
        return _error(404, "intent_not_found", "该书签还没有意图记录。")
    return JSONResponse(result)


@router.delete("/api/v1/library/bookmarks/{item_uuid}/intent", status_code=204)
async def delete_intent(item_uuid: str, request: Request) -> Response:
    try:
        deleted = await _store(request).delete_intent(item_uuid)
    except IntentBookmarkNotFound:
        return _error(404, "bookmark_not_found", "书签不存在。")
    if not deleted:
        return _error(404, "intent_not_found", "该书签还没有意图记录。")
    return Response(status_code=204)


@router.get("/api/v1/library/bookmark-intents")
async def list_intents(
    request: Request, q: str | None = None, when: str | None = None
) -> Response:
    try:
        return JSONResponse(await _store(request).list_intents(q=q, when=when))
    except IntentInvalid as exc:
        return _error(422, "invalid_intent", str(exc))
