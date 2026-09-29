"""NEW-214 标签同义词字典路由 —— 登记/列表/删除/解析提示。

422 invalid_tag_synonym / 409 tag_synonym_conflict / 404 tag_synonym_not_found。
resolve 是录入与搜索框的规范标签提示源：精确命中给 canonical，前缀给
候选集。文章原文永远不被改写——本路由没有任何内容写路径。
"""

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.new214_tag_synonyms import (
    TagSynonymConflict,
    TagSynonymInvalid,
    TagSynonymNotFound,
    TagSynonymStore,
)

router = APIRouter()


class TagSynonymCreate(BaseModel):
    model_config = {"extra": "forbid"}

    alias: str = Field(min_length=1, max_length=50)
    canonical: str = Field(min_length=1, max_length=50)


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


def _store(request: Request) -> TagSynonymStore:
    return TagSynonymStore(request.app.state.db)


@router.post("/api/v1/tag-synonyms", status_code=201)
async def create_tag_synonym(payload: TagSynonymCreate, request: Request) -> Response:
    try:
        result = await _store(request).create(payload.alias, payload.canonical)
    except TagSynonymInvalid as exc:
        return _error(422, "invalid_tag_synonym", str(exc))
    except TagSynonymConflict as exc:
        return _error(409, "tag_synonym_conflict", f"别名「{exc}」已被登记。")
    return JSONResponse(status_code=201, content=result)


@router.get("/api/v1/tag-synonyms")
async def list_tag_synonyms(request: Request, q: str | None = None) -> JSONResponse:
    return JSONResponse({"items": await _store(request).list_entries(q=q)})


@router.delete("/api/v1/tag-synonyms/{entry_id}", status_code=204)
async def delete_tag_synonym(entry_id: int, request: Request) -> Response:
    deleted = await _store(request).delete(entry_id)
    if not deleted:
        return _error(404, "tag_synonym_not_found", "别名不存在。")
    return Response(status_code=204)


@router.get("/api/v1/tag-synonyms/resolve")
async def resolve_tag_synonym(request: Request, q: str = "") -> Response:
    try:
        result = await _store(request).resolve_input(q)
    except TagSynonymInvalid as exc:
        return _error(422, "invalid_tag_synonym", str(exc))
    except TagSynonymNotFound as exc:
        return _error(404, "tag_synonym_not_found", str(exc))
    return JSONResponse(result)
