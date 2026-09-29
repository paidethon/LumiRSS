"""NEW-272 AI 草稿版本对照路由 — 生成 / 保存 / 对照 / 保留。

- POST   /api/v1/entries/{entry_ref}/ai-drafts/generate
      {schemeLabel, promptText, maxChars?} → 一次有界 provider 调用 → 草稿
- POST   /api/v1/entries/{entry_ref}/ai-drafts
      {schemeLabel, draftText, promptText?, materialHash?} → 手动保存候选
- GET    /api/v1/entries/{entry_ref}/ai-drafts → 分组列表（同材料并列）
- GET    /api/v1/ai-drafts/{draft_id} → 单份草稿
- GET    /api/v1/ai-drafts/{a}/diff/{b} → 逐行差异（非同组 422）
- POST   /api/v1/ai-drafts/{draft_id}/keep → 组内单选保留
- DELETE /api/v1/ai-drafts/{draft_id} → 204

保留/删除草稿绝不写 ai_summaries / lumi_notes（人工结论面零接触）。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.entryref import decode_entry_ref
from lumirss.new272_ai_drafts import (
    DraftInvalid,
    DraftNotFound,
    DraftStore,
)

router = APIRouter()


class DraftGenerateBody(BaseModel):
    model_config = {"extra": "forbid"}

    schemeLabel: str = Field(min_length=1, max_length=120)
    promptText: str = Field(min_length=1, max_length=4000)
    maxChars: int | None = Field(default=None, ge=512, le=50000)


class DraftSaveBody(BaseModel):
    model_config = {"extra": "forbid"}

    schemeLabel: str = Field(min_length=1, max_length=120)
    draftText: str = Field(min_length=1, max_length=20000)
    promptText: str | None = Field(default=None, max_length=4000)
    materialHash: str | None = Field(default=None, max_length=64)


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


def _store(request: Request) -> DraftStore:
    from lumirss.deps import (
        _get_adapter,
        _get_ai_settings_store,
        _provider_factory_for,
    )

    return DraftStore(
        db=request.app.state.db,
        adapter=_get_adapter(request),
        settings_store=_get_ai_settings_store(request),
        provider_factory=_provider_factory_for(request, "chat"),
    )


def _guard(exc: Exception) -> JSONResponse | None:
    if isinstance(exc, DraftInvalid):
        return _error(422, "invalid_draft_request", str(exc))
    if isinstance(exc, DraftNotFound):
        return _error(404, "draft_not_found", "草稿不存在。")
    return None


@router.post("/api/v1/entries/{entry_ref}/ai-drafts/generate")
async def generate_draft(
    entry_ref: str, payload: DraftGenerateBody, request: Request
) -> Response:
    """按一个提示方案生成候选草稿（配额/约束/费用与其它 AI 面同口径）。"""
    decode_entry_ref(entry_ref)
    from lumirss.ai_quota import quota_denial

    denial = await quota_denial(request, purpose="chat")
    if denial is not None:
        return denial
    try:
        record = await _store(request).generate_draft(
            entry_ref,
            scheme_label=payload.schemeLabel,
            prompt_text=payload.promptText,
            max_chars=payload.maxChars,
        )
    except Exception as exc:  # noqa: BLE001 — 统一稳定错误映射
        denial = _guard(exc)
        if denial is not None:
            return denial
        raise
    return JSONResponse(record.to_json(), status_code=201)


@router.post("/api/v1/entries/{entry_ref}/ai-drafts")
async def save_draft(
    entry_ref: str, payload: DraftSaveBody, request: Request
) -> Response:
    """保存一份候选草稿（客户端已有文本；不调用 provider）。"""
    decode_entry_ref(entry_ref)
    try:
        record = await _store(request).save_draft(
            entry_ref,
            scheme_label=payload.schemeLabel,
            draft_text=payload.draftText,
            prompt_text=payload.promptText or "",
            material_hash=payload.materialHash or "",
        )
    except Exception as exc:  # noqa: BLE001
        denial = _guard(exc)
        if denial is not None:
            return denial
        raise
    return JSONResponse(record.to_json(), status_code=201)


@router.get("/api/v1/entries/{entry_ref}/ai-drafts")
async def list_drafts(entry_ref: str, request: Request) -> Response:
    decode_entry_ref(entry_ref)
    records = await _store(request).list_drafts(entry_ref)
    groups: dict[str, list[dict]] = {}
    for record in records:
        groups.setdefault(record.material_hash, []).append(record.to_json())
    return JSONResponse(
        {
            "entryRef": entry_ref,
            "groups": [
                {"materialHash": material_hash, "drafts": drafts}
                for material_hash, drafts in groups.items()
            ],
            "total": len(records),
        }
    )


@router.get("/api/v1/ai-drafts/{draft_id}")
async def get_draft(draft_id: str, request: Request) -> Response:
    try:
        record = await _store(request).get_draft(draft_id)
    except DraftNotFound:
        return _error(404, "draft_not_found", "草稿不存在。")
    return JSONResponse(record.to_json())


@router.get("/api/v1/ai-drafts/{draft_a}/diff/{draft_b}")
async def diff_drafts(draft_a: str, draft_b: str, request: Request) -> Response:
    try:
        result = await _store(request).diff_drafts(draft_a, draft_b)
    except Exception as exc:  # noqa: BLE001
        denial = _guard(exc)
        if denial is not None:
            return denial
        raise
    return JSONResponse(result)


@router.post("/api/v1/ai-drafts/{draft_id}/keep")
async def keep_draft(draft_id: str, request: Request) -> Response:
    """组内单选保留（显式用户选择；人工结论面零接触）。"""
    try:
        record = await _store(request).keep_draft(draft_id)
    except DraftNotFound:
        return _error(404, "draft_not_found", "草稿不存在。")
    return JSONResponse(record.to_json())


@router.delete("/api/v1/ai-drafts/{draft_id}", status_code=204)
async def delete_draft(draft_id: str, request: Request) -> Response:
    deleted = await _store(request).delete_draft(draft_id)
    if not deleted:
        return _error(404, "draft_not_found", "草稿不存在。")
    return Response(status_code=204)
