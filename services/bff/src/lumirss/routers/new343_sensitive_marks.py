"""NEW-343 敏感资料标记路由。

- GET    /api/v1/privacy/ai-send-blocks                  本人标记清单
- POST   /api/v1/privacy/ai-send-blocks/{entry_ref}      设置/更新标记（幂等 upsert，
      可带原因；me 面不引入 PUT/PATCH —— FIX-046 同一口径）
- DELETE /api/v1/privacy/ai-send-blocks/{entry_ref}      解除标记

发送路径的真实拦截在 entry_ai.py 的四条 AI 发送路径（摘要/对话/
翻译分段/对照）统一调用 new343.ai_send_block_denial。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.entryref import decode_entry_ref
from lumirss.new343_sensitive_marks import (
    HONESTY_NOTE,
    InvalidSensitiveMark,
    SensitiveMarkStore,
)

router = APIRouter()


def _store(request: Request) -> SensitiveMarkStore:
    return SensitiveMarkStore(request.app.state.db)


def _invalid(exc: InvalidSensitiveMark) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": {"type": "mark_invalid", "message": str(exc)}},
    )


async def _require_user(request: Request) -> str | None:
    from lumirss.config import LumiSettings
    from lumirss.routers.auth import _current_user_id

    if LumiSettings().LUMIRSS_AUTH_MODE != "session":
        return None
    return await _current_user_id(request)


class MarkBody(BaseModel):
    model_config = {"extra": "forbid"}

    reason: str | None = Field(default=None, max_length=200)


@router.get("/api/v1/privacy/ai-send-blocks", response_model=None)
async def list_marks(request: Request) -> JSONResponse:
    user_id = await _require_user(request)
    if user_id is None:
        return JSONResponse(
            status_code=401,
            content={
                "error": {"type": "session_required", "message": "Login required."}
            },
        )
    items = await _store(request).list_marks()
    return JSONResponse(
        {"items": items, "note": HONESTY_NOTE},
        headers={"Cache-Control": "no-store"},
    )


@router.post("/api/v1/privacy/ai-send-blocks/{entry_ref}", response_model=None)
async def post_mark(entry_ref: str, body: MarkBody, request: Request) -> JSONResponse:
    user_id = await _require_user(request)
    if user_id is None:
        return JSONResponse(
            status_code=401,
            content={
                "error": {"type": "session_required", "message": "Login required."}
            },
        )
    try:
        decode_entry_ref(entry_ref)
    except Exception:  # noqa: BLE001 — 非法 ref → 400（与 AI 端点同契约）
        return JSONResponse(
            status_code=400,
            content={
                "error": {"type": "invalid_entry_reference", "message": "entry_ref 非法。"}
            },
        )
    try:
        payload = await _store(request).set_mark(entry_ref, body.reason)
    except InvalidSensitiveMark as exc:
        return _invalid(exc)
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


@router.delete("/api/v1/privacy/ai-send-blocks/{entry_ref}", response_model=None)
async def delete_mark(entry_ref: str, request: Request) -> JSONResponse:
    user_id = await _require_user(request)
    if user_id is None:
        return JSONResponse(
            status_code=401,
            content={
                "error": {"type": "session_required", "message": "Login required."}
            },
        )
    removed = await _store(request).clear_mark(entry_ref)
    if not removed:
        return JSONResponse(
            status_code=404,
            content={
                "error": {"type": "mark_not_found", "message": "该文章没有标记。"}
            },
        )
    return JSONResponse({"entryRef": entry_ref, "cleared": True})
