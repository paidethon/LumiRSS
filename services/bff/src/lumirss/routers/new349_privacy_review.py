"""NEW-349 隐私检查向导路由。

- GET  /api/v1/privacy/review                 逐项清单（sharing/external_ai/caches）
- POST /api/v1/privacy/review/{key}/withdraw  逐项真实撤回（可带 {ref}）
- 没有批量撤回端点：向导不提供一键全删（404）。
"""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from lumirss.new349_privacy_review import (
    NO_BULK_NOTE,
    ReviewWithdrawInvalid,
    recent_actions,
    record_review_action,
)

router = APIRouter()


class WithdrawBody(BaseModel):
    model_config = {"extra": "forbid"}

    ref: str = ""


async def _require_user(request: Request) -> str | None:
    from lumirss.config import LumiSettings
    from lumirss.routers.auth import _current_user_id

    if LumiSettings().LUMIRSS_AUTH_MODE != "session":
        return None
    return await _current_user_id(request)


def _unauth() -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"error": {"type": "session_required", "message": "Login required."}},
    )


async def _review_items(request: Request) -> list[dict[str, Any]]:
    db = request.app.state.db
    items: list[dict[str, Any]] = []

    def add(
        key: str,
        category: str,
        title: str,
        detail: str,
        *,
        withdraw_key: str | None = None,
        needs_ref: bool = False,
        how: str = "",
    ) -> None:
        items.append(
            {
                "key": key,
                "category": category,
                "title": title,
                "detail": detail,
                "withdraw": {
                    "available": withdraw_key is not None,
                    "actionKey": withdraw_key,
                    "needsRef": needs_ref,
                    "how": how,
                },
            }
        )

    from lumirss.gpt_digest_store import FEED_TOKEN_KEY
    from lumirss.new285_feed import BriefingFeedStore
    from lumirss.new344_share_links import ShareLinkStore

    briefing = await BriefingFeedStore(db).get_state()
    add(
        "briefing_feed",
        "sharing",
        "个人简报 RSS 订阅",
        "已开启：订阅地址在公开网络上可拉取" if briefing and briefing["enabled"] else "未开启",
        withdraw_key="briefing_feed" if briefing and briefing["enabled"] else None,
        how="撤销订阅 token，外部地址立即 404",
    )
    links = await ShareLinkStore(db).list_links()
    active_links = [link for link in links if link["revokedAt"] is None]
    add(
        "share_link",
        "sharing",
        "共享链接",
        f"有效 {len(active_links)} 条"
        + (
            "：" + "、".join(f"#{x['id']} {x['title']}" for x in active_links[:5])
            if active_links
            else ""
        ),
        withdraw_key="share_link" if active_links else None,
        needs_ref=True,
        how="逐条撤销（body.ref = 链接 id）",
    )
    from lumirss.api_source_store import ApiSourceStore

    sources = await ApiSourceStore(db).list_sources()
    active_sources = [s for s in sources if s.enabled]
    add(
        "api_source",
        "sharing",
        "API 来源（bearer 写入）",
        f"启用 {len(active_sources)} 个" if active_sources else "无启用",
        withdraw_key="api_source" if active_sources else None,
        needs_ref=True,
        how="停用（body.ref = 来源 uuid），bearer 立即失效",
    )
    from lumirss.new308_outbound_subscriptions import OutboundSubscriptionStore

    subs = await OutboundSubscriptionStore(
        db, request.app.state.secrets_store
    ).list_subscriptions()
    active_subs = [s for s in subs if str(s["state"]) == "active"]
    add(
        "out_webhook",
        "sharing",
        "Webhook 外发订阅",
        f"活跃 {len(active_subs)} 条" if active_subs else "无活跃",
        withdraw_key="out_webhook" if active_subs else None,
        needs_ref=True,
        how="撤销（body.ref = 订阅 id），停发并删签名材料",
    )
    digest_on = request.app.state.secrets_store.configured(FEED_TOKEN_KEY)
    add(
        "gpt_digest_feed",
        "sharing",
        "日报 RSS 订阅",
        "已开启：订阅地址在公开网络上可拉取" if digest_on else "未开启",
        withdraw_key="gpt_digest_feed" if digest_on else None,
        how="删除订阅 token，外部地址立即 404",
    )
    from lumirss.saved_search_store import SavedSearchStore

    views = await SavedSearchStore(db).list()
    feed_views = [v for v in views if v.get("hasFeedToken")]
    add(
        "saved_search_feed",
        "sharing",
        "保存视图私有 Atom 订阅",
        f"{len(feed_views)} 个视图开启了 feed token" if feed_views else "无",
        withdraw_key="saved_search_feed" if feed_views else None,
        needs_ref=True,
        how="清除该视图的 feed token（body.ref = 视图 id）",
    )
    hosts = await _ai_hosts(request)
    add(
        "external_ai",
        "external_ai",
        "外部 AI",
        hosts["ai_host"]
        and f"已配置：文本发往 {hosts['ai_host']}（摘要/对话/AI 翻译）"
        or "未配置外部 AI",
        withdraw_key=None,
        how="在 AI 设置页管理 provider 配置（破坏性操作，不在向导里一键清空）",
    )
    from lumirss.search_snapshot_store import SearchSnapshotStore

    snap = await SearchSnapshotStore(db).count_before("9999-12-31")
    add(
        "search_snapshots",
        "server_records",
        "搜索快照（服务端）",
        f"{snap} 条",
        withdraw_key="search_snapshots" if snap else None,
        how="清除本人全部搜索快照",
    )
    from lumirss.ai_task_log import AiTaskLogStore

    logs = await AiTaskLogStore(db).count_before("9999-12-31")
    add(
        "ai_task_logs",
        "server_records",
        "AI 任务日志（服务端）",
        f"{logs} 条",
        withdraw_key="ai_task_logs" if logs else None,
        how="清除本人全部 AI 任务日志",
    )
    from lumirss.auth_store import AuthStore
    from lumirss.routers.auth import _current_user_id

    sessions = await AuthStore(request.app.state.control_db).list_sessions(
        user_id=await _current_user_id(request)
    )
    add(
        "sessions_others",
        "server_records",
        "登录会话（其他设备）",
        f"共 {len(sessions)} 个活跃会话",
        withdraw_key="sessions_others" if len(sessions) > 1 else None,
        how="撤销除当前外的全部会话",
    )
    add(
        "reader_offline_cache",
        "device_cache",
        "阅读离线缓存（设备本地）",
        "在浏览器/设备本地存储——服务端看不到也清不掉",
        withdraw_key=None,
        how="只能在设备本地的浏览器设置里清除（服务端无法代劳）",
    )
    return items


async def _ai_hosts(request: Request) -> dict[str, Any]:
    db = request.app.state.db
    try:
        from lumirss.ai_settings import AiSettingsStore

        ai = await AiSettingsStore(db).load()
    except Exception:  # noqa: BLE001 — 读不到 = 未配置
        ai = {}
    from lumirss.routers.privacy import _hostname_of

    return {"ai_host": _hostname_of(ai.get("ai.base_url", ""))}


@router.get("/api/v1/privacy/review", response_model=None)
async def get_privacy_review(request: Request) -> JSONResponse:
    user_id = await _require_user(request)
    if user_id is None:
        return _unauth()
    items = await _review_items(request)
    return JSONResponse(
        {
            "items": items,
            "note": NO_BULK_NOTE,
            "recentActions": await recent_actions(request.app.state.db),
        },
        headers={"Cache-Control": "no-store"},
    )


@router.post("/api/v1/privacy/review/{key}/withdraw", response_model=None)
async def withdraw_review_item(key: str, body: WithdrawBody, request: Request) -> JSONResponse:
    user_id = await _require_user(request)
    if user_id is None:
        return _unauth()
    db = request.app.state.db
    ref = body.ref.strip()
    result: dict[str, Any] | None = None
    try:
        if key == "briefing_feed":
            from lumirss.new285_feed import BriefingFeedStore

            result = (
                {"revoked": True} if await BriefingFeedStore(db).revoke() else None
            )
        elif key == "share_link":
            from lumirss.new344_share_links import ShareLinkStore

            result = (
                {"revoked": True}
                if ref.isdigit() and await ShareLinkStore(db).revoke(int(ref))
                else None
            )
        elif key == "api_source":
            from lumirss.api_source_store import ApiSourceStore

            source = (
                await ApiSourceStore(db).update(ref, enabled=False) if ref else None
            )
            result = {"disabled": True} if source is not None else None
        elif key == "out_webhook":
            from lumirss.new308_outbound_subscriptions import (
                OutboundSubscriptionStore,
            )

            out = OutboundSubscriptionStore(db, request.app.state.secrets_store)
            if ref.isdigit() and await out.set_state(int(ref), "revoked"):
                out.delete_secret(int(ref))
                result = {"revoked": True}
        elif key == "gpt_digest_feed":
            from lumirss.gpt_digest_store import FEED_TOKEN_KEY

            result = (
                {"revoked": True}
                if request.app.state.secrets_store.delete(FEED_TOKEN_KEY)
                else None
            )
        elif key == "saved_search_feed":
            # 清除 = feed_secret 置 NULL（写空串会变成"哈希("")"仍然
            # truthy，等于留下一把假凭据）——直接清列，原子校验存在性。
            import sqlite3

            from lumirss.db_tx import transaction

            def _clear(conn: sqlite3.Connection) -> bool:
                cursor = conn.execute(
                    "UPDATE saved_searches SET feed_secret = NULL,"
                    " feed_secret_is_hash = 0 WHERE id = ?"
                    " AND feed_secret IS NOT NULL",
                    (ref,),
                )
                return bool(cursor.rowcount)

            cleared = bool(ref) and bool(await transaction(db, _clear))
            result = {"cleared": True} if cleared else None
        elif key == "search_snapshots":
            from lumirss.search_snapshot_store import SearchSnapshotStore

            result = {
                "purged": await SearchSnapshotStore(db).purge_before(
                    "9999-12-31T23:59:59+00:00"
                )
            }
        elif key == "ai_task_logs":
            from lumirss.ai_task_log import AiTaskLogStore

            result = {
                "purged": await AiTaskLogStore(db).purge_before(
                    "9999-12-31T23:59:59+00:00"
                )
            }
        elif key == "sessions_others":
            from lumirss.auth_store import AuthStore

            await AuthStore(request.app.state.control_db).revoke_all_sessions(
                user_id=user_id
            )
            # 撤全部会话会连当前会话一起撤 —— 与「只撤其他」不符。
            # 真实语义：这里回 409，提示用既有 logout-all（显式选择）。
            result = None
            return JSONResponse(
                status_code=409,
                content={
                    "error": {
                        "type": "withdraw_unavailable",
                        "message": "会话撤销会连当前设备一起登出：请使用"
                        " 设置 → 账户安全的「退出所有会话」（显式选择）。",
                    }
                },
            )
        else:
            raise ReviewWithdrawInvalid(f"未知项「{key}」。")
    except ReviewWithdrawInvalid as exc:
        return JSONResponse(
            status_code=404,
            content={"error": {"type": "unknown_review_item", "message": str(exc)}},
        )
    if result is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "type": "withdraw_not_available",
                    "message": "该项当前没有可撤回的对象（或已被撤回）。",
                }
            },
        )
    await record_review_action(db, key, ref, "withdrawn")
    return JSONResponse({"key": key, **result}, headers={"Cache-Control": "no-store"})
