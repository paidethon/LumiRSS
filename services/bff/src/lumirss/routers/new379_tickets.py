"""NEW-379 工单路由。

成员（会话身份为唯一主语）：
- POST /api/v1/support/tickets              提交；
- GET  /api/v1/support/tickets              自己的工单列表（无正文）；
- GET  /api/v1/support/tickets/{id}         自己的工单详情（含回复线）；
- POST /api/v1/support/tickets/{id}/replies 自己追加回复。

管理员（admin guard）：
- GET  /api/v1/admin/tickets?status=        全实例工单（列表无正文；
      正文只在详情——工单正文是用户显式提交的求助内容，不是私密正文）；
- GET  /api/v1/admin/tickets/{id}           详情；
- POST /api/v1/admin/tickets/{id}/assign    指派给 owner/admin；
- POST /api/v1/admin/tickets/{id}/replies   管理员回复（→ answered）；
- POST /api/v1/admin/tickets/{id}/close     关闭（终态；重复 409）。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.new379_tickets import (
    TicketInvalid,
    TicketNotFound,
    TicketStateInvalid,
    assign_ticket,
    close_ticket,
    create_ticket,
    get_ticket,
    list_tickets,
    reply_ticket,
    ticket_counts,
)
from lumirss.routers.admin import _NO_STORE, _require_admin

router = APIRouter()


class TicketBody(BaseModel):
    model_config = {"extra": "forbid"}

    subject: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=2000)


class AssignBody(BaseModel):
    model_config = {"extra": "forbid"}

    adminUserId: str = Field(min_length=1, max_length=64)


class ReplyBody(BaseModel):
    model_config = {"extra": "forbid"}

    body: str = Field(min_length=1, max_length=2000)


def _invalid(exc: TicketInvalid) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": {"type": "invalid_ticket_payload", "message": str(exc)}},
        headers=_NO_STORE,
    )


def _not_found() -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"error": {"type": "ticket_not_found", "message": "工单不存在。"}},
        headers=_NO_STORE,
    )


def _conflict() -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={"error": {"type": "ticket_state", "message": "工单状态不允许该操作。"}},
        headers=_NO_STORE,
    )


async def _current_user(request: Request) -> tuple[str | None, str]:
    from lumirss.config import LumiSettings
    from lumirss.routers.auth import _current_user_id as _session_user

    if LumiSettings().LUMIRSS_AUTH_MODE != "session":
        return None, "member"
    user_id = await _session_user(request)
    return user_id, "member"


async def _admin_or_error(request: Request) -> JSONResponse | dict[str, str]:
    principal = await _require_admin(request)
    if principal is None:
        return JSONResponse(
            status_code=403,
            content={"error": {"type": "forbidden", "message": "需要管理员角色。"}},
            headers=_NO_STORE,
        )
    return principal


# ---- 成员面 ---------------------------------------------------------------


@router.post("/api/v1/support/tickets", response_model=None)
async def post_ticket(payload: TicketBody, request: Request) -> JSONResponse:
    user_id, _role = await _current_user(request)
    if user_id is None:
        return JSONResponse(
            status_code=401,
            content={"error": {"type": "session_required", "message": "Login required."}},
            headers=_NO_STORE,
        )
    try:
        result = await create_ticket(
            request.app.state.control_db,
            submitted_by=user_id,
            subject=payload.subject,
            body=payload.body,
        )
    except TicketInvalid as exc:
        return _invalid(exc)
    return JSONResponse(result, status_code=201, headers=_NO_STORE)


@router.get("/api/v1/support/tickets", response_model=None)
async def get_my_tickets(request: Request, status: str | None = None) -> JSONResponse:
    user_id, _role = await _current_user(request)
    if user_id is None:
        return JSONResponse(
            status_code=401,
            content={"error": {"type": "session_required", "message": "Login required."}},
            headers=_NO_STORE,
        )
    try:
        items = await list_tickets(
            request.app.state.control_db, submitted_by=user_id, status=status
        )
    except TicketInvalid as exc:
        return _invalid(exc)
    return JSONResponse({"items": items}, headers=_NO_STORE)


@router.get("/api/v1/support/tickets/{ticket_id}", response_model=None)
async def get_my_ticket(ticket_id: str, request: Request) -> JSONResponse:
    user_id, _role = await _current_user(request)
    if user_id is None:
        return JSONResponse(
            status_code=401,
            content={"error": {"type": "session_required", "message": "Login required."}},
            headers=_NO_STORE,
        )
    ticket = await get_ticket(
        request.app.state.control_db, ticket_id=ticket_id, submitted_by=user_id
    )
    if ticket is None:
        return _not_found()
    return JSONResponse(ticket, headers=_NO_STORE)


@router.post("/api/v1/support/tickets/{ticket_id}/replies", response_model=None)
async def post_my_reply(ticket_id: str, payload: ReplyBody, request: Request) -> JSONResponse:
    user_id, role = await _current_user(request)
    if user_id is None:
        return JSONResponse(
            status_code=401,
            content={"error": {"type": "session_required", "message": "Login required."}},
            headers=_NO_STORE,
        )
    try:
        result = await reply_ticket(
            request.app.state.control_db,
            ticket_id=ticket_id,
            author_id=user_id,
            author_role=role,
            body=payload.body,
            as_submitter=user_id,
        )
    except TicketInvalid as exc:
        return _invalid(exc)
    except TicketNotFound:
        return _not_found()
    except TicketStateInvalid:
        return _conflict()
    return JSONResponse(result, headers=_NO_STORE)


# ---- 管理面 ---------------------------------------------------------------


@router.get("/api/v1/admin/tickets", response_model=None)
async def admin_list_tickets(request: Request, status: str | None = None) -> JSONResponse:
    principal = await _admin_or_error(request)
    if isinstance(principal, JSONResponse):
        return principal
    try:
        items = await list_tickets(request.app.state.control_db, status=status)
    except TicketInvalid as exc:
        return _invalid(exc)
    counts = await ticket_counts(request.app.state.control_db)
    return JSONResponse({"items": items, "counts": counts}, headers=_NO_STORE)


@router.get("/api/v1/admin/tickets/{ticket_id}", response_model=None)
async def admin_get_ticket(ticket_id: str, request: Request) -> JSONResponse:
    principal = await _admin_or_error(request)
    if isinstance(principal, JSONResponse):
        return principal
    ticket = await get_ticket(request.app.state.control_db, ticket_id=ticket_id)
    if ticket is None:
        return _not_found()
    return JSONResponse(ticket, headers=_NO_STORE)


@router.post("/api/v1/admin/tickets/{ticket_id}/assign", response_model=None)
async def admin_assign(ticket_id: str, payload: AssignBody, request: Request) -> JSONResponse:
    principal = await _admin_or_error(request)
    if isinstance(principal, JSONResponse):
        return principal
    accounts = request.app.state.accounts
    assignee = await accounts.get_user(payload.adminUserId)
    if assignee is None or assignee.get("role") not in ("owner", "admin"):
        return JSONResponse(
            status_code=422,
            content={"error": {"type": "invalid_assignee", "message": "处理人必须是 owner/admin。"}},
            headers=_NO_STORE,
        )
    try:
        result = await assign_ticket(
            request.app.state.control_db,
            ticket_id=ticket_id,
            assignee_id=payload.adminUserId,
            by=principal["user_id"],
        )
    except TicketNotFound:
        return _not_found()
    except TicketStateInvalid:
        return _conflict()

    await accounts.audit(
        actor=principal["user_id"],
        action="ticket_assigned",
        object_type="ticket",
        object_id=ticket_id,
        detail=f"assignee={payload.adminUserId}",
    )
    return JSONResponse(result, headers=_NO_STORE)


@router.post("/api/v1/admin/tickets/{ticket_id}/replies", response_model=None)
async def admin_reply(ticket_id: str, payload: ReplyBody, request: Request) -> JSONResponse:
    principal = await _admin_or_error(request)
    if isinstance(principal, JSONResponse):
        return principal
    try:
        result = await reply_ticket(
            request.app.state.control_db,
            ticket_id=ticket_id,
            author_id=principal["user_id"],
            author_role=str(principal.get("role", "admin")),
            body=payload.body,
        )
    except TicketInvalid as exc:
        return _invalid(exc)
    except TicketNotFound:
        return _not_found()
    except TicketStateInvalid:
        return _conflict()
    return JSONResponse(result, headers=_NO_STORE)


@router.post("/api/v1/admin/tickets/{ticket_id}/close", response_model=None)
async def admin_close(ticket_id: str, request: Request) -> JSONResponse:
    principal = await _admin_or_error(request)
    if isinstance(principal, JSONResponse):
        return principal
    try:
        result = await close_ticket(
            request.app.state.control_db, ticket_id=ticket_id, by=principal["user_id"]
        )
    except TicketNotFound:
        return _not_found()
    except TicketStateInvalid:
        return _conflict()
    from lumirss.accounts_store import AccountsStore

    await AccountsStore(request.app.state.control_db).audit(
        actor=principal["user_id"], action="ticket_closed", object_type="ticket", object_id=ticket_id
    )
    return JSONResponse(result, headers=_NO_STORE)
