"""NEW-374 资源账单路由。

- GET /api/v1/account/resource-bill            member 自查（同口径）；
- GET /api/v1/admin/users/{user_id}/resource-bill  admin 查阅（计数/字节，
  绝无内容；查阅写台账 + 审计，响应附最近查阅者）。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from lumirss.new374_resource_bill import (
    account_bill,
    open_user_db,
    recent_viewers,
    record_admin_view,
)
from lumirss.routers.admin import _NO_STORE
from lumirss.user_scope import user_context

router = APIRouter()


async def _current_user_id(request: Request) -> str | None:
    from lumirss.config import LumiSettings
    from lumirss.routers.auth import _current_user_id as _session_user

    if LumiSettings().LUMIRSS_AUTH_MODE != "session":
        return None
    return await _session_user(request)


@router.get("/api/v1/account/resource-bill", response_model=None)
async def get_own_bill(request: Request) -> JSONResponse:
    user_id = await _current_user_id(request)
    if user_id is None:
        return JSONResponse(
            status_code=401,
            content={"error": {"type": "session_required", "message": "Login required."}},
            headers=_NO_STORE,
        )
    db = request.app.state.db
    await db.migrate()
    with user_context(user_id):
        payload = await account_bill(db, request.app.state.users_root, user_id)
    return JSONResponse(payload, headers=_NO_STORE)


@router.get("/api/v1/admin/users/{user_id}/resource-bill", response_model=None)
async def admin_get_bill(user_id: str, request: Request) -> JSONResponse:
    from lumirss.accounts_store import AccountsStore
    from lumirss.routers.admin import _require_admin

    principal = await _require_admin(request)
    if principal is None:
        return JSONResponse(
            status_code=403,
            content={"error": {"type": "forbidden", "message": "需要管理员角色。"}},
            headers=_NO_STORE,
        )
    control_db = request.app.state.control_db
    user = await AccountsStore(control_db).get_user(user_id)
    if user is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "user_not_found", "message": "No such member."}},
            headers=_NO_STORE,
        )
    target_db = await open_user_db(request.app.state, user_id)
    payload = await account_bill(target_db, request.app.state.users_root, user_id)
    await record_admin_view(control_db, viewer_id=principal["user_id"], target_user_id=user_id)
    await AccountsStore(control_db).audit(
        actor=principal["user_id"],
        action="resource_bill_viewed",
        object_type="user",
        object_id=user_id,
        detail="counts/bytes only",
    )
    payload["recentViews"] = await recent_viewers(control_db, user_id)
    return JSONResponse(payload, headers=_NO_STORE)
