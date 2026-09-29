"""NEW-267 专有名词保护例外路由 — 当前任务级的不翻译豁免。

- GET    /api/v1/entries/{ref}/translation/protect-exceptions
        {exceptions:[{term, createdAt}], hits:[{term, hitSegments}]}
- POST   /api/v1/entries/{ref}/translation/protect-exceptions  body {term}
        幂等登记；空/超长 → 422；超每篇上限 → 422
- DELETE /api/v1/entries/{ref}/translation/protect-exceptions/{term}
        撤销例外（术语恢复全局默认保护）；未知 → 404

例外只影响该篇其后的新生成；既有缓存译文原样展示（不悄悄改变）。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.entryref import decode_entry_ref
from lumirss.new267_protect_exceptions import (
    ProtectCapExceeded,
    ProtectTermInvalid,
    exception_hits,
    list_exceptions,
    register,
    remove,
)

router = APIRouter()


class ExceptionBody(BaseModel):
    model_config = {"extra": "forbid"}

    term: str = Field(min_length=1, max_length=200)


def _invalid(exc: Exception, type_name: str) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": {"type": type_name, "message": str(exc)}},
    )


@router.get("/api/v1/entries/{entry_ref}/translation/protect-exceptions")
async def get_protect_exceptions(
    entry_ref: str, request: Request
) -> dict[str, object]:
    """该篇例外清单 + 只读命中视图（多少个不同源段命中）。"""
    decode_entry_ref(entry_ref)
    db = request.app.state.db
    items = await list_exceptions(db, entry_ref)
    return {
        "exceptions": [
            {"term": item.term, "createdAt": item.created_at} for item in items
        ],
        "hits": await exception_hits(db, entry_ref),
    }


@router.post(
    "/api/v1/entries/{entry_ref}/translation/protect-exceptions",
    response_model=None,
)
async def post_protect_exception(
    entry_ref: str, payload: ExceptionBody, request: Request
) -> dict[str, object] | JSONResponse:
    """登记「这篇不保护该术语」的例外（幂等）。"""
    decode_entry_ref(entry_ref)
    try:
        item = await register(request.app.state.db, entry_ref, payload.term)
    except ProtectTermInvalid as exc:
        return _invalid(exc, "protect_term_invalid")
    except ProtectCapExceeded as exc:
        return _invalid(exc, "protect_cap_exceeded")
    return {"term": item.term, "createdAt": item.created_at}


@router.delete(
    "/api/v1/entries/{entry_ref}/translation/protect-exceptions/{term}",
    response_model=None,
)
async def delete_protect_exception(
    entry_ref: str, term: str, request: Request
) -> dict[str, object] | JSONResponse:
    """撤销例外；未知 → 404。"""
    decode_entry_ref(entry_ref)
    try:
        removed = await remove(request.app.state.db, entry_ref, term)
    except ProtectTermInvalid as exc:
        return _invalid(exc, "protect_term_invalid")
    if not removed:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "type": "protect_exception_not_found",
                    "message": "该篇没有这个术语例外。",
                }
            },
        )
    return {"removed": True}
