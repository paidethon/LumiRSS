"""Admin audit responsibility slice (FIX-161): the minimal audit-trail
read surface. Route moved verbatim from the former ``routers/admin.py``
monolith.
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from lumirss.routers.admin._common import _accounts, _forbid, _require_admin

router = APIRouter()


@router.get("/audit", response_model=None, response_model_exclude_none=True)
async def audit_tail(request: Request, limit: int = 100) -> JSONResponse:
    if await _require_admin(request) is None:
        return _forbid()
    return await _accounts(request).audit_list(limit=limit)
