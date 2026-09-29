"""NEW-243 原始 feed 字段查看器路由 — 脱敏字段 + 应用映射 + 错误映射报告。

- GET  /api/v1/entries/{entry_ref}/raw-fields          脱敏字段视图 + 映射说明；
- GET  /api/v1/entries/{entry_ref}/raw-fields/reports   该文的报告台账；
- POST /api/v1/entries/{entry_ref}/raw-fields/reports   报告一个错误映射。

投影未命中 → 404 raw_fields_not_found；报告负载非法 → 422 raw_field_invalid。
报告只追加台账，不自动改任何映射；per-user 库天然隔离。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.new243_raw_fields import (
    RawFieldInvalid,
    RawFieldsNotFound,
    RawFieldStore,
)

router = APIRouter()


class RawFieldReportCreate(BaseModel):
    model_config = {"extra": "forbid"}

    fieldKey: str = Field(min_length=1, max_length=2000)
    problem: str = Field(min_length=1, max_length=2000)
    expected: str = Field(default="", max_length=2000)


def _store(request: Request) -> RawFieldStore:
    return RawFieldStore(request.app.state.db)


@router.get("/api/v1/entries/{entry_ref}/raw-fields")
async def get_raw_fields(entry_ref: str, request: Request) -> Response:
    try:
        view = await _store(request).get_fields(entry_ref)
    except RawFieldsNotFound:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "type": "raw_fields_not_found",
                    "message": "投影中没有这篇文章，没有原始字段可看。",
                }
            },
        )
    return JSONResponse(view)


@router.get("/api/v1/entries/{entry_ref}/raw-fields/reports")
async def list_raw_field_reports(entry_ref: str, request: Request) -> Response:
    return JSONResponse({"items": await _store(request).list_reports(entry_ref)})


@router.post("/api/v1/entries/{entry_ref}/raw-fields/reports", status_code=201)
async def create_raw_field_report(
    entry_ref: str, payload: RawFieldReportCreate, request: Request
) -> Response:
    try:
        item = await _store(request).add_report(
            entry_ref, payload.fieldKey, payload.problem, payload.expected
        )
    except RawFieldInvalid as exc:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "raw_field_invalid", "message": str(exc)}},
        )
    return JSONResponse(status_code=201, content=item)
