"""NEW-262 译文人工修订层路由 — 逐段「放弃修订并重翻」的显式决定。

- POST /api/v1/entries/{ref}/translation/segments/{index}/revision/discard
  body {regenerate?: bool}
  放弃一段的人工修订：被放弃时刻的人工文本完整留底（0189 只追加台账，
  任何覆盖都不销毁历史）；随后该段回到普通未生成状态。
  regenerate=true → 用缓存行留存的源段文本立即重翻一次（只发该段，
  已有成功结果的段零 provider 调用）。
- GET  /api/v1/entries/{ref}/translation/revision-decisions
  某篇的决定台账（新→旧），供回看「放弃了什么」。

无缓存行 / 无修订可放弃 → 422 revision_discard_invalid。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from lumirss.ai_translation_segments import SegmentInput
from lumirss.deps import _get_segment_service
from lumirss.entryref import decode_entry_ref
from lumirss.new262_revision_decisions import (
    RevisionDiscardInvalid,
    discard_revision,
    list_decisions,
)

router = APIRouter()


class RevisionDiscardBody(BaseModel):
    model_config = {"extra": "forbid"}

    regenerate: bool = False


def _invalid_index(block_index: int) -> JSONResponse | None:
    if not 0 <= block_index <= 63:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "type": "invalid_segment_index",
                    "message": "block_index 必须在 0..63 之间。",
                }
            },
        )
    return None


@router.post(
    "/api/v1/entries/{entry_ref}/translation/segments/{block_index}/revision/discard",
    response_model=None,
)
async def post_revision_discard(
    entry_ref: str,
    block_index: int,
    request: Request,
    payload: RevisionDiscardBody | None = None,
) -> dict[str, object] | JSONResponse:
    """放弃一段修订（留底 + 撤销）；可选立即按缓存源段重翻。"""
    decode_entry_ref(entry_ref)
    invalid = _invalid_index(block_index)
    if invalid is not None:
        return invalid
    db = request.app.state.db
    try:
        decision = await discard_revision(db, entry_ref, block_index)
    except RevisionDiscardInvalid as exc:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "type": "revision_discard_invalid",
                    "message": str(exc),
                }
            },
        )

    regenerated: dict[str, object] | None = None
    if payload is not None and payload.regenerate:
        # 立即重翻：源段文本取自放弃时刻的缓存行留存（decision.source_text；
        # 源文更新后以读取到的当前块重新生成为准）。
        source_text = decision.source_text.strip()
        if source_text:
            service = _get_segment_service(request)
            states = await service.generate(
                entry_ref, [SegmentInput(index=block_index, text=source_text)]
            )
            state = states[0]
            regenerated = {
                "status": state.status,
                "translatedText": state.translated_text,
                "failureType": state.failure_type,
                "cached": state.cached,
            }
        else:
            regenerated = {"status": "not_generated", "reason": "source_text_unavailable"}
    return {
        "id": decision.id,
        "blockIndex": decision.index,
        "overwrittenText": decision.overwritten_text,
        "supersededMachineText": decision.superseded_machine_text,
        "createdAt": decision.created_at,
        "regenerated": regenerated,
    }


@router.get("/api/v1/entries/{entry_ref}/translation/revision-decisions")
async def get_revision_decisions(
    entry_ref: str, request: Request
) -> dict[str, object]:
    """某篇的「修订 → 放弃重翻」决定台账（新→旧）。"""
    decode_entry_ref(entry_ref)
    decisions = await list_decisions(request.app.state.db, entry_ref)
    return {"decisions": decisions}
