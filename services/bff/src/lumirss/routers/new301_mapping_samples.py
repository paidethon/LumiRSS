"""NEW-301 API 字段映射编辑器路由。

- POST   /api/v1/api-sources/{uuid}/mapping-samples            存样本 → 201
- GET    /api/v1/api-sources/{uuid}/mapping-samples            清单
- DELETE /api/v1/api-sources/{uuid}/mapping-samples/{id}       删样本 → 204
- POST   /api/v1/api-sources/{uuid}/mapping-samples/{id}/preview  试映射预览
- POST   /api/v1/api-sources/{uuid}/mapping-bind               绑定映射到既有来源
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.api_sources import ApiSourceNotFound
from lumirss.new301_mapping_samples import (
    MappingSampleStore,
    SampleInvalid,
    preview_sample_mapping,
)

router = APIRouter()


class MappingSampleCreate(BaseModel):
    model_config = {"extra": "forbid"}

    label: str = Field(min_length=1, max_length=100)
    sampleJson: object


class MappingPreviewBody(BaseModel):
    model_config = {"extra": "forbid"}

    fieldMap: dict[str, str]


class MappingBindBody(MappingPreviewBody):
    pass


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


def _stores(request: Request) -> tuple[MappingSampleStore, object]:
    from lumirss.api_source_store import ApiSourceStore

    return MappingSampleStore(request.app.state.db), ApiSourceStore(request.app.state.db)


@router.post("/api/v1/api-sources/{source_uuid}/mapping-samples", status_code=201)
async def create_mapping_sample(source_uuid: str, payload: MappingSampleCreate, request: Request) -> Response:
    sample_store, source_store = _stores(request)
    if await source_store.get(source_uuid) is None:
        raise ApiSourceNotFound(source_uuid)
    try:
        created = await sample_store.save_sample(source_uuid, payload.label, payload.sampleJson)
    except SampleInvalid as exc:
        return _error(422, "invalid_mapping_sample", str(exc))
    return JSONResponse(created, status_code=201)


@router.get("/api/v1/api-sources/{source_uuid}/mapping-samples")
async def list_mapping_samples(source_uuid: str, request: Request) -> Response:
    sample_store, source_store = _stores(request)
    if await source_store.get(source_uuid) is None:
        raise ApiSourceNotFound(source_uuid)
    return JSONResponse({"items": await sample_store.list_samples(source_uuid)})


@router.delete("/api/v1/api-sources/{source_uuid}/mapping-samples/{sample_id}", status_code=204)
async def delete_mapping_sample(source_uuid: str, sample_id: int, request: Request) -> Response:
    sample_store, _ = _stores(request)
    if not await sample_store.delete_sample(source_uuid, sample_id):
        return _error(404, "mapping_sample_not_found", "样本不存在。")
    return Response(status_code=204)


@router.post("/api/v1/api-sources/{source_uuid}/mapping-samples/{sample_id}/preview")
async def preview_mapping(
    source_uuid: str, sample_id: int, payload: MappingPreviewBody, request: Request
) -> Response:
    sample_store, source_store = _stores(request)
    record = await source_store.get(source_uuid)
    if record is None:
        raise ApiSourceNotFound(source_uuid)
    sample = await sample_store.get_sample(source_uuid, sample_id)
    if sample is None:
        return _error(404, "mapping_sample_not_found", "样本不存在。")
    try:
        result = preview_sample_mapping(
            sample["sampleJson"], payload.fieldMap, record.items_expr
        )
    except SampleInvalid as exc:
        return _error(422, "invalid_mapping_expression", str(exc))
    return JSONResponse(result)


@router.post("/api/v1/api-sources/{source_uuid}/mapping-bind")
async def bind_mapping(source_uuid: str, payload: MappingBindBody, request: Request) -> Response:
    """绑定 = 复用既有 update（缓存失效语义完整保留）。"""
    source_store: object
    sample_store, source_store = _stores(request)
    record = await source_store.get(source_uuid)
    if record is None:
        raise ApiSourceNotFound(source_uuid)
    from lumirss.api_sources import ApiSourceExpressionError, ApiSourceInvalid

    try:
        updated = await source_store.update(source_uuid, field_map=payload.fieldMap)
    except ApiSourceExpressionError as exc:
        return _error(422, "invalid_mapping_expression", str(exc))
    except ApiSourceInvalid as exc:
        return _error(422, "invalid_field_map", str(exc))
    return JSONResponse(
        {
            "uuid": updated.uuid,
            "fieldMap": payload.fieldMap,
            "note": "映射已绑定；缓存与结构基线已按既有语义失效（F043）。",
        }
    )
