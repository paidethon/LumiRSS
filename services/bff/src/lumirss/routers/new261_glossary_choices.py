"""NEW-261 术语表冲突处理路由 — 冲突清单 / 生效译法选择 / 清除。

- GET  /api/v1/glossary/conflicts            同词多义冲突清单（变体含
    来源与适用范围；chosen = 用户已登记的生效选择）。
- POST /api/v1/glossary/conflicts/choice     为当前来源或项目登记生效译法
    （写入推进 glossary_version：已产生译文缓存原样，其后新生成按生效译法）。
- DELETE /api/v1/glossary/conflicts/choice   清除一条选择（回到默认解析）。

非法负载 → 422 glossary_choice_invalid；清除不存在的选择 → 404。
"""

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.new261_glossary_conflicts import (
    GlossaryChoiceInvalid,
    clear_choice,
    list_conflicts,
    set_choice,
)

router = APIRouter()


class GlossaryChoiceBody(BaseModel):
    model_config = {"extra": "forbid"}

    term: str = Field(min_length=1, max_length=100)
    chosenTermId: str = Field(min_length=1, max_length=64)
    scope: str = Field(pattern="^(project|source)$")
    sourceUrl: str = Field(default="", max_length=2048)


def _invalid(exc: GlossaryChoiceInvalid) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": {"type": "glossary_choice_invalid", "message": str(exc)}
        },
    )


@router.get("/api/v1/glossary/conflicts")
async def get_glossary_conflicts(request: Request) -> dict[str, object]:
    """同名多义冲突清单（每组的变体来源/适用范围可见 + 现有选择）。"""
    conflicts = await list_conflicts(request.app.state.db)
    return {"conflicts": conflicts}


@router.post("/api/v1/glossary/conflicts/choice", response_model=None)
async def post_glossary_choice(
    payload: GlossaryChoiceBody, request: Request
) -> dict[str, object] | JSONResponse:
    """登记生效译法（scope=project 忽略 sourceUrl；scope=source 必填）。"""
    try:
        choice = await set_choice(
            request.app.state.db,
            payload.term,
            payload.chosenTermId,
            payload.scope,
            payload.sourceUrl,
        )
    except GlossaryChoiceInvalid as exc:
        return _invalid(exc)
    return choice


@router.delete("/api/v1/glossary/conflicts/choice", response_model=None)
async def delete_glossary_choice(
    request: Request,
    term: str = Query(min_length=1, max_length=100),
    scope: str = Query(pattern="^(project|source)$"),
    sourceUrl: str = "",
) -> JSONResponse:
    """清除一条生效选择（回默认解析）。不存在 → 404。"""
    try:
        removed = await clear_choice(request.app.state.db, term, scope, sourceUrl)
    except GlossaryChoiceInvalid as exc:
        return _invalid(exc)
    if not removed:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "type": "glossary_choice_not_found",
                    "message": "该术语没有这条生效选择。",
                }
            },
        )
    return JSONResponse(status_code=200, content={"removed": True})
