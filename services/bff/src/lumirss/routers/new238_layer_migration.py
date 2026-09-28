"""NEW-238 标注批量迁移路由 — 预览 / 应用（层间迁移）。

- POST /api/v1/annotation-layers/migrate/preview {fromLayerId|null, toLayerId, annotationIds?}
- POST /api/v1/annotation-layers/migrate/apply   同体（落写入）。

层缺失 → 404（fromLayerId/toLayerId 指明）；同层或空集 → 422；
entryRef/anchor 永不改写（原文章身份不变）。
"""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from lumirss.new234_annotation_layers import AnnotationLayerStore
from lumirss.new238_layer_migration import (
    LayerMigrationInvalid,
    LayerMigrationNotFound,
    apply_migration,
    preview_migration,
)

router = APIRouter()


class MigrateRequest(BaseModel):
    model_config = {"extra": "forbid"}

    fromLayerId: str | None = None
    toLayerId: str
    annotationIds: list[Any] | None = None


def _layers(request: Request) -> AnnotationLayerStore:
    return AnnotationLayerStore(request.app.state.db)


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


def _validate_ids(payload: MigrateRequest) -> list[str] | None:
    if payload.annotationIds is None:
        return None
    return [str(value) for value in payload.annotationIds]


@router.post("/api/v1/annotation-layers/migrate/preview")
async def migrate_preview(payload: MigrateRequest, request: Request) -> Response:
    """预览来源与标签变化（零写入）。"""
    try:
        result = await preview_migration(
            request.app.state.db,
            _layers(request),
            from_layer_id=payload.fromLayerId,
            to_layer_id=payload.toLayerId,
            annotation_ids=_validate_ids(payload),
        )
    except LayerMigrationNotFound as exc:
        return _error(404, "annotation_layer_not_found", f"层不存在：{exc}。")
    except LayerMigrationInvalid as exc:
        return _error(422, "invalid_layer_migration", str(exc))
    return JSONResponse(result)


@router.post("/api/v1/annotation-layers/migrate/apply")
async def migrate_apply(payload: MigrateRequest, request: Request) -> Response:
    """应用迁移（逐条改层；entryRef/anchor 不动）。"""
    try:
        result = await apply_migration(
            request.app.state.db,
            _layers(request),
            from_layer_id=payload.fromLayerId,
            to_layer_id=payload.toLayerId,
            annotation_ids=_validate_ids(payload),
        )
    except LayerMigrationNotFound as exc:
        return _error(404, "annotation_layer_not_found", f"层不存在：{exc}。")
    except LayerMigrationInvalid as exc:
        return _error(422, "invalid_layer_migration", str(exc))
    return JSONResponse(result)
