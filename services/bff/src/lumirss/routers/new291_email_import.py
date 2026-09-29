"""NEW-291 EML 拖入阅读路由 — 用户上传邮件文件为资料条目。

- POST /api/v1/email-materials/import {files:[{filename, content}]}
      → 解析入库；逐文件 imported/failed 如实返回（坏文件不毁整批）
- GET  /api/v1/email-materials?source=&limit=  → 资料条目清单（摘要）
- GET  /api/v1/email-materials/{id}            → 详情（净化正文 + 头部）
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.new291_email_import import (
    EmailImportInvalid,
    EmailMaterialStore,
)

router = APIRouter()


class ImportFile(BaseModel):
    model_config = {"extra": "forbid"}

    filename: str = Field(default="", max_length=255)
    content: str


class EmailImportBody(BaseModel):
    model_config = {"extra": "forbid"}

    files: list[ImportFile]


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


@router.post("/api/v1/email-materials/import")
async def post_email_import(payload: EmailImportBody, request: Request) -> Response:
    store = EmailMaterialStore(request.app.state.db)
    try:
        result = await store.import_files(
            [file.model_dump() for file in payload.files]
        )
    except EmailImportInvalid as exc:
        return _error(422, "email_import_invalid", str(exc))
    return JSONResponse(result, status_code=200)


@router.get("/api/v1/email-materials")
async def get_email_materials(request: Request, source: str = "", limit: int = 50) -> Response:
    store = EmailMaterialStore(request.app.state.db)
    return JSONResponse(await store.list_materials(source=source, limit=limit))


@router.get("/api/v1/email-materials/{material_id}")
async def get_email_material(material_id: str, request: Request) -> Response:
    store = EmailMaterialStore(request.app.state.db)
    view = await store.get_material(material_id)
    if view is None:
        return _error(404, "email_material_not_found", "没有这条邮件资料条目。")
    return JSONResponse(view)
