"""NEW-350 个人数据删除范围预览与处理回执路由。

- GET  /api/v1/me/deletion/preview   逐类别真实计数 + 共享副本处理规则
- POST /api/v1/me/deletion/confirm   密码 + confirmText 复核 → 真实执行
                                    → 实际处理回执（已发生事实）
- GET  /api/v1/me/deletion/receipts  本人回执清单

确认会：撤销简报 feed / 逐条撤销共享链接 / 停用 API 来源 / 撤销外发
webhook / 删除日报 feed token / 清本人活动记录（AI 任务日志 + 搜索
快照）/ 标记停用（status=paused + 待删除标记，宽限期语义与
POST /me/deactivation-request 一致）/ 吊销全部会话。
FreshRSS 侧数据不在处理范围（retained 如实说明）。
"""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lumirss.new350_deletion_receipts import (
    DeletionConfirmInvalid,
    clean_confirm_text,
    deletion_counts,
    list_receipts,
    save_receipt,
    shared_copy_rules,
)

router = APIRouter()


def _reject(status: int, err_type: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"type": err_type, "message": message}},
        headers={"Cache-Control": "no-store"},
    )


async def _require_user(request: Request) -> str | None:
    from lumirss.config import LumiSettings
    from lumirss.routers.auth import _current_user_id

    if LumiSettings().LUMIRSS_AUTH_MODE != "session":
        return None
    return await _current_user_id(request)


class ConfirmBody(BaseModel):
    model_config = {"extra": "forbid"}

    password: str = Field(min_length=1, max_length=256)
    confirmText: str


@router.get("/api/v1/me/deletion/preview", response_model=None)
async def get_deletion_preview(request: Request) -> JSONResponse:
    user_id = await _require_user(request)
    if user_id is None:
        return _reject(401, "session_required", "Login required.")
    db = request.app.state.db
    return JSONResponse(
        {
            "categories": await deletion_counts(db),
            "sharedCopies": await shared_copy_rules(db, request.app.state.secrets_store),
            "note": "计数是本人库的真实行数；确认后的回执只包含实际执行了的动作。",
        },
        headers={"Cache-Control": "no-store"},
    )


@router.post("/api/v1/me/deletion/confirm", response_model=None)
async def confirm_deletion(body: ConfirmBody, request: Request) -> JSONResponse:
    user_id = await _require_user(request)
    if user_id is None:
        return _reject(401, "session_required", "Login required.")
    try:
        clean_confirm_text(body.confirmText)
    except DeletionConfirmInvalid as exc:
        return _reject(422, "confirm_invalid", str(exc))
    accounts = request.app.state.accounts
    # 密码复核 + 待删除标记（复用既有停用请求的状态机；owner 不可自助停用）。
    from lumirss.routers.auth import _sessions

    user = await accounts.get_user(user_id)
    if user is None:
        return _reject(401, "session_required", "Login required.")
    if user.get("role") == "owner":
        return _reject(403, "owner_undeactivatable", "owner 账户不支持自助停用。")
    result = await accounts.request_deactivation(user_id, body.password)
    if result is None:
        return _reject(401, "invalid_credentials", "Incorrect password.")
    db = request.app.state.db
    secrets = request.app.state.secrets_store
    actions: list[dict[str, Any]] = []

    # 1) 共享凭据面逐类真实撤销（失败不中断——回执如实记录 0）。
    from lumirss.api_source_store import ApiSourceStore
    from lumirss.gpt_digest_store import FEED_TOKEN_KEY
    from lumirss.new285_feed import BriefingFeedStore
    from lumirss.new308_outbound_subscriptions import OutboundSubscriptionStore
    from lumirss.new344_share_links import ShareLinkStore

    briefing_revoked = await BriefingFeedStore(db).revoke()
    actions.append(
        {"category": "briefing_feed", "action": "revoke", "count": int(briefing_revoked)}
    )
    store = ShareLinkStore(db)
    share_revoked = 0
    for link in await store.list_links():
        if link["revokedAt"] is None and await store.revoke(int(link["id"])):
            share_revoked += 1
    actions.append(
        {"category": "share_links", "action": "revoke", "count": share_revoked}
    )
    api_disabled = 0
    for source in await ApiSourceStore(db).list_sources():
        if source.enabled and await ApiSourceStore(db).update(
            str(source.uuid), enabled=False
        ):
            api_disabled += 1
    actions.append(
        {"category": "api_sources", "action": "disable", "count": api_disabled}
    )
    out = OutboundSubscriptionStore(db, secrets)
    webhook_revoked = 0
    for sub in await out.list_subscriptions():
        if str(sub["state"]) != "revoked" and await out.set_state(
            int(sub["id"]), "revoked"
        ):
            out.delete_secret(int(sub["id"]))
            webhook_revoked += 1
    actions.append(
        {"category": "out_webhooks", "action": "revoke", "count": webhook_revoked}
    )
    digest_removed = bool(secrets.delete(FEED_TOKEN_KEY))
    actions.append(
        {"category": "gpt_digest_feed", "action": "revoke", "count": int(digest_removed)}
    )

    # 2) 本人活动记录清除（N189 同款口径）。
    from lumirss.ai_task_log import AiTaskLogStore
    from lumirss.search_snapshot_store import SearchSnapshotStore

    purged_logs = await AiTaskLogStore(db).purge_before("9999-12-31T23:59:59+00:00")
    purged_snaps = await SearchSnapshotStore(db).purge_before(
        "9999-12-31T23:59:59+00:00"
    )
    actions.append(
        {"category": "ai_task_logs", "action": "purge", "count": purged_logs}
    )
    actions.append(
        {"category": "search_snapshots", "action": "purge", "count": purged_snaps}
    )

    # 3) 会话全部吊销 + 审计。
    from lumirss.util import utc_now

    await _sessions(request).revoke_all_sessions(user_id=user_id)
    await accounts.audit(
        actor=user_id,
        action="deletion_confirmed",
        object_type="user",
        object_id=user_id,
    )

    from datetime import UTC, datetime

    from lumirss.config import LumiSettings

    scheduled_epoch = int(result["scheduledDeletionAt"])
    scheduled_iso = datetime.fromtimestamp(scheduled_epoch, tz=UTC).isoformat(
        timespec="seconds"
    )
    receipt = await save_receipt(
        db,
        requested_at=utc_now(),
        scheduled_deletion_at=scheduled_iso,
        actions=actions,
    )
    response = JSONResponse(
        {
            "receipt": receipt,
            "graceDays": LumiSettings().LUMIRSS_DEACTIVATION_GRACE_DAYS,
            "restoreHint": "宽限期内联系运营者（管理台「恢复」）即可撤销停用。",
            "retained": receipt["retained"],
        },
        status_code=200,
        headers={"Cache-Control": "no-store"},
    )
    # 会话已全吊销：清当前 cookie（与既有停用请求同口径）。
    from lumirss.routers.auth import clear_session_cookie

    response.headers["Set-Cookie"] = clear_session_cookie()
    return response


@router.get("/api/v1/me/deletion/receipts", response_model=None)
async def get_deletion_receipts(request: Request, limit: int = 10) -> JSONResponse:
    user_id = await _require_user(request)
    if user_id is None:
        return _reject(401, "session_required", "Login required.")
    return JSONResponse(
        {"items": await list_receipts(request.app.state.db, limit)},
        headers={"Cache-Control": "no-store"},
    )
