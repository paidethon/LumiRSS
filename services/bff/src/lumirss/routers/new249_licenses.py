"""NEW-249 资料引用许可证提示路由 — 记录 / 查询 / 撤销 / 提示预览。

- PUT    /api/v1/licenses/{target_ref}                     登记（或更新）许可证记录；
- GET    /api/v1/licenses/{target_ref}                     单条（无记录 → unknown，不 404）；
- DELETE /api/v1/licenses/{target_ref}                     撤销记录（204）；
- POST   /api/v1/licenses/notice-preview                   一组 refs 的引用限制提示
       （recorded / source_explicit / explicit_undeclared / unknown；输出固定附
       免责声明：仅转述记录与来源明示信息，不构成法律意见）。

负载非法 → 422 license_invalid。per-user 库天然隔离。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.new249_licenses import LicenseInvalid, LicenseRecordStore

router = APIRouter()


class LicenseRecordPut(BaseModel):
    model_config = {"extra": "forbid"}

    licenseText: str = Field(default="", max_length=500)
    infoSource: str = Field(..., pattern="^(user_record|source_explicit)$")
    note: str = Field(default="", max_length=500)


class LicenseNoticePreview(BaseModel):
    model_config = {"extra": "forbid"}

    targetRefs: list[str] = Field(min_length=1, max_length=100)


def _store(request: Request) -> LicenseRecordStore:
    return LicenseRecordStore(request.app.state.db)


def _invalid(message: str) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": {"type": "license_invalid", "message": message}},
    )


@router.put("/api/v1/licenses/{target_ref}")
async def put_license_record(
    target_ref: str, payload: LicenseRecordPut, request: Request
) -> Response:
    try:
        item = await _store(request).put_record(
            target_ref, payload.licenseText, payload.infoSource, payload.note
        )
    except LicenseInvalid as exc:
        return _invalid(str(exc))
    return JSONResponse(item)


@router.get("/api/v1/licenses/{target_ref}")
async def get_license_record(target_ref: str, request: Request) -> Response:
    try:
        item = await _store(request).get_record(target_ref)
    except LicenseInvalid as exc:
        return _invalid(str(exc))
    return JSONResponse(item)


@router.delete("/api/v1/licenses/{target_ref}", status_code=204)
async def delete_license_record(target_ref: str, request: Request) -> Response:
    await _store(request).delete_record(target_ref)
    return Response(status_code=204)


@router.post("/api/v1/licenses/notice-preview")
async def preview_license_notice(payload: LicenseNoticePreview, request: Request) -> Response:
    try:
        result = await _store(request).notice_preview(payload.targetRefs)
    except LicenseInvalid as exc:
        return _invalid(str(exc))
    return JSONResponse(result)
