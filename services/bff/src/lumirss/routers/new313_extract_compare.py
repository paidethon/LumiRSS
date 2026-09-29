"""NEW-313 剪藏正文候选对照路由 — 抓取一次、两种候选、用户选择应用。

- POST /api/v1/library/clips/{uuid}/extract-compare → 200 对照预览（写入候选行）
- GET  /api/v1/library/clips/{uuid}/extract-compare → 最近一轮对照
- POST /api/v1/library/clips/{uuid}/extract-compare/{candidate_id}/choose
      → 应用所选候选到修订槽（原始版本与笔记锚点不动）

抓取走默认的有界 SSRF 管线；网络失败 → 502 clip_fetch_failed（诚实失败）。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from lumirss.clip_fetch import ClipFetchError
from lumirss.library_clips import ClipNotFound
from lumirss.new313_extract_compare import ExtractCompareService

router = APIRouter()


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


def _service(request: Request) -> ExtractCompareService:
    # 测试通过 app.state.extract_compare_fetcher 注入假抓取；生产走
    # 默认的有界 SSRF 管线（fetch_extract_sanitize）。
    fetcher = getattr(request.app.state, "extract_compare_fetcher", None)
    return ExtractCompareService(request.app.state.db, fetcher=fetcher)


@router.post("/api/v1/library/clips/{item_uuid}/extract-compare")
async def compare_extract_candidates(item_uuid: str, request: Request) -> Response:
    try:
        return JSONResponse(await _service(request).compare(item_uuid, base_url=""))
    except ClipNotFound:
        return _error(404, "clip_not_found", "剪藏不存在。")
    except ClipFetchError as exc:
        return _error(
            502,
            "clip_fetch_failed",
            f"原文抓取失败（{exc.reason}）：{exc}。旧候选保持不变。",
        )


@router.get("/api/v1/library/clips/{item_uuid}/extract-compare")
async def get_last_compare(item_uuid: str, request: Request) -> Response:
    try:
        result = await _service(request).last_compare(item_uuid)
    except ClipNotFound:
        return _error(404, "clip_not_found", "剪藏不存在。")
    if result is None:
        return _error(404, "extract_compare_not_found", "还没有候选对照。")
    return JSONResponse(result)


@router.post(
    "/api/v1/library/clips/{item_uuid}/extract-compare/{candidate_id}/choose"
)
async def choose_extract_candidate(
    item_uuid: str, candidate_id: str, request: Request
) -> Response:
    try:
        return JSONResponse(
            await _service(request).choose(item_uuid, candidate_id)
        )
    except ClipNotFound:
        return _error(404, "candidate_not_found", "候选不存在或不属于该剪藏。")
