"""NEW-227 章节级阅读计划路由。

稳定错误信封：invalid_section_plan / section_plan_not_found /
section_plan_section_not_found / section_plan_conflict。
"""

from typing import Any

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from lumirss.new227_section_plans import (
    PlanConflict,
    PlanInvalid,
    PlanNotFound,
    PlanSectionNotFound,
    SectionPlanStore,
)

router = APIRouter()


def _store(request: Request) -> SectionPlanStore:
    return SectionPlanStore(request.app.state.db)


class SectionInput(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    sessionNo: int | None = Field(default=None, ge=1, le=52)


class SectionPlanCreateRequest(BaseModel):
    model_config = {"extra": "forbid"}

    itemRef: str
    sections: list[SectionInput] = Field(min_length=1, max_length=100)


class SectionView(BaseModel):
    id: str
    position: int
    label: str
    sessionNo: int | None = None
    status: str
    doneAt: str | None = None


class SectionProgressView(BaseModel):
    totalSections: int
    doneSections: int
    pendingSections: int
    bySession: list[dict[str, Any]]


class SectionPlanView(BaseModel):
    id: str
    itemRef: str
    createdAt: str
    updatedAt: str
    sections: list[SectionView]
    progress: SectionProgressView


class SectionPlanCreateResponse(SectionPlanView):
    pass


class SectionUpdateRequest(BaseModel):
    model_config = {"extra": "forbid"}

    label: str | None = Field(default=None, min_length=1, max_length=120)
    sessionNo: int | None = Field(default=None, ge=1, le=52)
    clearSession: bool = False


class SectionDoneRequest(BaseModel):
    model_config = {"extra": "forbid"}

    done: bool


@router.post("/api/v1/reading/section-plans", response_model=SectionPlanCreateResponse, status_code=201)
async def create_section_plan(
    payload: SectionPlanCreateRequest, request: Request
) -> SectionPlanCreateResponse:
    """为长文建章节计划（一篇一个；已有 → 409 section_plan_conflict）。"""
    view = await _store(request).create_plan(
        payload.itemRef,
        [section.model_dump() for section in payload.sections],
    )
    return SectionPlanCreateResponse(**view)


@router.get("/api/v1/reading/section-plans", response_model=SectionPlanView)
async def get_section_plan(request: Request, itemRef: str) -> SectionPlanView:
    """计划视图（章节 + 整数进度 + 分 session 桶）。"""
    return SectionPlanView(**await _store(request).get_plan(itemRef))


@router.delete("/api/v1/reading/section-plans", status_code=204)
async def delete_section_plan(request: Request, itemRef: str) -> Response:
    """删除计划（含全部章节行；用户显式动作）。"""
    await _store(request).delete_plan(itemRef)
    return Response(status_code=204)


@router.patch("/api/v1/reading/section-plan-sections/{section_id}", response_model=SectionView)
async def update_plan_section(
    section_id: str, payload: SectionUpdateRequest, request: Request
) -> SectionView:
    """改章节标签 / 分配到某一次阅读（clearSession=true 清除分配）。"""
    view = await _store(request).update_section(
        section_id,
        label=payload.label,
        session_no=payload.sessionNo,
        clear_session=payload.clearSession,
    )
    return SectionView(**view)


@router.post(
    "/api/v1/reading/section-plan-sections/{section_id}/done", response_model=SectionView
)
async def set_plan_section_done(
    section_id: str, payload: SectionDoneRequest, request: Request
) -> SectionView:
    """章节完成（set 语义）——「每次结束保存完成章节」。"""
    view = await _store(request).set_section_done(section_id, payload.done)
    return SectionView(**view)


__all__ = ["router", "PlanConflict", "PlanInvalid", "PlanNotFound", "PlanSectionNotFound"]
