"""NEW-281 个人简报编排台路由 — 候选摘要卡 / 期次 CRUD / 确认。

- GET    /api/v1/briefings/candidates?from&to&feedUrl  → 摘要卡（附
           「已在哪几期刊过」= 282 去重预检的数据源）
- POST   /api/v1/briefings                              → 建草稿期次
- GET    /api/v1/briefings                              → 期次列表
- GET    /api/v1/briefings/{id}                         → 期次详情
- PATCH  /api/v1/briefings/{id}                         → 编辑草稿（整稿替换）
- POST   /api/v1/briefings/{id}/confirm                 → 确认（draft→confirmed）
- DELETE /api/v1/briefings/{id}                         → 删草稿（确认稿不可删）
"""

from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from lumirss.new281_briefings import (
    BriefingInvalid,
    BriefingNotFound,
    BriefingStateConflict,
    BriefingStore,
    DupApprovalRequired,
    LateEntryRejected,
)

router = APIRouter()


class BriefingItemIn(BaseModel):
    model_config = {"extra": "forbid"}

    entryRef: str
    sectionKey: str
    itemId: str = ""
    title: str = ""
    feedTitle: str = ""
    url: str = ""
    publishedAt: str = ""
    excerpt: str = ""
    provenance: str = "manual"
    pullBack: bool = False
    dupDecision: str | None = None
    card: dict[str, Any] | None = None


class BriefingCreateBody(BaseModel):
    model_config = {"extra": "forbid"}

    title: str
    rangeFrom: str = ""
    rangeTo: str = ""
    sections: list[dict[str, str]]
    items: list[BriefingItemIn]


class BriefingPatchBody(BaseModel):
    model_config = {"extra": "forbid"}

    title: str | None = None
    sections: list[dict[str, str]] | None = None
    items: list[BriefingItemIn] | None = None


def _error(status: int, error_type: str, message: str, **extra: Any) -> JSONResponse:
    content: dict[str, Any] = {"error": {"type": error_type, "message": message}}
    content["error"].update(extra)
    return JSONResponse(status_code=status, content=content)


def _store(request: Request) -> BriefingStore:
    return BriefingStore(request.app.state.db)


def _item_payload(item: BriefingItemIn) -> dict[str, Any]:
    data = item.model_dump()
    if data["dupDecision"] is None:
        data.pop("dupDecision")
    return data


@router.get("/api/v1/briefings/candidates")
async def get_candidates(
    request: Request,
    range_from: str = Query("", alias="from"),
    to: str = "",
    feedUrl: str = "",
) -> Response:
    try:
        cards = await _store(request).candidates(
            range_from, to, feed_url=feedUrl or None
        )
    except BriefingInvalid as exc:
        return _error(422, "invalid_briefing_payload", str(exc))
    return JSONResponse({"candidates": cards, "count": len(cards)})


# 282 后续清单（静态路由必须先于 {issue_id} 声明）。
@router.get("/api/v1/briefings/followups")
async def get_followups(request: Request) -> Response:
    rows = await _store(request).followups()
    return JSONResponse({"followups": rows, "count": len(rows)})


@router.post("/api/v1/briefings")
async def create_briefing(payload: BriefingCreateBody, request: Request) -> Response:
    from lumirss.new283_window import BriefingWindowStore

    # 283：配置了截稿窗口时，迟到条目必须显式 pullBack（store 层拦截）。
    window = await BriefingWindowStore(request.app.state.db).get()
    try:
        issue = await _store(request).create_issue(
            title=payload.title,
            range_from=payload.rangeFrom,
            range_to=payload.rangeTo,
            sections=payload.sections,
            items=[_item_payload(i) for i in payload.items],
            cutoff_utc=str(window["cutoffUtc"]) if window else None,
        )
    except DupApprovalRequired as exc:
        return _error(
            409,
            "briefing_dup_approval_required",
            str(exc),
            duplicates=exc.duplicates,
        )
    except LateEntryRejected as exc:
        return _error(
            422,
            "briefing_late_entry",
            str(exc),
            entryRefs=exc.refs,
        )
    except BriefingInvalid as exc:
        return _error(422, "invalid_briefing_payload", str(exc))
    return JSONResponse(issue, status_code=201)


@router.get("/api/v1/briefings")
async def list_briefings(request: Request, limit: int = 50) -> Response:
    issues = await _store(request).list_issues(limit=limit)
    return JSONResponse({"issues": issues, "count": len(issues)})


@router.get("/api/v1/briefings/{issue_id}")
async def get_briefing(issue_id: str, request: Request) -> Response:
    try:
        return JSONResponse(await _store(request).get_issue(issue_id))
    except BriefingNotFound as exc:
        return _error(404, "briefing_not_found", str(exc))


@router.patch("/api/v1/briefings/{issue_id}")
async def patch_briefing(
    issue_id: str, payload: BriefingPatchBody, request: Request
) -> Response:
    try:
        issue = await _store(request).update_draft(
            issue_id,
            title=payload.title,
            sections=payload.sections,
            items=(
                [_item_payload(i) for i in payload.items]
                if payload.items is not None
                else None
            ),
        )
    except BriefingStateConflict as exc:
        return _error(409, "briefing_confirmed", str(exc))
    except BriefingInvalid as exc:
        return _error(422, "invalid_briefing_payload", str(exc))
    except BriefingNotFound as exc:
        return _error(404, "briefing_not_found", str(exc))
    return JSONResponse(issue)


@router.post("/api/v1/briefings/{issue_id}/confirm")
async def confirm_briefing(issue_id: str, request: Request) -> Response:
    try:
        issue = await _store(request).confirm_issue(issue_id)
    except BriefingStateConflict as exc:
        return _error(409, "briefing_state_conflict", str(exc))
    except BriefingInvalid as exc:
        return _error(422, "invalid_briefing_payload", str(exc))
    except BriefingNotFound as exc:
        return _error(404, "briefing_not_found", str(exc))
    return JSONResponse(issue)


@router.delete("/api/v1/briefings/{issue_id}")
async def delete_briefing(issue_id: str, request: Request) -> Response:
    try:
        await _store(request).delete_draft(issue_id)
    except BriefingStateConflict as exc:
        return _error(409, "briefing_confirmed", str(exc))
    except BriefingNotFound as exc:
        return _error(404, "briefing_not_found", str(exc))
    return Response(status_code=204)
