"""NEW-289 简报纯文本邮件文件路由 — 确认期次 → RFC 5322 EML 下载。

- GET /api/v1/briefings/{issue_id}/export.eml → message/rfc822 附件。
  只导出「本人确认」的期次（草稿 409）；绝不发送、绝不 import
  smtplib、不需要 SMTP 凭据——发送与否由用户拿到文件后自行决定。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from lumirss.new281_briefings import BriefingNotFound, BriefingStore
from lumirss.new289_eml import build_eml, filename_for
from lumirss.new290_corrections import CorrectionStore

router = APIRouter()


@router.get("/api/v1/briefings/{issue_id}/export.eml")
async def export_eml(issue_id: str, request: Request) -> Response:
    store = BriefingStore(request.app.state.db)
    try:
        issue = await store.get_issue(issue_id)
    except BriefingNotFound as exc:
        return JSONResponse(
            status_code=404,
            content={
                "error": {"type": "briefing_not_found", "message": str(exc)}
            },
        )
    if issue["status"] != "confirmed":
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "type": "briefing_not_confirmed",
                    "message": "只有已确认的期次可导出 EML（草稿请先确认）。",
                }
            },
        )
    corrections = await CorrectionStore(
        request.app.state.db
    ).list_corrections(issue_id)
    payload = build_eml(issue, corrections)
    return Response(
        content=payload,
        media_type="message/rfc822",
        headers={
            "Content-Disposition": f'attachment; filename="{filename_for(issue)}"'
        },
    )
