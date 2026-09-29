"""NEW-345 共享链接次数上限路由。

- POST  /api/v1/privacy/share-links/{id}/limit   设置/更改使用上限（null = 不限；
      me 面不引入 PUT/PATCH —— FIX-046 同一口径）
- POST  /api/v1/privacy/share-links/{id}/topup    手动续额（只加不上减）
- GET   /api/v1/privacy/share-links/{id}/accesses 访问留痕（含被拒的访问）
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from lumirss.new344_share_links import ShareLinkStore
from lumirss.new345_share_link_limits import (
    ShareLinkLimitInvalid,
    clean_max_uses,
    list_accesses,
    topup,
)

router = APIRouter()


def _error(status: int, err_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": err_type, "message": message}},
    )


async def _require_user(request: Request) -> str | None:
    from lumirss.config import LumiSettings
    from lumirss.routers.auth import _current_user_id

    if LumiSettings().LUMIRSS_AUTH_MODE != "session":
        return None
    return await _current_user_id(request)


class MaxUsesBody(BaseModel):
    model_config = {"extra": "forbid"}

    maxUses: int | None = None


class TopupBody(BaseModel):
    model_config = {"extra": "forbid"}

    addUses: int


@router.post("/api/v1/privacy/share-links/{link_id}/limit", response_model=None)
async def set_share_link_limit(
    link_id: int, body: MaxUsesBody, request: Request
) -> JSONResponse:
    user_id = await _require_user(request)
    if user_id is None:
        return _error(401, "session_required", "Login required.")
    store = ShareLinkStore(request.app.state.db)
    link = await store.get(link_id)
    if link is None:
        return _error(404, "share_link_not_found", "共享链接不存在。")
    try:
        max_uses = clean_max_uses(body.maxUses)
    except ShareLinkLimitInvalid as exc:
        return _error(422, "share_link_invalid", str(exc))
    if link["revokedAt"] is None and max_uses is not None:
        # 收紧到已用量以下没有意义：耗尽判定立即成立（如实提示）。
        pass
    from lumirss.util import utc_now

    await request.app.state.db.execute(
        "UPDATE share_links SET max_uses = ?, exhausted_at = CASE"
        " WHEN ? IS NOT NULL AND use_count >= ? AND revoked_at IS NULL"
        " THEN COALESCE(exhausted_at, ?) ELSE NULL END WHERE id = ?",
        (max_uses, max_uses, max_uses, utc_now(), link_id),
    )
    updated = await store.get(link_id)
    assert updated is not None
    return JSONResponse(
        {
            "id": link_id,
            "maxUses": updated["maxUses"],
            "useCount": updated["useCount"],
            "exhaustedAt": updated["exhaustedAt"],
        }
    )


@router.post("/api/v1/privacy/share-links/{link_id}/topup", response_model=None)
async def topup_share_link(
    link_id: int, body: TopupBody, request: Request
) -> JSONResponse:
    user_id = await _require_user(request)
    if user_id is None:
        return _error(401, "session_required", "Login required.")
    store = ShareLinkStore(request.app.state.db)
    link = await store.get(link_id)
    if link is None:
        return _error(404, "share_link_not_found", "共享链接不存在。")
    try:
        return JSONResponse(await topup(request.app.state.db, link, body.addUses))
    except ShareLinkLimitInvalid as exc:
        return _error(422, "share_link_invalid", str(exc))


@router.get("/api/v1/privacy/share-links/{link_id}/accesses", response_model=None)
async def share_link_accesses(
    link_id: int, request: Request, limit: int = 100
) -> JSONResponse:
    user_id = await _require_user(request)
    if user_id is None:
        return _error(401, "session_required", "Login required.")
    store = ShareLinkStore(request.app.state.db)
    link = await store.get(link_id)
    if link is None:
        return _error(404, "share_link_not_found", "共享链接不存在。")
    rows = await list_accesses(request.app.state.db, link_id, limit)
    return JSONResponse(
        {
            "items": rows,
            "note": "访问者身份/IP 不记录；被拒（耗尽）的访问同样留痕但不计数。",
        },
        headers={"Cache-Control": "no-store"},
    )
