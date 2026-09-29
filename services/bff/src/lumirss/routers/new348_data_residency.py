"""NEW-348 数据驻留说明路由。

- GET /api/v1/privacy/data-residency          成员只读（配置推导 + 管理员注释）
- GET /api/v1/admin/residency-notes           管理员读注释
- PUT /api/v1/admin/residency-notes           管理员写注释 {key, note}
- DELETE /api/v1/admin/residency-notes/{key}  管理员删注释
"""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.new348_data_residency import (
    ResidencyNoteInvalid,
    ResidencyNoteStore,
    build_residency_view,
)

router = APIRouter()


def _hostname_of(url: str) -> str | None:
    from lumirss.routers.privacy import _hostname_of

    return _hostname_of(url)


async def _require_user(request: Request) -> str | None:
    from lumirss.config import LumiSettings
    from lumirss.routers.auth import _current_user_id

    if LumiSettings().LUMIRSS_AUTH_MODE != "session":
        return None
    return await _current_user_id(request)


async def _hosts(request: Request) -> dict[str, Any]:
    from lumirss.backup import WebDavSettingsStore
    from lumirss.config import FreshRSSSettings, RssHubSettings

    db = request.app.state.db
    ai: dict[str, str] = {}
    try:
        from lumirss.ai_settings import AiSettingsStore

        ai = await AiSettingsStore(db).load()
    except Exception:  # noqa: BLE001 — 读不到 = 未配置
        ai = {}
    webdav_store = WebDavSettingsStore(db, request.app.state.secrets_store)
    webdav_doc = await webdav_store.load()
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
    return {
        "freshrss_host": _hostname_of(
            (freshrss.FRESHRSS_PUBLIC_URL if freshrss else "")
            or (freshrss.FRESHRSS_BASE_URL if freshrss else "")
        ),
        "rsshub_host": _hostname_of(
            str((rsshub.RSSHUB_BASE_URL if rsshub else "") or "")
        ),
        "ai_host": _hostname_of(ai.get("ai.base_url", "")),
        "webdav_host": _hostname_of(str(webdav_doc.get("serverUrl", ""))),
        "webdav_ready": webdav_store.configured(webdav_doc),
    }


@router.get("/api/v1/privacy/data-residency", response_model=None)
async def get_data_residency(request: Request) -> JSONResponse:
    user_id = await _require_user(request)
    if user_id is None:
        return JSONResponse(
            status_code=401,
            content={
                "error": {"type": "session_required", "message": "Login required."}
            },
            headers={"Cache-Control": "no-store"},
        )
    hosts = await _hosts(request)
    notes = await ResidencyNoteStore(request.app.state.control_db).all_notes()
    payload = build_residency_view(
        freshrss_host=hosts["freshrss_host"],
        rsshub_host=hosts["rsshub_host"],
        ai_host=hosts["ai_host"],
        webdav_host=hosts["webdav_host"],
        webdav_ready=hosts["webdav_ready"],
        notes=notes,
    )
    return JSONResponse(payload, headers={"Cache-Control": "no-store"})


class NoteBody(BaseModel):
    model_config = {"extra": "forbid"}

    key: str = Field(min_length=1, max_length=40)
    note: str = Field(min_length=1, max_length=500)


def _admin_denied() -> JSONResponse | None:
    return None


async def _require_admin(request: Request) -> dict[str, str] | None:
    from lumirss.user_scope import principal_of

    principal = principal_of(request.scope)
    if principal is None or principal.get("role") not in ("owner", "admin"):
        return None
    return principal


@router.get("/api/v1/admin/residency-notes", response_model=None)
async def list_residency_notes(request: Request) -> JSONResponse:
    admin = await _require_admin(request)
    if admin is None:
        return JSONResponse(
            status_code=403,
            content={"error": {"type": "forbidden", "message": "Administrator role required."}},
        )
    notes = await ResidencyNoteStore(request.app.state.control_db).all_notes()
    return JSONResponse({"items": [{"key": k, **v} for k, v in sorted(notes.items())]})


@router.put("/api/v1/admin/residency-notes", response_model=None)
async def put_residency_note(body: NoteBody, request: Request) -> JSONResponse:
    admin = await _require_admin(request)
    if admin is None:
        return JSONResponse(
            status_code=403,
            content={"error": {"type": "forbidden", "message": "Administrator role required."}},
        )
    try:
        saved = await ResidencyNoteStore(request.app.state.control_db).upsert(
            body.key, body.note, str(admin.get("user_id") or "admin")
        )
    except ResidencyNoteInvalid as exc:
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "note_invalid", "message": str(exc)}},
        )
    return JSONResponse(saved)


@router.delete("/api/v1/admin/residency-notes/{key}", response_model=None)
async def delete_residency_note(key: str, request: Request) -> JSONResponse:
    admin = await _require_admin(request)
    if admin is None:
        return JSONResponse(
            status_code=403,
            content={"error": {"type": "forbidden", "message": "Administrator role required."}},
        )
    deleted = await ResidencyNoteStore(request.app.state.control_db).delete(key)
    if not deleted:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "note_not_found", "message": "注释不存在。"}},
        )
    return JSONResponse({"key": key, "deleted": True})
