"""NEW-217 集合排序配方路由 —— 配方 CRUD + 预览 + 应用。

全部端点挂在既有集合路径下；apply 只写该集合的成员 position（其他
列表不受影响）。explain 随配方返回，分享时说明排序规则。
422 invalid_sort_recipe / 404 sort_recipe_not_found。
"""

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.new217_sort_recipes import (
    SortRecipeInvalid,
    SortRecipeNotFound,
    SortRecipeStore,
)

router = APIRouter()


class SortRecipeField(BaseModel):
    model_config = {"extra": "forbid"}

    key: str = Field(min_length=1, max_length=20)
    dir: str = Field(min_length=1, max_length=4)


class SortRecipeCreate(BaseModel):
    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1, max_length=100)
    fields: list[SortRecipeField] = Field(min_length=1, max_length=4)
    exceptions: list[str] = Field(default_factory=list, max_length=50)


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


def _store(request: Request) -> SortRecipeStore:
    return SortRecipeStore(request.app.state.db)


@router.post("/api/v1/workspaces/{workspace_id}/sort-recipes", status_code=201)
async def create_sort_recipe(
    workspace_id: str, payload: SortRecipeCreate, request: Request
) -> Response:
    try:
        result = await _store(request).create(
            workspace_id,
            payload.name,
            [field.model_dump() for field in payload.fields],
            payload.exceptions,
        )
    except SortRecipeInvalid as exc:
        return _error(422, "invalid_sort_recipe", str(exc))
    return JSONResponse(status_code=201, content=result)


@router.get("/api/v1/workspaces/{workspace_id}/sort-recipes")
async def list_sort_recipes(workspace_id: str, request: Request) -> JSONResponse:
    return JSONResponse({"items": await _store(request).list_recipes(workspace_id)})


@router.delete("/api/v1/workspaces/{workspace_id}/sort-recipes/{recipe_id}", status_code=204)
async def delete_sort_recipe(
    workspace_id: str, recipe_id: str, request: Request
) -> Response:
    deleted = await _store(request).delete(workspace_id, recipe_id)
    if not deleted:
        return _error(404, "sort_recipe_not_found", "排序配方不存在。")
    return Response(status_code=204)


@router.post("/api/v1/workspaces/{workspace_id}/sort-recipes/{recipe_id}/preview")
async def preview_sort_recipe(
    workspace_id: str, recipe_id: str, request: Request
) -> Response:
    try:
        result = await _store(request).preview(workspace_id, recipe_id)
    except SortRecipeNotFound:
        return _error(404, "sort_recipe_not_found", "排序配方不存在。")
    return JSONResponse(result)


@router.post("/api/v1/workspaces/{workspace_id}/sort-recipes/{recipe_id}/apply")
async def apply_sort_recipe(
    workspace_id: str, recipe_id: str, request: Request
) -> Response:
    try:
        result = await _store(request).apply(workspace_id, recipe_id)
    except SortRecipeNotFound:
        return _error(404, "sort_recipe_not_found", "排序配方不存在。")
    return JSONResponse(result)
