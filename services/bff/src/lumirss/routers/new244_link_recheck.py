"""NEW-244 链接存活复核路由 — 批量有界检查 + 四档结果台账。

- POST /api/v1/library/link-recheck          一批 refs（≤50）→ 逐条探测落台账；
- GET  /api/v1/library/link-recheck/results   最近台账（新→旧，有界）。

四档结果：ok / redirect（报 finalUrl）/ dead（404/410）/ unknown
（超时、网络错误、需登录、限流、SSRF 拦截、无 URL、投影缺失——
无法判断绝不冒充失效）。请求非法 → 422 link_recheck_invalid。
per-user 库天然隔离。
"""

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.new244_link_recheck import LinkRecheckInvalid, LinkRecheckService

router = APIRouter()


class LinkRecheckRun(BaseModel):
    model_config = {"extra": "forbid"}

    refs: list[str] = Field(min_length=1, max_length=50)


def _service(request: Request) -> LinkRecheckService:
    return LinkRecheckService(request.app.state.db)


@router.post("/api/v1/library/link-recheck")
async def run_link_recheck(payload: LinkRecheckRun, request: Request) -> Response:
    try:
        result = await _service(request).recheck(payload.refs)
    except LinkRecheckInvalid as exc:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "link_recheck_invalid", "message": str(exc)}},
        )
    return JSONResponse(result)


@router.get("/api/v1/library/link-recheck/results")
async def list_link_recheck_results(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
) -> Response:
    return JSONResponse(await _service(request).recent_results(limit=limit))
