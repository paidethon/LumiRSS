"""NEW-377 后台任务阻塞定位路由（管理员）。

- GET /api/v1/admin/task-blockers  实时诊断（重算 + 落账 + 每类安全处置入口）；
- GET /api/v1/admin/task-blockers/ledger  只读台账（历史观测）。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from lumirss.new377_task_blockers import diagnose, recent_ledger
from lumirss.routers.admin import _NO_STORE, _require_admin

router = APIRouter(prefix="/api/v1/admin/task-blockers")


async def _admin_or_error(request: Request) -> JSONResponse | dict[str, str]:
    principal = await _require_admin(request)
    if principal is None:
        return JSONResponse(
            status_code=403,
            content={"error": {"type": "forbidden", "message": "需要管理员角色。"}},
            headers=_NO_STORE,
        )
    return principal


@router.get("", response_model=None)
async def get_blockers(request: Request, maxAccounts: int = 50) -> JSONResponse:
    principal = await _admin_or_error(request)
    if isinstance(principal, JSONResponse):
        return principal
    bounded = max(1, min(maxAccounts, 200))
    payload = await diagnose(request.app.state, request.app.state.control_db, max_accounts=bounded)
    return JSONResponse(payload, headers=_NO_STORE)


@router.get("/ledger", response_model=None)
async def get_ledger(request: Request, limit: int = 20) -> JSONResponse:
    principal = await _admin_or_error(request)
    if isinstance(principal, JSONResponse):
        return principal
    return JSONResponse(
        {"items": await recent_ledger(request.app.state.control_db, limit)},
        headers=_NO_STORE,
    )
