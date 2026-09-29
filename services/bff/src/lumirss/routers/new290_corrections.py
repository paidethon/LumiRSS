"""NEW-290 简报历史更正路由 — 追加式更正（无 UPDATE/DELETE 路径）。

- POST /api/v1/briefings/{issue_id}/corrections {body} → 201（追加）
- GET  /api/v1/briefings/{issue_id}/corrections        → 按时间读回
- PATCH/DELETE 同路径 → FastAPI 天然 405（模块根本没有那些处理器，
  这就是「只增不改不删」的机制保证，不靠自觉）。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from lumirss.new281_briefings import (
    BriefingInvalid,
    BriefingNotFound,
    BriefingStore,
)
from lumirss.new290_corrections import (
    CorrectionStateConflict,
    CorrectionStore,
)

router = APIRouter()


class CorrectionBody(BaseModel):
    model_config = {"extra": "forbid"}

    body: str


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


@router.post("/api/v1/briefings/{issue_id}/corrections")
async def add_correction(
    issue_id: str, payload: CorrectionBody, request: Request
) -> Response:
    try:
        correction = await CorrectionStore(request.app.state.db).add(
            BriefingStore(request.app.state.db),
            issue_id,
            body=payload.body,
        )
    except CorrectionStateConflict as exc:
        return _error(409, "briefing_not_confirmed", str(exc))
    except BriefingInvalid as exc:
        return _error(422, "invalid_briefing_payload", str(exc))
    except BriefingNotFound as exc:
        return _error(404, "briefing_not_found", str(exc))
    return JSONResponse(correction, status_code=201)


@router.get("/api/v1/briefings/{issue_id}/corrections")
async def list_corrections(issue_id: str, request: Request) -> Response:
    store = CorrectionStore(request.app.state.db)
    # 404 语义与期次路由同形：不存在的期次不泄露「更正表存在性」。
    try:
        await BriefingStore(request.app.state.db).get_issue(issue_id)
    except BriefingNotFound as exc:
        return _error(404, "briefing_not_found", str(exc))
    corrections = await store.list_corrections(issue_id)
    return JSONResponse(
        {
            "corrections": corrections,
            "count": len(corrections),
            "honestyNote": (
                "更正只增不改不删；期次正文永不静默替换，读者在 RSS/EML/"
                "详情三面看到的都是「原文 + 更正提示」。"
            ),
        }
    )
