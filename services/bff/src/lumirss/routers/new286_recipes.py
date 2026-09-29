"""NEW-286 简报栏目配方路由 — 配方 CRUD + 应用到草稿。

- POST   /api/v1/briefings/recipes                → 创建
- GET    /api/v1/briefings/recipes                → 列表
- GET    /api/v1/briefings/recipes/{recipe_id}    → 详情
- PUT    /api/v1/briefings/recipes/{recipe_id}    → 更新（名称/栏目）
- DELETE /api/v1/briefings/recipes/{recipe_id}    → 删除
- POST   /api/v1/briefings/{issue_id}/apply-recipe → 草稿套用配方
           （栏目定义替换；被移除栏目里的条目随之移除并如实报数）。

注意：本路由的静态 /recipes 路径必须先于 new281 的 /{issue_id} 注册。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from lumirss.new281_briefings import (
    BriefingInvalid,
    BriefingNotFound,
    BriefingStore,
)
from lumirss.new286_recipes import RecipeNotFound, RecipeStore

router = APIRouter()


class RecipeBody(BaseModel):
    model_config = {"extra": "forbid"}

    name: str | None = None
    sections: list[dict[str, object]] | None = None


class RecipeCreateBody(BaseModel):
    model_config = {"extra": "forbid"}

    name: str
    sections: list[dict[str, object]]


class ApplyRecipeBody(BaseModel):
    model_config = {"extra": "forbid"}

    recipeId: str


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


def _store(request: Request) -> RecipeStore:
    return RecipeStore(request.app.state.db)


@router.post("/api/v1/briefings/recipes")
async def create_recipe(payload: RecipeCreateBody, request: Request) -> Response:
    try:
        recipe = await _store(request).create(
            name=payload.name, sections=payload.sections
        )
    except BriefingInvalid as exc:
        return _error(422, "invalid_recipe_payload", str(exc))
    return JSONResponse(recipe, status_code=201)


@router.get("/api/v1/briefings/recipes")
async def list_recipes(request: Request) -> Response:
    recipes = await _store(request).list_recipes()
    return JSONResponse({"recipes": recipes, "count": len(recipes)})


@router.get("/api/v1/briefings/recipes/{recipe_id}")
async def get_recipe(recipe_id: str, request: Request) -> Response:
    try:
        return JSONResponse(await _store(request).get(recipe_id))
    except RecipeNotFound as exc:
        return _error(404, "recipe_not_found", str(exc))


@router.put("/api/v1/briefings/recipes/{recipe_id}")
async def put_recipe(
    recipe_id: str, payload: RecipeBody, request: Request
) -> Response:
    try:
        recipe = await _store(request).update(
            recipe_id, name=payload.name, sections=payload.sections
        )
    except RecipeNotFound as exc:
        return _error(404, "recipe_not_found", str(exc))
    except BriefingInvalid as exc:
        return _error(422, "invalid_recipe_payload", str(exc))
    return JSONResponse(recipe)


@router.delete("/api/v1/briefings/recipes/{recipe_id}")
async def delete_recipe(recipe_id: str, request: Request) -> Response:
    try:
        await _store(request).delete(recipe_id)
    except RecipeNotFound as exc:
        return _error(404, "recipe_not_found", str(exc))
    return Response(status_code=204)


@router.post("/api/v1/briefings/{issue_id}/apply-recipe")
async def apply_recipe(
    issue_id: str, payload: ApplyRecipeBody, request: Request
) -> Response:
    db = request.app.state.db
    try:
        recipe = await _store(request).get(payload.recipeId)
    except RecipeNotFound as exc:
        return _error(404, "recipe_not_found", str(exc))
    store = BriefingStore(db)
    try:
        issue = await store.get_issue(issue_id)
    except BriefingNotFound as exc:
        return _error(404, "briefing_not_found", str(exc))
    if issue["status"] != "draft":
        return _error(409, "briefing_confirmed", "已确认期次不可套用配方。")
    kept_keys = {s["key"] for s in recipe["sections"]}
    kept_items = [
        item
        for item in issue["items"]
        if item["sectionKey"] in kept_keys
    ]
    dropped = len(issue["items"]) - len(kept_items)
    if not kept_items:
        return _error(
            422,
            "invalid_briefing_payload",
            "套用该配方会清空本期所有条目（条目所在栏目都被移除）；"
            "请先调整配方或改用生成流程。",
        )
    updated = await store.update_draft(
        issue_id, sections=recipe["sections"], items=kept_items
    )
    return JSONResponse({**updated, "droppedItems": dropped})
