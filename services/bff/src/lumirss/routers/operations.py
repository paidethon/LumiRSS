"""Operations routes (moved verbatim from main.py)."""



from fastapi import APIRouter, Request

from lumirss.backup import (
    _job_json,
)
from lumirss.deps import (
    _get_backup_jobs,
    _get_operations_service,
    _get_rsshub_control_store,
    _get_webdav_settings,
)
from lumirss.models import (
    OperationsStatus,
)

router = APIRouter()


@router.get(
    "/api/v1/operations/status",
    response_model=OperationsStatus,
    response_model_exclude_none=False,  # latencyMs/error/lastBackup may be null
)
async def operations_status(request: Request) -> dict[str, object]:
    """Redacted, real dependency status for the operations UI (no fake metrics)."""
    service = _get_operations_service(request)
    status = await service.full_status()
    rsshub_store = _get_rsshub_control_store(request)
    flags = await rsshub_store.restart_required_flags()
    status["rsshub"]["restartRequired"] = flags["count"] > 0
    status["rsshub"]["pendingConfigCount"] = flags["count"]
    webdav = _get_webdav_settings(request)
    doc = await webdav.load()
    jobs = _get_backup_jobs(request)
    last = await jobs.last_succeeded()
    status["backup"] = {
        "webdavConfigured": webdav.configured(doc),
        "lastBackup": _job_json(last) if last else None,
    }
    return status


