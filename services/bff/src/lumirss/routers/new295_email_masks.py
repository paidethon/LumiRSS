"""NEW-295 邮件隐私内容遮罩路由 — 显式遮罩 + 分享视图（原文不动）。

- POST   /api/v1/email-materials/{id}/masks {kind, value} → 新增遮罩
- GET    /api/v1/email-materials/{id}/share-view          → 遮罩后的分享视图
- DELETE /api/v1/email-masks/{maskId}                     → 取消遮罩
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.new295_email_masks import (
    EmailMaskStore,
    MaskInvalid,
    MaskTextNotFound,
)

router = APIRouter()


class MaskBody(BaseModel):
    model_config = {"extra": "forbid"}

    kind: str = Field(min_length=1, max_length=20)
    value: str = Field(min_length=1, max_length=2000)


@router.post("/api/v1/email-materials/{material_id}/masks")
async def post_email_mask(
    material_id: str, payload: MaskBody, request: Request
) -> Response:
    try:
        mask = await EmailMaskStore(request.app.state.db).add_mask(
            material_id, payload.kind, payload.value
        )
    except MaskTextNotFound as exc:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "mask_text_not_found", "message": str(exc)}},
        )
    except MaskInvalid as exc:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "mask_invalid", "message": str(exc)}},
        )
    return JSONResponse(mask, status_code=201)


@router.get("/api/v1/email-materials/{material_id}/share-view")
async def get_share_view(material_id: str, request: Request) -> Response:
    view = await EmailMaskStore(request.app.state.db).share_view(material_id)
    if view is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "type": "email_material_not_found",
                    "message": "没有这条邮件资料条目。",
                }
            },
        )
    return JSONResponse(view)


@router.delete("/api/v1/email-masks/{mask_id}", status_code=204)
async def delete_email_mask(mask_id: str, request: Request) -> Response:
    deleted = await EmailMaskStore(request.app.state.db).delete_mask(mask_id)
    if not deleted:
        return JSONResponse(
            status_code=404,
            content={
                "error": {"type": "mask_not_found", "message": "没有这条遮罩。"}
            },
        )
    return Response(status_code=204)
