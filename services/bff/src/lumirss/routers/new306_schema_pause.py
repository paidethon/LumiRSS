"""NEW-306 API 抓取变更预警路由（写暂停的确认/恢复入口）。

- POST /api/v1/api-sources/{uuid}/schema-resume {fieldMap?}
      用户确认新映射：可选绑定新 field_map（同一 update 失效语义）→
      单次受控抓取 → 重新确认结构基线 → 清除写暂停；
      抓取失败 → 409 保持暂停（诚实，不假装恢复）。

暂停的**触发**在 feed 发布路径（routers/api_sources.serve_atom 集成
evaluate_required_drift）；本路由只负责解除。
"""

import json

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from lumirss.api_sources import (
    ApiSourceNotFound,
    fetch_json,
    map_items,
)
from lumirss.new306_schema_pause import pause_reason_text

router = APIRouter()


class SchemaResumeBody(BaseModel):
    model_config = {"extra": "forbid"}

    fieldMap: dict[str, str] | None = None


@router.post("/api/v1/api-sources/{source_uuid}/schema-resume")
async def schema_resume(
    source_uuid: str, payload: SchemaResumeBody | None = None, request: Request = None
) -> Response:
    from lumirss.api_source_store import ApiSourceStore

    store = ApiSourceStore(request.app.state.db)
    record = await store.get(source_uuid)
    if record is None:
        raise ApiSourceNotFound(source_uuid)
    if not record.write_paused:
        return JSONResponse(
            {"resumed": False, "note": "该来源未处于写暂停。"}
        )
    # 可选：确认新映射（复用既有 update —— 缓存/基线失效语义一致）。
    if payload is not None and payload.fieldMap is not None:
        from lumirss.api_sources import ApiSourceExpressionError, ApiSourceInvalid

        try:
            record = await store.update(source_uuid, field_map=payload.fieldMap)
        except ApiSourceExpressionError as exc:
            return JSONResponse(
                status_code=422,
                content={"error": {"type": "invalid_mapping_expression", "message": str(exc)}},
            )
        except ApiSourceInvalid as exc:
            return JSONResponse(
                status_code=422,
                content={"error": {"type": "invalid_field_map", "message": str(exc)}},
            )
    # 单次受控抓取：验证新结构并可确认基线。
    try:
        data = await fetch_json(request.app.state.http_client, record.endpoint)
        items = map_items(data, record.items_expr, record.field_map)
    except Exception as exc:
        reason = str(exc) or type(exc).__name__
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "type": "resume_probe_failed",
                    "message": f"恢复探测失败（来源保持暂停）：{reason}",
                }
            },
        )
    if not items:
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "type": "resume_probe_empty",
                    "message": "恢复探测映射结果为空（来源保持暂停）。",
                }
            },
        )
    baseline = await store.confirm_schema(source_uuid, items)
    await store.set_write_paused(source_uuid, False, None)
    return JSONResponse(
        {
            "resumed": True,
            "sampledItems": len(items),
            "baselineConfirmed": bool(baseline),
            "fieldMap": json.loads(record.field_map),
        }
    )


@router.get("/api/v1/api-sources/{source_uuid}/schema-pause")
async def schema_pause_status(source_uuid: str, request: Request) -> Response:
    from lumirss.api_source_store import ApiSourceStore

    store = ApiSourceStore(request.app.state.db)
    record = await store.get(source_uuid)
    if record is None:
        raise ApiSourceNotFound(source_uuid)
    return JSONResponse(
        {
            "writePaused": bool(record.write_paused),
            "pauseReason": record.pause_reason,
            "drift": json.loads(record.schema_drift) if record.schema_drift else None,
        }
    )


_ = pause_reason_text
