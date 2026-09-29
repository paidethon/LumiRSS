"""NEW-241 文章更新差异阅读路由 — 版本保存 / 列表 / 阅读 / 段落差异。

- POST /api/v1/entries/{entry_ref}/article-versions           显式保存当前正文为版本；
- GET  /api/v1/entries/{entry_ref}/article-versions           版本列表（元数据）；
- GET  /api/v1/entries/{entry_ref}/article-versions/{id}      阅读所选版本全文；
- GET  /api/v1/entries/{entry_ref}/article-versions/diff      两版段落级差异
      （from/to 均为已保存版本 id）。

负载非法 → 422 article_version_invalid；版本不存在 → 404
article_version_not_found；per-user 库天然隔离。
"""

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.new241_article_versions import (
    ArticleVersionInvalid,
    ArticleVersionNotFound,
    ArticleVersionStore,
)

router = APIRouter()


class VersionSave(BaseModel):
    model_config = {"extra": "forbid"}

    label: str = Field(min_length=1, max_length=200)
    contentText: str = Field(min_length=1, max_length=200_000)


def _store(request: Request) -> ArticleVersionStore:
    return ArticleVersionStore(request.app.state.db)


def _invalid(message: str) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": {"type": "article_version_invalid", "message": message}},
    )


def _not_found() -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"error": {"type": "article_version_not_found", "message": "版本不存在。"}},
    )


@router.post("/api/v1/entries/{entry_ref}/article-versions", status_code=201)
async def save_article_version(entry_ref: str, payload: VersionSave, request: Request) -> Response:
    """把当前正文显式保存为一个版本。"""
    try:
        item = await _store(request).save_version(entry_ref, payload.label, payload.contentText)
    except ArticleVersionInvalid as exc:
        return _invalid(str(exc))
    return JSONResponse(status_code=201, content=item)


@router.get("/api/v1/entries/{entry_ref}/article-versions")
async def list_article_versions(entry_ref: str, request: Request) -> Response:
    """版本列表（新→旧；不含正文）。"""
    return JSONResponse(await _store(request).list_versions(entry_ref))


@router.get("/api/v1/entries/{entry_ref}/article-versions/diff")
async def diff_article_versions(
    entry_ref: str,
    request: Request,
    fromVersion: str = Query(...),
    toVersion: str = Query(...),
) -> Response:
    """两个已保存版本之间的段落级差异（added/removed/modified 计数）。"""
    try:
        result = await _store(request).diff(entry_ref, fromVersion, toVersion)
    except ArticleVersionNotFound:
        return _not_found()
    return JSONResponse(result)


@router.get("/api/v1/entries/{entry_ref}/article-versions/{version_id}")
async def read_article_version(entry_ref: str, version_id: str, request: Request) -> Response:
    """阅读所选版本的全文。"""
    try:
        item = await _store(request).get_version(entry_ref, version_id)
    except ArticleVersionNotFound:
        return _not_found()
    return JSONResponse(item)
