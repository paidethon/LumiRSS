"""NEW-260 研究分享脱敏预览路由 — 只读盘点 + 确认快照。

- /api/v1/research/projects/{id}/share-preview（GET 只读盘点，零写入）
- /api/v1/research/projects/{id}/share-confirmations（POST 确认快照 /
  GET 确认台账，append-only）

诚实边界：预览/确认都不产出任何真实分享包或导出文件；确认只把
用户逐项勾选结果存成 manifest 快照供核对。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from lumirss.new251_research import ProjectNotFound, ResearchInvalid
from lumirss.new260_share_preview import SharePreviewStore

router = APIRouter()


class ShareConfirmationCreate(BaseModel):
    model_config = {"extra": "forbid"}

    includePrivateNoteIds: list[str]
    anonymizeMemberUsernames: list[str]


def _store(request: Request) -> SharePreviewStore:
    return SharePreviewStore(request.app.state.db, request.app.state.accounts)


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


def _not_found() -> JSONResponse:
    return _error(404, "research_project_not_found", "研究项目不存在。")


@router.get("/api/v1/research/projects/{project_id}/share-preview")
async def get_share_preview(project_id: str, request: Request) -> Response:
    try:
        return JSONResponse(await _store(request).preview(project_id))
    except ProjectNotFound:
        return _not_found()


@router.post("/api/v1/research/projects/{project_id}/share-confirmations", status_code=201)
async def create_share_confirmation(
    project_id: str, payload: ShareConfirmationCreate, request: Request
) -> Response:
    try:
        confirmation = await _store(request).confirm(
            project_id,
            include_note_ids=payload.includePrivateNoteIds,
            anonymize_usernames=payload.anonymizeMemberUsernames,
        )
    except ProjectNotFound:
        return _not_found()
    except ResearchInvalid as exc:
        return _error(422, "invalid_research_payload", str(exc))
    return JSONResponse(status_code=201, content=confirmation)


@router.get("/api/v1/research/projects/{project_id}/share-confirmations")
async def list_share_confirmations(project_id: str, request: Request) -> Response:
    try:
        return JSONResponse(await _store(request).list_confirmations(project_id))
    except ProjectNotFound:
        return _not_found()
