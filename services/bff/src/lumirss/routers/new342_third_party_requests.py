"""NEW-342 第三方请求清单路由。

- GET  /api/v1/privacy/third-party-requests            清单（配置推导）
- POST /api/v1/privacy/third-party-requests/{key}/toggle  可选请求开关
      （remote_images → 便携设置 readerImageMode；outbound_webhooks →
       暂停/恢复全部活跃订阅）；动作留痕（0265）。
"""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from lumirss.new342_third_party_requests import (
    OUTBOUND_WEBHOOKS_KEY,
    REMOTE_IMAGES_KEY,
    build_third_party_inventory,
    recent_optout_actions,
    record_optout_action,
)

router = APIRouter()

_TOGGLEABLE = {REMOTE_IMAGES_KEY, OUTBOUND_WEBHOOKS_KEY}


def _hostname_of(url: str) -> str | None:
    from lumirss.routers.privacy import _hostname_of

    return _hostname_of(url)


async def _require_user(request: Request) -> str | None:
    from lumirss.config import LumiSettings
    from lumirss.routers.auth import _current_user_id

    if LumiSettings().LUMIRSS_AUTH_MODE != "session":
        return None
    return await _current_user_id(request)


async def _config_hosts(request: Request) -> dict[str, Any]:
    """与 FIX-148 data-flows 同源的配置读取（本机，零网络）。"""
    from lumirss.backup import WebDavSettingsStore
    from lumirss.config import FreshRSSSettings, RssHubSettings
    from lumirss.mail_imap import load_imap_config

    db = request.app.state.db
    ai: dict[str, str] = {}
    try:
        from lumirss.ai_settings import AiSettingsStore

        ai = await AiSettingsStore(db).load()
    except Exception:  # noqa: BLE001 — 读不到 = 未配置
        ai = {}
    webdav_store = WebDavSettingsStore(db, request.app.state.secrets_store)
    webdav_doc = await webdav_store.load()
    imap = load_imap_config(request.app.state.secrets_store)
    # 未配置时 FreshRSSSettings 校验会抛 —— 如实按「未配置」处理
    #（与 FIX-148 data-flows 的诚实降级同一口径），绝不 500。
    try:
        freshrss = FreshRSSSettings()
    except Exception:  # noqa: BLE001 — 校验失败 = 未配置
        freshrss = None
    try:
        rsshub = RssHubSettings()
    except Exception:  # noqa: BLE001 — 校验失败 = 未配置
        rsshub = None
    ai_host = _hostname_of(ai.get("ai.base_url", ""))
    tts_host = None
    try:
        from lumirss.routers.privacy import _tts_provider_host

        tts_host = await _tts_provider_host(request)
    except Exception:  # noqa: BLE001 — 解析不出 = 未配置
        tts_host = None
    return {
        "freshrss_host": _hostname_of(
            (freshrss.FRESHRSS_PUBLIC_URL if freshrss else "")
            or (freshrss.FRESHRSS_BASE_URL if freshrss else "")
        ),
        "rsshub_host": _hostname_of(
            str((rsshub.RSSHUB_BASE_URL if rsshub else "") or "")
        ),
        "ai_host": ai_host,
        "libretranslate_host": _hostname_of(
            ai.get("translation.libretranslate_url", "")
        ),
        "tts_host": tts_host,
        "webdav_host": _hostname_of(str(webdav_doc.get("serverUrl", ""))),
        "webdav_ready": webdav_store.configured(webdav_doc),
        "imap_host": _hostname_of(str(getattr(imap, "host", "") or "")),
        "remote_images_hidden": False,  # 由路由按便携设置覆写
    }


class ToggleBody(BaseModel):
    model_config = {"extra": "forbid"}

    disabled: bool


@router.get("/api/v1/privacy/third-party-requests", response_model=None)
async def get_third_party_requests(request: Request) -> JSONResponse:
    user_id = await _require_user(request)
    if user_id is None:
        return JSONResponse(
            status_code=401,
            content={
                "error": {"type": "session_required", "message": "Login required."}
            },
            headers={"Cache-Control": "no-store"},
        )
    db = request.app.state.db
    hosts = await _config_hosts(request)
    portable: dict[str, Any] = {}
    try:
        from lumirss.app_settings import AppSettingsStore

        portable, _ = await AppSettingsStore(db).load()
        hosts["remote_images_hidden"] = portable.readerImageMode == "hidden"
    except Exception:  # noqa: BLE001 — 读不到按默认 all
        hosts["remote_images_hidden"] = False
    from lumirss.new308_outbound_subscriptions import OutboundSubscriptionStore
    from lumirss.new344_share_links import ShareLinkStore

    subs = await OutboundSubscriptionStore(db, request.app.state.secrets_store).list_subscriptions()
    webhook_hosts = sorted(
        {
            host
            for sub in subs
            if str(sub["state"]) == "active"
            for host in [_hostname_of(str(sub["target_url"]))]
            if host
        }
    )
    share_links = await ShareLinkStore(db).list_links()
    optouts = {
        REMOTE_IMAGES_KEY: bool(hosts.pop("remote_images_hidden")),
        OUTBOUND_WEBHOOKS_KEY: all(
            str(sub["state"]) != "active"
            for sub in subs
        ) and bool(subs),
    }
    payload = build_third_party_inventory(
        freshrss_host=hosts["freshrss_host"],
        rsshub_host=hosts["rsshub_host"],
        ai_host=hosts["ai_host"],
        libretranslate_host=hosts["libretranslate_host"],
        tts_host=hosts["tts_host"],
        webdav_host=hosts["webdav_host"],
        imap_host=hosts["imap_host"],
        remote_images_hidden=optouts[REMOTE_IMAGES_KEY],
        webhook_hosts=webhook_hosts,
        share_link_count=sum(
            1 for link in share_links if link["revokedAt"] is None
        ),
        optouts=optouts,
    )
    payload["recentActions"] = await recent_optout_actions(db)
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


@router.post(
    "/api/v1/privacy/third-party-requests/{key}/toggle", response_model=None
)
async def toggle_third_party_request(
    key: str, body: ToggleBody, request: Request
) -> JSONResponse:
    """可选请求的真实开关（不可关的项在清单里 optional=false）。"""
    user_id = await _require_user(request)
    if user_id is None:
        return JSONResponse(
            status_code=401,
            content={
                "error": {"type": "session_required", "message": "Login required."}
            },
            headers={"Cache-Control": "no-store"},
        )
    if key not in _TOGGLEABLE:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "type": "unknown_toggle",
                    "message": f"未知开关「{key}」；可开关：{'、'.join(sorted(_TOGGLEABLE))}。",
                }
            },
        )
    db = request.app.state.db
    detail = ""
    if key == REMOTE_IMAGES_KEY:
        from lumirss.app_settings import AppSettingsStore, PortableSettingsPatch

        await AppSettingsStore(db).save(
            PortableSettingsPatch(readerImageMode="hidden" if body.disabled else "all")
        )
        detail = (
            "文章远程图片已关闭（阅读器不再请求图片来源站）"
            if body.disabled
            else "文章远程图片已恢复显示"
        )
    else:
        from lumirss.new308_outbound_subscriptions import (
            OutboundSubscriptionStore,
        )

        out = OutboundSubscriptionStore(db, request.app.state.secrets_store)
        subs = await out.list_subscriptions()
        changed = 0
        for sub in subs:
            if str(sub["state"]) in ("active", "paused") and await out.set_state(
                int(sub["id"]), "paused" if body.disabled else "active"
            ):
                changed += 1
        detail = (
            f"已暂停 {changed} 条外发订阅（事件停发）"
            if body.disabled
            else f"已恢复 {changed} 条外发订阅"
        )
    await record_optout_action(db, key, "off" if body.disabled else "on")
    return JSONResponse(
        {"key": key, "disabled": body.disabled, "detail": detail},
        headers={"Cache-Control": "no-store"},
    )
