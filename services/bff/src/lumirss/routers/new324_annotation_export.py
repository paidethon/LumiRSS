"""NEW-324 阅读批注 Markdown 输出路由 — 生成文件内容（用户自行保存）。

- POST /api/v1/annotations/markdown-export  {entryRefs: [...]} → {filename, content}
- GET  /api/v1/annotations/markdown-export  导出台账（最近 50）

Lumi 不代写文件、不写 Vault：响应体是文件内容 + 建议文件名，保存由
用户完成。批注是 per-user 数据——A 的导出绝不含 B 的批注（无需
owner 门槛，任何登录账户导出自己批注）。
"""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from lumirss.new324_annotation_export import (
    AnnotationExportInvalid,
    AnnotationMarkdownExporter,
)

router = APIRouter()


@router.post("/api/v1/annotations/markdown-export")
async def export_annotations_markdown(
    payload: dict[str, Any], request: Request
) -> Any:
    try:
        result = await AnnotationMarkdownExporter(request.app.state.db).export(
            payload.get("entryRefs") or []
        )
    except AnnotationExportInvalid as exc:
        return JSONResponse(
            status_code=400,
            content={
                "error": {"type": "invalid_annotation_export", "message": str(exc)}
            },
        )
    return JSONResponse(result)


@router.get("/api/v1/annotations/markdown-export")
async def list_annotation_export_history(request: Request) -> Any:
    return JSONResponse(
        {"exports": await AnnotationMarkdownExporter(request.app.state.db).history()}
    )
