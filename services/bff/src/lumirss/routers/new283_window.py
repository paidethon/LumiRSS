"""NEW-283 简报截稿窗口路由 — 时区化窗口配置 + 周期生成入口。

- PUT    /api/v1/briefings/window  {timezone,cutoffTime,periodDays} → 200
- GET    /api/v1/briefings/window  → 现配置 + 换算好的 UTC 边界（未配置
           返回 configured=false，绝不编造边界）
- DELETE /api/v1/briefings/window  → 204（清除配置）
- POST   /api/v1/briefings/generate {recipeId?|sections?|from?,to?} →
           按窗口/显式范围 + 配方规则生成草稿；失败 → 422 诊断体
           （stage + missing，见 NEW-284；诊断已落库）。

注意：本路由的静态路径必须先于 new281 的 /{issue_id} 注册（main.py
按此顺序 include），否则 'window'/'generate' 会被期次路由吞掉。
"""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from lumirss.new281_briefings import BriefingInvalid, BriefingStore
from lumirss.new283_window import BriefingWindowStore
from lumirss.new284_diagnostics import (
    AttemptStore,
    DiagnosisFailure,
    generate_issue,
)
from lumirss.new286_recipes import RecipeNotFound, RecipeStore

router = APIRouter()


class WindowBody(BaseModel):
    model_config = {"extra": "forbid"}

    timezone: str
    cutoffTime: str
    periodDays: int


class GenerateBody(BaseModel):
    model_config = {"extra": "forbid"}

    recipeId: str | None = None
    sections: list[dict[str, Any]] | None = None
    rangeFrom: str | None = None
    rangeTo: str | None = None


def _error(status: int, error_type: str, message: str, **extra: Any) -> JSONResponse:
    content: dict[str, Any] = {"error": {"type": error_type, "message": message}}
    content["error"].update(extra)
    return JSONResponse(status_code=status, content=content)


@router.put("/api/v1/briefings/window")
async def put_window(payload: WindowBody, request: Request) -> Response:
    try:
        window = await BriefingWindowStore(request.app.state.db).put(
            timezone=payload.timezone,
            cutoff_time=payload.cutoffTime,
            period_days=payload.periodDays,
        )
    except BriefingInvalid as exc:
        return _error(422, "invalid_window_payload", str(exc))
    return JSONResponse(window)


@router.get("/api/v1/briefings/window")
async def get_window(request: Request) -> Response:
    window = await BriefingWindowStore(request.app.state.db).get()
    if window is None:
        return JSONResponse(
            {
                "configured": False,
                "honestyNote": "尚未配置截稿窗口；生成周期简报前必须显式给出时区与截止点。",
            }
        )
    return JSONResponse({"configured": True, **window})


@router.delete("/api/v1/briefings/window")
async def delete_window(request: Request) -> Response:
    deleted = await BriefingWindowStore(request.app.state.db).delete()
    if not deleted:
        return _error(404, "window_not_found", "尚未配置截稿窗口。")
    return Response(status_code=204)


@router.post("/api/v1/briefings/generate")
async def post_generate(payload: GenerateBody, request: Request) -> Response:
    db = request.app.state.db
    sections: list[dict[str, Any]] | None = payload.sections
    if payload.recipeId:
        try:
            recipe = await RecipeStore(db).get(payload.recipeId)
        except RecipeNotFound as exc:
            return _error(404, "recipe_not_found", str(exc))
        sections = recipe["sections"]
    try:
        result = await generate_issue(
            db,
            BriefingStore(db),
            BriefingWindowStore(db),
            AttemptStore(db),
            range_from=payload.rangeFrom,
            range_to=payload.rangeTo,
            sections=sections
            and [
                {
                    "key": s.get("key"),
                    "label": s.get("label") or s.get("key"),
                    "rule": s.get("rule", "recent"),
                    "budget": s.get("budget", 400),
                    "feedUrl": s.get("feedUrl") or "",
                }
                for s in sections
            ],
        )
    except DiagnosisFailure as exc:
        return _error(
            422,
            "briefing_inputs_missing",
            exc.detail,
            stage=exc.stage,
            missing=exc.missing,
            attemptId=exc.attempt["id"],
        )
    except BriefingInvalid as exc:
        return _error(422, "invalid_briefing_payload", str(exc))
    return JSONResponse(
        {
            "issue": result["issue"],
            "excludedLate": result["excludedLate"],
            "inputs": result["inputs"],
        },
        status_code=201,
    )
