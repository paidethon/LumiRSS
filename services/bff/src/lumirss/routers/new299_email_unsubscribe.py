"""NEW-299 通讯退订信息卡路由 — 展示原文退订信息 + 用户主动打开记录。

- GET  /api/v1/email-materials/{id}/unsubscribe → 信息卡（可能「无」）
- POST /api/v1/email-materials/{id}/unsubscribe-open {method, target}
      → 记录用户主动打开（仅审计；LumiRSS 不发送任何请求）
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.new299_email_unsubscribe import EmailUnsubStore

router = APIRouter()


class UnsubOpenBody(BaseModel):
    model_config = {"extra": "forbid"}

    method: str = Field(min_length=1, max_length=10)
    target: str = Field(min_length=1, max_length=2000)


@router.get("/api/v1/email-materials/{material_id}/unsubscribe")
async def get_unsubscribe_card(material_id: str, request: Request) -> Response:
    card = await EmailUnsubStore(request.app.state.db).card(material_id)
    if card is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "type": "email_material_not_found",
                    "message": "没有这条邮件资料条目。",
                }
            },
        )
    return JSONResponse(card)


@router.post("/api/v1/email-materials/{material_id}/unsubscribe-open")
async def post_unsubscribe_open(
    material_id: str, payload: UnsubOpenBody, request: Request
) -> Response:
    try:
        result = await EmailUnsubStore(request.app.state.db).record_open(
            material_id, payload.method, payload.target
        )
    except LookupError:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "type": "email_material_not_found",
                    "message": "没有这条邮件资料条目。",
                }
            },
        )
    except ValueError as exc:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "unsub_open_invalid", "message": str(exc)}},
        )
    return JSONResponse(result, status_code=201)
