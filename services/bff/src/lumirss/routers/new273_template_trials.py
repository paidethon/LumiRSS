"""NEW-273 提示模板试运行路由 — 试跑 / 台账 / 显式启用。

- POST /api/v1/ai/template-trials
      {templateText, samples:[{title,text}] (1..3), sampleKind?} → 试跑台账
- GET  /api/v1/ai/template-trials            → 台账（新→旧）
- GET  /api/v1/ai/template-trials/{id}       → 单次试跑（含逐样本输入/输出/用量）
- POST /api/v1/ai/template-trials/{id}/promote {name} → 启用为正式 qa_template
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.new273_template_trials import (
    TemplateTrialStore,
    TrialInvalid,
    TrialNotFound,
)

router = APIRouter()


class TrialSample(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=4000)


class TrialRunBody(BaseModel):
    model_config = {"extra": "forbid"}

    templateText: str = Field(min_length=1, max_length=4000)
    samples: list[TrialSample] = Field(min_length=1, max_length=3)
    sampleKind: str = "custom"


class TrialPromoteBody(BaseModel):
    model_config = {"extra": "forbid"}

    name: str = Field(min_length=1, max_length=120)


def _store(request: Request) -> TemplateTrialStore:
    from lumirss.deps import _get_ai_settings_store, _provider_factory_for

    return TemplateTrialStore(
        db=request.app.state.db,
        settings_store=_get_ai_settings_store(request),
        provider_factory=_provider_factory_for(request, "chat"),
    )


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


@router.post("/api/v1/ai/template-trials")
async def run_template_trial(
    payload: TrialRunBody, request: Request
) -> Response:
    """在少量样本上试跑模板（逐样本一次真实调用，用量如实记录）。"""
    from lumirss.ai_quota import quota_denial

    denial = await quota_denial(request, purpose="chat")
    if denial is not None:
        return denial
    try:
        trial = await _store(request).run_trial(
            payload.templateText,
            [sample.model_dump() for sample in payload.samples],
            sample_kind=payload.sampleKind,
        )
    except TrialInvalid as exc:
        return _error(422, "invalid_trial_request", str(exc))
    return JSONResponse(trial, status_code=201)


@router.get("/api/v1/ai/template-trials")
async def list_template_trials(request: Request) -> Response:
    trials = await _store(request).list_trials()
    return JSONResponse({"items": trials, "total": len(trials)})


@router.get("/api/v1/ai/template-trials/{trial_id}")
async def get_template_trial(trial_id: str, request: Request) -> Response:
    try:
        trial = await _store(request).get_trial(trial_id)
    except TrialNotFound:
        return _error(404, "trial_not_found", "试跑不存在。")
    return JSONResponse(trial)


@router.post("/api/v1/ai/template-trials/{trial_id}/promote")
async def promote_template_trial(
    trial_id: str, payload: TrialPromoteBody, request: Request
) -> Response:
    """显式启用：模板原文升级为正式 qa_template（幂等）。"""
    from lumirss.qa_templates import QaTemplateInvalid

    try:
        trial = await _store(request).promote(trial_id, payload.name)
    except TrialNotFound:
        return _error(404, "trial_not_found", "试跑不存在。")
    except TrialInvalid as exc:
        return _error(422, "invalid_trial_request", str(exc))
    except QaTemplateInvalid as exc:
        return _error(422, "invalid_qa_template", str(exc))
    return JSONResponse(trial)
