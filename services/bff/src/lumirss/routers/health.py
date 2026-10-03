"""Health routes (moved verbatim from main.py)."""



from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from lumirss.config import LumiSettings
from lumirss.deps import _get_operations_service
from lumirss.models import (
    ApiVersionInfo,
    HealthStatus,
    ReadinessResponse,
)

router = APIRouter()


@router.get("/health/live", response_model=HealthStatus)
async def health_live() -> dict[str, str]:
    """Liveness: only proves this process is alive, never touches FreshRSS."""
    return {"status": "ok"}


@router.get("/health/ready", response_model=ReadinessResponse)
async def health_ready(request: Request) -> JSONResponse:
    """Readiness: core dependency (lumi.sqlite) must be usable.

    FreshRSS / RSSHub are reported but NEVER fail readiness — RSSHub being
    down must not make already-fetched reading unavailable (0018 failure
    isolation, AD-0018-3).
    """
    service = _get_operations_service(request)
    # 就绪探测不经认证（CLI 健康门/编排器匿名调用）——session 多账户
    # 模式下匿名请求没有用户上下文，而核心依赖检查探的是控制库。显式
    # 绑定 owner 上下文（与后台扫描循环同一模式）让探针语义与请求身份
    # 解耦；basic 单用户模式行为不变（本就有隐式 owner）。
    owner_id = getattr(request.app.state, "owner_id", None)
    if owner_id:
        from lumirss.user_scope import user_context

        with user_context(owner_id):
            ready, payload = await service.ready()
    else:
        ready, payload = await service.ready()
    return JSONResponse(status_code=200 if ready else 503, content=payload)


@router.get("/api/v1/version", response_model=ApiVersionInfo)
async def version() -> dict[str, object]:
    """Build provenance for Web/BFF skew diagnosis.

    Deliberately minimal: no env dump, no paths, no secrets — just the
    running BFF's version/commit so a stale deployment is diagnosable
    from the browser (see also the web build commit on the About page).
    """
    settings = LumiSettings()
    return {
        "version": settings.LUMIRSS_VERSION,
        "commit": settings.LUMIRSS_COMMIT,
        "apiVersion": 1,
    }


