"""N072 批注精选篮路由 — 篮 CRUD + 成员管理 + 篮内导出。

- POST   /api/v1/annotation-baskets                     创建篮；
- GET    /api/v1/annotation-baskets                     篮列表（含成员计数）；
- PATCH  /api/v1/annotation-baskets/{id}                重命名；
- DELETE /api/v1/annotation-baskets/{id}                删篮（成员关系级联）；
- POST   /api/v1/annotation-baskets/{id}/items          批量加入（幂等）；
- DELETE /api/v1/annotation-baskets/{id}/items/{aid}    移除单项；
- GET    /api/v1/annotation-baskets/{id}/items          成员明细（broken 诚实标注）。

导出走既有 POST /annotations/export（basketId 过滤），见 annotations 路由。
"""

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.annotation_baskets import (
    MAX_NAME,
    AnnotationBasketStore,
    BasketInvalid,
    BasketNotFound,
)

router = APIRouter()


class BasketCreate(BaseModel):
    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1, max_length=MAX_NAME)


class BasketRename(BaseModel):
    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1, max_length=MAX_NAME)


class BasketItemsAdd(BaseModel):
    model_config = {"extra": "forbid"}

    annotationIds: list[str] = Field(min_length=1)


def _invalid(message: str) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": {"type": "invalid_basket", "message": message}},
    )


def _not_found() -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"error": {"type": "basket_not_found", "message": "精选篮不存在。"}},
    )


@router.post("/api/v1/annotation-baskets", status_code=201)
async def create_basket(payload: BasketCreate, request: Request) -> JSONResponse:
    store = AnnotationBasketStore(request.app.state.db)
    try:
        basket = await store.create(name=payload.name)
    except BasketInvalid as exc:
        return _invalid(str(exc))
    return JSONResponse(status_code=201, content=basket)


@router.get("/api/v1/annotation-baskets")
async def list_baskets(request: Request) -> JSONResponse:
    store = AnnotationBasketStore(request.app.state.db)
    return JSONResponse({"items": await store.list_baskets()})


@router.patch("/api/v1/annotation-baskets/{basket_id}")
async def rename_basket(basket_id: str, payload: BasketRename, request: Request) -> JSONResponse:
    store = AnnotationBasketStore(request.app.state.db)
    try:
        basket = await store.rename(basket_id, name=payload.name)
    except BasketInvalid as exc:
        return _invalid(str(exc))
    if basket is None:
        return _not_found()
    return JSONResponse(basket)


@router.delete("/api/v1/annotation-baskets/{basket_id}", status_code=204)
async def delete_basket(basket_id: str, request: Request) -> Response:
    store = AnnotationBasketStore(request.app.state.db)
    deleted = await store.delete(basket_id)
    if not deleted:
        return _not_found()
    return Response(status_code=204)


@router.post("/api/v1/annotation-baskets/{basket_id}/items")
async def add_basket_items(
    basket_id: str, payload: BasketItemsAdd, request: Request
) -> JSONResponse:
    store = AnnotationBasketStore(request.app.state.db)
    try:
        result = await store.add_items(basket_id, payload.annotationIds)
    except BasketInvalid as exc:
        return _invalid(str(exc))
    except BasketNotFound:
        return _not_found()
    return JSONResponse(result)


@router.delete("/api/v1/annotation-baskets/{basket_id}/items/{annotation_id}", status_code=204)
async def remove_basket_item(
    basket_id: str, annotation_id: str, request: Request
) -> Response:
    store = AnnotationBasketStore(request.app.state.db)
    removed = await store.remove_item(basket_id, annotation_id)
    if not removed:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "type": "basket_item_not_found",
                    "message": "该批注不在此精选篮中。",
                }
            },
        )
    return Response(status_code=204)


@router.get("/api/v1/annotation-baskets/{basket_id}/items")
async def list_basket_items(basket_id: str, request: Request) -> JSONResponse:
    store = AnnotationBasketStore(request.app.state.db)
    if not await store.basket_exists(basket_id):
        return _not_found()
    return JSONResponse({"items": await store.list_items(basket_id)})
