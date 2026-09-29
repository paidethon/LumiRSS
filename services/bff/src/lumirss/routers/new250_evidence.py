"""NEW-250 证据完整性检查单路由 — 建单 / 报告视图 / 逐项补齐。

- POST  /api/v1/evidence-checklists                          建单（幂等：重复引文不重复建）；
- GET   /api/v1/evidence-checklists/{report_label}            报告视图：每条引文的
       source / version / excerpt 三项状态 + 缺项清单 + 完整计数；
- PATCH /api/v1/evidence-checklists/{report_label}/items/{citation_ref}
       逐项补齐（只改提交的字段：sourceRef / versionId / excerpt）。

版本证据以 NEW-241 的已保存版本为准：versionId 指向被删版本 →
honest missing（hasVersion=false），不冒充已具备。
负载非法 → 422 evidence_invalid；报告/引文项不存在 → 404 evidence_not_found。
per-user 库天然隔离。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.new250_evidence import (
    EvidenceChecklistStore,
    EvidenceInvalid,
    EvidenceNotFound,
)

router = APIRouter()


class EvidenceChecklistCreate(BaseModel):
    model_config = {"extra": "forbid"}

    reportLabel: str = Field(min_length=1, max_length=120)
    citationRefs: list[str] = Field(min_length=1, max_length=200)


class EvidenceItemPatch(BaseModel):
    model_config = {"extra": "forbid"}

    sourceRef: str | None = Field(default=None, min_length=1, max_length=300)
    versionId: str | None = Field(default=None, min_length=1, max_length=300)
    excerpt: str | None = Field(default=None, min_length=1, max_length=2000)


def _store(request: Request) -> EvidenceChecklistStore:
    return EvidenceChecklistStore(request.app.state.db)


def _error(status: int, kind: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"type": kind, "message": message}})


@router.post("/api/v1/evidence-checklists", status_code=201)
async def create_evidence_checklist(payload: EvidenceChecklistCreate, request: Request) -> Response:
    try:
        result = await _store(request).create_items(payload.reportLabel, payload.citationRefs)
    except EvidenceInvalid as exc:
        return _error(422, "evidence_invalid", str(exc))
    return JSONResponse(status_code=201, content=result)


@router.get("/api/v1/evidence-checklists/{report_label}")
async def get_evidence_checklist(report_label: str, request: Request) -> Response:
    try:
        result = await _store(request).get_report(report_label)
    except EvidenceInvalid as exc:
        return _error(422, "evidence_invalid", str(exc))
    except EvidenceNotFound:
        return _error(404, "evidence_not_found", "没有这个检查单。")
    return JSONResponse(result)


@router.patch("/api/v1/evidence-checklists/{report_label}/items/{citation_ref}")
async def patch_evidence_item(
    report_label: str, citation_ref: str, payload: EvidenceItemPatch, request: Request
) -> Response:
    if payload.sourceRef is None and payload.versionId is None and payload.excerpt is None:
        return _error(422, "evidence_invalid", "PATCH 至少提交一个要补齐的字段。")
    try:
        item = await _store(request).patch_item(
            report_label,
            citation_ref,
            source_ref=payload.sourceRef,
            version_id=payload.versionId,
            excerpt=payload.excerpt,
        )
    except EvidenceInvalid as exc:
        return _error(422, "evidence_invalid", str(exc))
    except EvidenceNotFound:
        return _error(404, "evidence_not_found", "检查单或引文项不存在。")
    return JSONResponse(item)
