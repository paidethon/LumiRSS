"""NEW-234 个人批注层路由 — 层 CRUD / 成员 / 按层列表与导出。

- GET/POST /api/v1/annotation-layers
- PATCH/DELETE /api/v1/annotation-layers/{layer_id}
- POST /api/v1/annotation-layers/{layer_id}/items {annotationIds}
- DELETE /api/v1/annotation-layers/{layer_id}/items/{annotation_id}
- GET  /api/v1/annotation-layers/{layer_id}/annotations   （切换 = 按层读取）
- POST /api/v1/annotation-layers/{layer_id}/export {includeNotes} → Markdown

层是纯个人结构：默认不混入共享面（层操作从不改变批注私有性）。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.new234_annotation_layers import (
    AnnotationLayerInvalid,
    AnnotationLayerNotFound,
    AnnotationLayerStore,
)

router = APIRouter()


class LayerCreate(BaseModel):
    model_config = {"extra": "forbid"}

    name: str


class LayerRename(BaseModel):
    model_config = {"extra": "forbid"}

    name: str


class LayerAssign(BaseModel):
    model_config = {"extra": "forbid"}

    annotationIds: list[str] = Field(min_length=1)


class LayerExportRequest(BaseModel):
    model_config = {"extra": "forbid"}

    includeNotes: bool = True


def _store(request: Request) -> AnnotationLayerStore:
    return AnnotationLayerStore(request.app.state.db)


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


@router.get("/api/v1/annotation-layers")
async def list_layers(request: Request) -> Response:
    return JSONResponse({"items": await _store(request).list_layers()})


@router.post("/api/v1/annotation-layers", status_code=201)
async def create_layer(payload: LayerCreate, request: Request) -> Response:
    try:
        layer = await _store(request).create(payload.name)
    except AnnotationLayerInvalid as exc:
        return _error(422, "invalid_annotation_layer", str(exc))
    return JSONResponse(status_code=201, content=layer)


@router.patch("/api/v1/annotation-layers/{layer_id}")
async def rename_layer(layer_id: str, payload: LayerRename, request: Request) -> Response:
    try:
        result = await _store(request).rename(layer_id, payload.name)
    except AnnotationLayerInvalid as exc:
        return _error(422, "invalid_annotation_layer", str(exc))
    if result is None:
        return _error(404, "annotation_layer_not_found", "批注层不存在。")
    return JSONResponse(result)


@router.delete("/api/v1/annotation-layers/{layer_id}", status_code=204)
async def delete_layer(layer_id: str, request: Request) -> Response:
    deleted = await _store(request).delete(layer_id)
    if not deleted:
        return _error(404, "annotation_layer_not_found", "批注层不存在。")
    return Response(status_code=204)


@router.post("/api/v1/annotation-layers/{layer_id}/items")
async def assign_items(layer_id: str, payload: LayerAssign, request: Request) -> Response:
    try:
        result = await _store(request).assign(layer_id, payload.annotationIds)
    except AnnotationLayerNotFound:
        return _error(404, "annotation_layer_not_found", "批注层不存在。")
    return JSONResponse(result)


@router.delete("/api/v1/annotation-layers/{layer_id}/items/{annotation_id}", status_code=204)
async def unassign_item(layer_id: str, annotation_id: str, request: Request) -> Response:
    try:
        removed = await _store(request).unassign(layer_id, annotation_id)
    except AnnotationLayerNotFound:
        return _error(404, "annotation_layer_not_found", "批注层不存在。")
    if not removed:
        return _error(404, "annotation_not_in_layer", "该批注不在此层（或不存在）。")
    return Response(status_code=204)


@router.get("/api/v1/annotation-layers/{layer_id}/annotations")
async def layer_annotations(layer_id: str, request: Request) -> Response:
    """按层读取批注（「切换批注层」的读取面）。"""
    try:
        items = await _store(request).list_annotations(layer_id)
    except AnnotationLayerNotFound:
        return _error(404, "annotation_layer_not_found", "批注层不存在。")
    return JSONResponse({"items": items, "nextCursor": None})


@router.post("/api/v1/annotation-layers/{layer_id}/export")
async def export_layer(
    layer_id: str, payload: LayerExportRequest, request: Request
) -> Response:
    """按层单独导出（Markdown）。"""
    try:
        body = await _store(request).export_markdown(layer_id, include_notes=payload.includeNotes)
    except AnnotationLayerNotFound:
        return _error(404, "annotation_layer_not_found", "批注层不存在。")
    return Response(
        content=body,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="lumi-annotation-layer.md"'},
    )
