"""NEW-300 邮件资料脱敏导出路由 — 默认脱敏 + 显式保留 + 删除清单。

- POST /api/v1/email-materials/{id}/export {includeAddresses?,
      includeFullHeaders?} → 导出载荷（默认全脱敏）+ removedFields
- GET  /api/v1/email-export-logs?materialId= → 导出审计（选项+删除清单）
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from lumirss.new300_email_export import EmailExportStore

router = APIRouter()


class ExportBody(BaseModel):
    model_config = {"extra": "forbid"}

    includeAddresses: bool = False
    includeFullHeaders: bool = False


@router.post("/api/v1/email-materials/{material_id}/export")
async def post_email_export(
    material_id: str, payload: ExportBody, request: Request
) -> Response:
    result = await EmailExportStore(request.app.state.db).export_material(
        material_id,
        include_addresses=payload.includeAddresses,
        include_full_headers=payload.includeFullHeaders,
    )
    if result is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "type": "email_material_not_found",
                    "message": "没有这条邮件资料条目。",
                }
            },
        )
    return JSONResponse(result)


@router.get("/api/v1/email-export-logs")
async def get_export_logs(request: Request, materialId: str = "") -> Response:
    return JSONResponse(
        await EmailExportStore(request.app.state.db).list_logs(
            materialId or None
        )
    )
