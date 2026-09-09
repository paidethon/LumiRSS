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


