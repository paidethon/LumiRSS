"""NEW-269 语言识别纠正路由 — 某文/某源识别语言的显式更正。

- GET    /api/v1/translation/language-overrides          本人全部更正
- PUT    /api/v1/translation/language-overrides          登记/更正
        body {scope: 'entry'|'source', refKey, language}（BCP-47 短代码）
- DELETE /api/v1/translation/language-overrides/{scope}/{refKey}  撤销
- GET    /api/v1/entries/{ref}/translation/language-override
        该篇当前生效的更正（entry 优先 → 源 → null）

语义（已产生结果不悄悄改变）：更正只影响其后的新生成；既有缓存
译文原样展示，不失效、不改写。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.entryref import decode_entry_ref
from lumirss.new269_language_overrides import (
    LanguageOverrideInvalid,
    delete_override,
    list_overrides,
    resolve_source_language,
    set_override,
)

router = APIRouter()


class OverrideBody(BaseModel):
    model_config = {"extra": "forbid"}

    scope: str = Field(min_length=1, max_length=10)
    refKey: str = Field(min_length=1, max_length=400)
    language: str = Field(min_length=2, max_length=12)


def _invalid(exc: LanguageOverrideInvalid) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": {"type": "language_override_invalid", "message": str(exc)}},
    )


@router.get("/api/v1/translation/language-overrides")
async def get_language_overrides(request: Request) -> dict[str, object]:
    """本人全部识别更正（新→旧；per-user 库天然隔离）。"""
    items = await list_overrides(request.app.state.db)
    return {"overrides": items}


@router.put("/api/v1/translation/language-overrides", response_model=None)
async def put_language_override(
    payload: OverrideBody, request: Request
) -> dict[str, object] | JSONResponse:
    """登记/更正识别语言（再次更正覆盖旧值；created_at 保留首次）。"""
    if payload.scope == "entry":
        decode_entry_ref(payload.refKey)  # 400 on malformed refs
    try:
        item = await set_override(
            request.app.state.db, payload.scope, payload.refKey, payload.language
        )
    except LanguageOverrideInvalid as exc:
        return _invalid(exc)
    return item


@router.delete(
    "/api/v1/translation/language-overrides",
    response_model=None,
)
async def delete_language_override(
    request: Request, scope: str = "", refKey: str = ""
) -> dict[str, object] | JSONResponse:
    """撤销更正（query 传 scope/refKey —— refKey 常是 URL，免转码歧义）。
    未知 → 404。"""
    try:
        removed = await delete_override(request.app.state.db, scope, refKey)
    except LanguageOverrideInvalid as exc:
        return _invalid(exc)
    if not removed:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "type": "language_override_not_found",
                    "message": "没有这条更正。",
                }
            },
        )
    return {"removed": True}


@router.get("/api/v1/entries/{entry_ref}/translation/language-override")
async def get_entry_language_override(
    entry_ref: str, request: Request
) -> dict[str, object]:
    """该篇当前生效的源语言更正（entry 优先 → 源 → null）。"""
    decode_entry_ref(entry_ref)
    language = await resolve_source_language(request.app.state.db, entry_ref)
    return {"language": language}
