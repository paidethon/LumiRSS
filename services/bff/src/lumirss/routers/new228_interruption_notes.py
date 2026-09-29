"""NEW-228 阅读中断便签路由（接续视图 / 归档 / 清单）。

稳定错误信封：invalid_interruption_note / interruption_note_not_found。
"""

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from lumirss.new228_interruption_notes import (
    InterruptionNoteInvalid,
    InterruptionNoteNotFound,
    InterruptionNoteStore,
)

router = APIRouter()


def _store(request: Request) -> InterruptionNoteStore:
    return InterruptionNoteStore(request.app.state.db)


class NoteUpsertRequest(BaseModel):
    model_config = {"extra": "forbid"}

    itemRef: str
    thought: str = Field(min_length=1, max_length=500)
    resumeHint: str | None = Field(default=None, max_length=300)
    """下次从哪里继续（章节/位置的自由描述）。"""


class NoteView(BaseModel):
    id: str
    itemRef: str
    resumeHint: str | None = None
    thought: str
    createdAt: str
    updatedAt: str
    archivedAt: str | None = None
    title: str | None = None


class NoteUpsertResponse(NoteView):
    pass


class NoteActiveResponse(BaseModel):
    itemRef: str
    note: NoteView | None = None
    """返回文章时的接续便签（无活跃 → null，诚实空态）。"""
    archivedCount: int


class NoteListResponse(BaseModel):
    items: list[NoteView]
    note: str | None = None


class NoteArchiveResponse(NoteView):
    pass


@router.put("/api/v1/reading/interruption-notes", response_model=NoteUpsertResponse)
async def upsert_interruption_note(
    payload: NoteUpsertRequest, request: Request
) -> NoteUpsertResponse:
    """离开前写/改接续便签（一篇一个活跃便签，latest-wins）。"""
    row = await _store(request).upsert(
        payload.itemRef, payload.thought, payload.resumeHint
    )
    return NoteUpsertResponse(**row)


@router.get("/api/v1/reading/interruption-notes", response_model=NoteActiveResponse)
async def get_active_interruption_note(
    request: Request, itemRef: str
) -> NoteActiveResponse:
    """返回文章时的接续视图：活跃便签或 null + 归档计数。"""
    return NoteActiveResponse(**await _store(request).get_active(itemRef))


@router.post("/api/v1/reading/interruption-notes/archive", response_model=NoteArchiveResponse)
async def archive_interruption_note(
    request: Request, itemRef: str
) -> NoteArchiveResponse:
    """读完归档（显式；无活跃便签 → 404）。"""
    row = await _store(request).archive(itemRef)
    return NoteArchiveResponse(**row)


@router.delete("/api/v1/reading/interruption-notes", status_code=204)
async def delete_interruption_note(request: Request, itemRef: str) -> Response:
    """丢弃活跃便签（不归档；显式动作）。"""
    await _store(request).delete(itemRef)
    return Response(status_code=204)


@router.get("/api/v1/reading/interruption-notes/all", response_model=NoteListResponse)
async def list_active_interruption_notes(request: Request) -> NoteListResponse:
    """全部活跃便签（跨材料的「读到一半」清单）。"""
    return NoteListResponse(**await _store(request).list_active())


@router.get("/api/v1/reading/interruption-notes/archived", response_model=NoteListResponse)
async def list_archived_interruption_notes(
    request: Request, itemRef: str | None = None
) -> NoteListResponse:
    """归档历史（可按材料过滤）。"""
    return NoteListResponse(**await _store(request).list_archived(itemRef))


__all__ = ["router", "InterruptionNoteInvalid", "InterruptionNoteNotFound"]
