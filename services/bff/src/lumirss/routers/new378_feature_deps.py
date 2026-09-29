"""NEW-378 实例功能依赖图路由（管理员）。

- GET  /api/v1/admin/feature-dependencies   只读依赖图（未探测 → unknown）；
- POST /api/v1/admin/feature-dependencies/probe  运行本地探测并落库
  （实际探测时间入 admin_feature_probes）。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from lumirss.new378_feature_deps import dependency_graph, probe_all
from lumirss.routers.admin import _NO_STORE, _require_admin

router = APIRouter(prefix="/api/v1/admin/feature-dependencies")


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
async def get_graph(request: Request) -> JSONResponse:
    principal = await _admin_or_error(request)
    if isinstance(principal, JSONResponse):
        return principal
    payload = await dependency_graph(request.app.state.control_db)
    return JSONResponse(payload, headers=_NO_STORE)


@router.post("/probe", response_model=None)
async def post_probe(request: Request) -> JSONResponse:
    principal = await _admin_or_error(request)
    if isinstance(principal, JSONResponse):
        return principal
    payload = await probe_all(request.app.state, request.app.state.control_db)
    return JSONResponse(payload, headers=_NO_STORE)
