"""NEW-296 邮件附件单独入库路由 — 转出独立条目 + 列表 + 下载 + 删除。

- POST   /api/v1/email-materials/{id}/attachments/{ord}/promote → 转出
- GET    /api/v1/email-attachment-items                          → 清单
- GET    /api/v1/email-attachment-items/{itemId}/download        → 原始字节
- DELETE /api/v1/email-attachment-items/{itemId}                 → 删除条目
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from lumirss.new296_email_attachments import (
    AttachmentNotFound,
    AttachmentPromoteError,
    EmailAttachmentItemStore,
)

router = APIRouter()


@router.post("/api/v1/email-materials/{material_id}/attachments/{ord}/promote")
async def post_attachment_promote(
    material_id: str, ord: int, request: Request
) -> Response:
    try:
        item = await EmailAttachmentItemStore(request.app.state.db).promote(
            material_id, ord
        )
    except AttachmentNotFound as exc:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "attachment_not_found", "message": str(exc)}},
        )
    except AttachmentPromoteError as exc:
        return JSONResponse(
            status_code=422,
            content={
                "error": {"type": "attachment_not_stored", "message": str(exc)}
            },
        )
    return JSONResponse(item, status_code=201)


@router.get("/api/v1/email-attachment-items")
async def get_attachment_items(request: Request) -> Response:
    return JSONResponse(
        await EmailAttachmentItemStore(request.app.state.db).list_items()
    )


@router.get("/api/v1/email-attachment-items/{item_id}/download")
async def get_attachment_download(item_id: str, request: Request) -> Response:
    item = await EmailAttachmentItemStore(request.app.state.db).download(item_id)
    if item is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "type": "attachment_item_not_found",
                    "message": "没有这个附件条目或其内容未存。",
                }
            },
        )
    data: bytes = item.pop("data") or b""
    from urllib.parse import quote

    from fastapi.responses import Response as FastAPIResponse

    # RFC 5987：非 ASCII 文件名用 filename*，另给 ASCII 兜底。
    quoted = quote(str(item["filename"] or "attachment"), safe="")
    return FastAPIResponse(
        content=data,
        media_type=item["contentType"] or "application/octet-stream",
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"attachment\"; filename*=UTF-8''{quoted}"
            )
        },
    )


@router.delete("/api/v1/email-attachment-items/{item_id}", status_code=204)
async def delete_attachment_item(item_id: str, request: Request) -> Response:
    deleted = await EmailAttachmentItemStore(request.app.state.db).delete_item(
        item_id
    )
    if not deleted:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "type": "attachment_item_not_found",
                    "message": "没有这个附件条目。",
                }
            },
        )
    return Response(status_code=204)
