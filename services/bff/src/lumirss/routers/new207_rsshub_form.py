"""NEW-207 RSSHub 参数表单路由（schema → 离线校验 → 验证后添加）。"""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.adapters.freshrss_control import SubscriptionConflict
from lumirss.config import RssHubSettings
from lumirss.deps import _get_control_adapter
from lumirss.new207_rsshub_form import (
    RssHubFormInvalid,
    RssHubFormStore,
    form_schema,
    validate_form,
)
from lumirss.rsshub import _CATALOG_BY_ID

router = APIRouter()


def _route(route_id: str):
    return _CATALOG_BY_ID.get(route_id)


def _not_found(route_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={
            "error": {
                "type": "rsshub_route_not_found",
                "message": f"路由目录中没有「{route_id}」。",
            }
        },
    )


class FormValidateRequest(BaseModel):
    """POST /api/v1/new207/rsshub-form/{routeId}/validate body（离线）。"""

    model_config = {"extra": "forbid"}

    params: dict[str, str] = Field(default_factory=dict)


class FormApplyRequest(BaseModel):
    """POST /api/v1/new207/rsshub-form/{routeId}/apply body（验证后添加）。"""

    model_config = {"extra": "forbid"}

    params: dict[str, str] = Field(default_factory=dict)
    title: str | None = Field(default=None, max_length=300)
    confirmed: bool = False
    """显式确认添加（缺席/false → 422 confirmation_required）。"""


@router.get("/api/v1/new207/rsshub-form/{route_id}")
async def get_form_schema(route_id: str) -> Any:
    """表单 schema（依据 Lumi 自有路由目录；离线零网络）。"""
    route = _route(route_id)
    if route is None:
        return _not_found(route_id)
    return {**form_schema(route), "note": "填表后先验证（预览样本走既有 rsshub/preview），确认后添加。"}


@router.post("/api/v1/new207/rsshub-form/{route_id}/validate")
async def validate_form_params(route_id: str, payload: FormValidateRequest) -> Any:
    """逐参数校验（required/pattern/unknown；离线，不取样本）。"""
    route = _route(route_id)
    if route is None:
        return _not_found(route_id)
    try:
        return validate_form(route, payload.params)
    except RssHubFormInvalid as exc:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "invalid_rsshub_form", "message": str(exc)}},
        )


@router.post("/api/v1/new207/rsshub-form/{route_id}/apply", status_code=201)
async def apply_form(route_id: str, payload: FormApplyRequest, request: Request) -> Any:
    """验证后添加：校验 → 生成订阅地址（服务端拼装）→ 确认即订阅。

    - 表单未过校验 → 422 rsshub_form_invalid（errors 逐参数）；
    - 未显式 confirmed → 422 confirmation_required；
    - RSSHUB base 未配置 → 422 rsshub_not_configured（服务端配置缺失）；
    - 已订阅同 URL → 409 already_subscribed（上游冲突也归并到这里）。"""
    route = _route(route_id)
    if route is None:
        return _not_found(route_id)
    if not payload.confirmed:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "type": "confirmation_required",
                    "message": "必须显式 confirmed=true 才会添加订阅。",
                }
            },
        )
    try:
        result = validate_form(route, payload.params)
    except RssHubFormInvalid as exc:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "invalid_rsshub_form", "message": str(exc)}},
        )
    if not result["valid"]:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "type": "rsshub_form_invalid",
                    "message": "表单校验未通过，请按逐参数错误修正。",
                    "errors": result["errors"],
                }
            },
        )
    try:
        settings = RssHubSettings()
        if not settings.RSSHUB_BASE_URL:
            raise RssHubFormInvalid("RSSHUB_BASE_URL is not configured.")
    except RssHubFormInvalid as exc:
        return JSONResponse(
            status_code=422,
            content={
                "error": {"type": "rsshub_not_configured", "message": str(exc)}
            },
        )
    feed_url = f"{settings.freshrss_base_url}{result['generatedPath']}"
    control = _get_control_adapter(request)
    try:
        subscriptions = await control.list_subscriptions()
    except Exception as exc:  # noqa: BLE001 — 上游退化如实上报
        return JSONResponse(
            status_code=502,
            content={"error": {"type": "upstream_unavailable", "message": str(exc)}},
        )
    if any(sub.feed_url == feed_url for sub in subscriptions):
        return JSONResponse(
            status_code=409,
            content={
                "error": {
                    "type": "already_subscribed",
                    "message": "该生成地址已在订阅清单中，无需重复添加。",
                    "feedUrl": feed_url,
                }
            },
        )
    try:
        created = await control.subscribe(feed_url, category_id=None, title=payload.title)
    except SubscriptionConflict as exc:
        return JSONResponse(
            status_code=409,
            content={"error": {"type": "already_subscribed", "message": str(exc)}},
        )
    form_use = await RssHubFormStore(request.app.state.db).record(
        route_id=route_id, params=payload.params, feed_url=feed_url
    )
    return {
        "subscription": {
            "streamId": str(created.stream_id),
            "subscriptionRef": getattr(created, "subscription_ref", None),
            "feedUrl": feed_url,
            "title": getattr(created, "title", None),
        },
        "formUse": form_use,
        "note": "已按表单生成地址并订阅；参数台账为脱敏形态。",
    }


@router.get("/api/v1/new207/rsshub-form/{route_id}/uses")
async def list_form_uses(route_id: str, request: Request) -> dict[str, Any]:
    """该路由的添加台账（脱敏参数；新→旧，≤50）。"""
    uses = await RssHubFormStore(request.app.state.db).list_uses()
    return {"items": [use for use in uses if use["routeId"] == route_id]}
