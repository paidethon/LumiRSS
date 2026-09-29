"""NEW-236 批注回复提醒路由 — 显式共享 / 回复 / 收件人提醒箱。

- POST   /api/v1/annotations/{annotation_id}/share {withUsername}
         owner 显式共享批注（快照上下文）；不能共享给自己；收件人
         必须是真实账户；私人批注绝不自动共享（无此路由即无共享）。
- DELETE /api/v1/annotations/{annotation_id}/share/{thread_id}
         owner 撤销共享（串与回复删除）。
- GET    /api/v1/annotation-replies            收件人提醒箱（默认不含已关闭）。
- GET    /api/v1/annotation-replies/{id}       原上下文 + 回复（收件人查看即清未读）。
- POST   /api/v1/annotation-replies/{id}/replies {body}
- POST   /api/v1/annotation-replies/{id}/dismiss  收件人关闭该串提醒。
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from lumirss.annotation_store import AnnotationStore
from lumirss.new236_annotation_replies import (
    ShareThreadForbidden,
    ShareThreadFull,
    ShareThreadNotFound,
    ShareThreadStore,
)
from lumirss.user_scope import current_user_id, require_user_id

router = APIRouter()


class ShareCreate(BaseModel):
    model_config = {"extra": "forbid"}

    withUsername: str = Field(min_length=1, max_length=100)


class ReplyCreate(BaseModel):
    model_config = {"extra": "forbid"}

    body: str = Field(min_length=1, max_length=2000)


def _threads(request: Request) -> ShareThreadStore:
    return ShareThreadStore(request.app.state.control_db)


def _accounts(request: Request):
    from lumirss.accounts_store import AccountsStore

    return AccountsStore(request.app.state.control_db)


def _error(status: int, error_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": error_type, "message": message}},
    )


async def _username_of(request: Request, user_id: str) -> str:
    user = await _accounts(request).get_user(user_id)
    return str(user["username"]) if user else user_id


@router.post("/api/v1/annotations/{annotation_id}/share", status_code=201)
async def share_annotation(
    annotation_id: str, payload: ShareCreate, request: Request
) -> Response:
    """owner 显式共享自己的批注给指定成员（创建/刷新共享串）。"""
    owner_id = require_user_id()
    annotation = await AnnotationStore(request.app.state.db).get(annotation_id)
    if annotation is None:
        return _error(404, "annotation_not_found", "批注不存在。")
    username = payload.withUsername.strip()
    recipient = await _accounts(request).get_user_by_username(username)
    if recipient is None:
        return _error(422, "share_recipient_unknown", "收件人不是本实例的成员。")
    recipient_id = str(recipient["id"])
    if recipient_id == owner_id:
        return _error(422, "share_recipient_self", "不能把批注共享给自己。")
    thread = await _threads(request).share(
        owner_user_id=owner_id,
        annotation_id=annotation["id"],
        entry_ref=annotation["entryRef"],
        excerpt=annotation["excerpt"],
        note=annotation["note"],
        recipient_user_id=recipient_id,
        recipient_username=str(recipient["username"]),
    )
    return JSONResponse(status_code=201, content=thread)


@router.delete("/api/v1/annotations/{annotation_id}/share/{thread_id}", status_code=204)
async def revoke_share(annotation_id: str, thread_id: str, request: Request) -> Response:
    owner_id = require_user_id()
    try:
        await _threads(request).revoke(thread_id, owner_id)
    except ShareThreadNotFound:
        return _error(404, "share_thread_not_found", "共享串不存在。")
    return Response(status_code=204)


@router.get("/api/v1/annotation-replies")
async def reply_inbox(
    request: Request, includeDismissed: bool = False
) -> Response:
    """我的提醒箱（收件视角；默认不含已关闭串）。"""
    user_id = require_user_id()
    items = await _threads(request).list_for_recipient(
        user_id, include_dismissed=includeDismissed
    )
    return JSONResponse({"items": items})


@router.get("/api/v1/annotation-replies/{thread_id}")
async def thread_detail(thread_id: str, request: Request) -> Response:
    """原上下文 + 全部回复；收件人查看即清未读（查看原上下文）。"""
    user_id = require_user_id()
    try:
        thread = await _threads(request).get_thread(
            thread_id, user_id, mark_seen=True
        )
    except ShareThreadNotFound:
        return _error(404, "share_thread_not_found", "共享串不存在。")
    return JSONResponse(thread)


@router.post("/api/v1/annotation-replies/{thread_id}/replies", status_code=201)
async def add_reply(thread_id: str, payload: ReplyCreate, request: Request) -> Response:
    """串内回复（成员双方均可）；owner 回复会重开已关闭的提醒。"""
    user_id = require_user_id()
    username = await _username_of(request, user_id)
    try:
        thread = await _threads(request).add_reply(
            thread_id,
            author_user_id=user_id,
            author_username=username,
            body=payload.body,
        )
    except ShareThreadNotFound:
        return _error(404, "share_thread_not_found", "共享串不存在。")
    except ShareThreadFull:
        return _error(422, "share_thread_full", "该串回复已达上限（200）。")
    except ValueError as exc:
        return _error(422, "invalid_reply", str(exc))
    return JSONResponse(status_code=201, content=thread)


@router.post("/api/v1/annotation-replies/{thread_id}/dismiss", status_code=204)
async def dismiss_thread(thread_id: str, request: Request) -> Response:
    """收件人关闭该串提醒。"""
    user_id = require_user_id()
    try:
        await _threads(request).dismiss(thread_id, user_id)
    except ShareThreadNotFound:
        return _error(404, "share_thread_not_found", "共享串不存在。")
    except ShareThreadForbidden:
        return _error(403, "share_thread_forbidden", "只有收件人可以关闭提醒。")
    return Response(status_code=204)


@router.get("/api/v1/annotation-shares")
async def my_shares(request: Request) -> Response:
    """我（owner 视角）显式共享出去的批注串列表。"""
    user_id = current_user_id() or require_user_id()
    items = await _threads(request).list_for_owner(user_id)
    return JSONResponse({"items": items})
