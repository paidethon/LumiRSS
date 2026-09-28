"""NEW-208 来源认证到期提醒路由（只存提醒元数据，绝不存凭据正文）。"""

from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.new208_credential import (
    DEFAULT_UPCOMING_DAYS,
    MAX_UPCOMING_DAYS,
    UPDATE_ENTRY_FRESHRSS,
    UPDATE_ENTRY_RSSHUB,
    CredentialReminderInvalid,
    CredentialReminderNotFound,
    CredentialReminderStore,
    classify_expiry,
    parse_iso_date,
)

router = APIRouter()


def _store(request: Request) -> CredentialReminderStore:
    return CredentialReminderStore(request.app.state.db)


def _invalid(message: str) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "error": {"type": "invalid_credential_reminder", "message": message}
        },
    )


def _update_entry(feed_url: str) -> str:
    """更新引导：RSSHub 形态的来源走凭据库，其余走 FreshRSS 原生界面。"""
    import urllib.parse

    from lumirss.rsshub import match_route_path

    try:
        path = urllib.parse.urlsplit(feed_url).path
    except ValueError:
        return UPDATE_ENTRY_FRESHRSS
    return UPDATE_ENTRY_RSSHUB if match_route_path(path) else UPDATE_ENTRY_FRESHRSS


class ReminderCreate(BaseModel):
    """POST /api/v1/new208/reminders body。

    刻意**没有**凭据值字段（extra=forbid）——凭据正文属于既有
    write-only 边界，本端点只登记「什么时候到期」。"""

    model_config = {"extra": "forbid"}

    feedUrl: str = Field(min_length=1)
    expiresOn: str = Field(min_length=1)
    sourceLabel: str | None = None
    note: str | None = None
    """有界自由文本（≤200）——写给「找谁续/怎么续」的元信息，
    不是凭据存放处。"""


class ReminderRenew(BaseModel):
    """POST /api/v1/new208/reminders/{id}/renew body（只换到期日）。"""

    model_config = {"extra": "forbid"}

    expiresOn: str = Field(min_length=1)


class ReminderView(BaseModel):
    id: str
    feedUrl: str
    sourceLabel: str | None
    expiresOn: str
    note: str | None
    status: str
    renewedCount: int
    createdAt: str
    updatedAt: str
    bucket: str | None = None
    """overdue | due_soon | later（列表响应携带；today 可注入）。"""
    updateEntry: str | None = None
    """受控更新入口坐标（rsshub-credentials | freshrss-native）。"""


class ReminderList(BaseModel):
    items: list[ReminderView]
    today: str
    note: str


_REMINDER_NOTE = (
    "只登记到期提醒，不存储、不显示凭据正文；更新凭据请走受控入口"
    "（RSSHub 凭据库 / FreshRSS 原生界面）。"
)


@router.post("/api/v1/new208/reminders", response_model=ReminderView, status_code=201)
async def create_reminder(payload: ReminderCreate, request: Request) -> Any:
    """登记来源访问凭据的到期日（提醒元数据；无凭据字段可填）。"""
    try:
        expires_on = parse_iso_date(payload.expiresOn)
        return await _store(request).create(
            feed_url=payload.feedUrl,
            expires_on=expires_on,
            source_label=payload.sourceLabel,
            note=payload.note,
        )
    except CredentialReminderInvalid as exc:
        return _invalid(str(exc))


@router.get("/api/v1/new208/reminders", response_model=ReminderList)
async def list_reminders(
    request: Request,
    includeDismissed: bool = False,
    upcomingDays: int = Query(default=DEFAULT_UPCOMING_DAYS, ge=1, le=MAX_UPCOMING_DAYS),
    today: str | None = Query(default=None),
) -> ReminderList:
    """提醒列表（按到期日升序；带 overdue/due_soon/later 分桶）。"""
    from datetime import UTC, datetime

    anchor = today or datetime.now(UTC).date().isoformat()
    if today is not None:
        try:
            parse_iso_date(today, "today")
        except CredentialReminderInvalid as exc:
            return _invalid(str(exc))
    items = await _store(request).list_reminders(include_dismissed=includeDismissed)
    views = []
    for item in items:
        bucket = (
            classify_expiry(item["expiresOn"], today=anchor, upcoming_days=upcomingDays)
            if item["status"] == "active"
            else None
        )
        views.append(
            ReminderView(
                **item,
                bucket=bucket,
                updateEntry=_update_entry(item["feedUrl"]),
            )
        )
    return ReminderList(items=views, today=anchor, note=_REMINDER_NOTE)


@router.post("/api/v1/new208/reminders/{reminder_id}/renew", response_model=ReminderView)
async def renew_reminder(reminder_id: str, payload: ReminderRenew, request: Request) -> Any:
    """续期：更新到期日（dismissed 行重新激活；计数 +1）。"""
    try:
        expires_on = parse_iso_date(payload.expiresOn)
    except CredentialReminderInvalid as exc:
        return _invalid(str(exc))
    try:
        renewed = await _store(request).renew(reminder_id, expires_on)
    except CredentialReminderNotFound:
        return _not_found()
    renewed["updateEntry"] = _update_entry(renewed["feedUrl"])
    return ReminderView(**renewed)


def _not_found() -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={
            "error": {
                "type": "credential_reminder_not_found",
                "message": "提醒不存在。",
            }
        },
    )


@router.post("/api/v1/new208/reminders/{reminder_id}/dismiss", response_model=ReminderView)
async def dismiss_reminder(reminder_id: str, request: Request, dismissed: bool = True) -> Any:
    """dismiss / 重新激活（set 语义；dismissed=true 静默，false 复原）。"""
    try:
        row = await _store(request).set_dismissed(reminder_id, dismissed)
    except CredentialReminderNotFound:
        return _not_found()
    row["updateEntry"] = _update_entry(row["feedUrl"])
    return ReminderView(**row)
