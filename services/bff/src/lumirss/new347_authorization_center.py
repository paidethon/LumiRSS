"""NEW-347 单项授权撤销中心 —— 按用途列出本人的全部凭据面并逐项
撤销，展示受影响功能而绝不暴露原令牌。

聚合的凭据面（每个都调用其主存储的真实撤销/停用，本模块不复制
任何令牌材料）：
- briefing_feed（NEW-285 个人简报 RSS）→ revoke（订阅立即 404）；
- share_link（NEW-344 共享链接）→ 逐条 revoke；
- api_source（API 来源 bearer）→ enabled=0（ingest 立即拒绝）；
- out_webhook（NEW-308 外发订阅）→ set_state revoked（停发 + 删钥）；
- gpt_digest_feed（日报 RSS token）→ 删除 secrets 键（feed 404）。

清单只含状态与影响说明（绝无 token/secret 前缀）；撤销动作留痕到
authorization_revoke_events（0270）。

per-user：全部表/凭据在 per-user 库与 per-user secrets；A 的清单里
没有 B 的任何凭据，B 的撤销触不到 A 的凭据。
"""

from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

KINDS = (
    "briefing_feed",
    "share_link",
    "api_source",
    "out_webhook",
    "gpt_digest_feed",
)

AFFECTED = {
    "briefing_feed": "个人简报 RSS 订阅地址立即失效（订阅端拉取 404）；简报数据本身不受影响",
    "share_link": "该共享链接立即失效（外部访问者 404）；已发生的访问记录保留",
    "api_source": "该 API 来源的 bearer 立即失效（外部写入被拒绝）；来源配置保留，可重新启用",
    "out_webhook": "该外发订阅立即停发并删除签名材料；投递回执保留",
    "gpt_digest_feed": "日报 RSS 订阅地址立即失效；日报内容不受影响，可重新启用生成新地址",
}


async def record_revoke(db: Database, kind: str, ref: str) -> None:
    await db.migrate()
    await db.execute(
        "INSERT INTO authorization_revoke_events (kind, ref, revoked_at)"
        " VALUES (?, ?, ?)",
        (kind, str(ref)[:120], utc_now()),
    )


async def list_revoke_events(db: Database, limit: int = 50) -> list[dict[str, Any]]:
    await db.migrate()
    rows = await db.fetch_all(
        "SELECT kind, ref, revoked_at FROM authorization_revoke_events"
        " ORDER BY id DESC LIMIT ?",
        (max(1, min(int(limit), 200)),),
    )
    return [
        {
            "kind": str(row["kind"]),
            "ref": str(row["ref"]),
            "revokedAt": str(row["revoked_at"]),
        }
        for row in rows
    ]


class AuthorizationCenter:
    """只读清单 + 逐项真实撤销（路由层鉴权；这里只做数据面）。"""

    def __init__(self, db: Database, secrets: Any) -> None:
        self._db = db
        self._secrets = secrets

    async def inventory(self) -> dict[str, Any]:
        from lumirss.api_source_store import ApiSourceStore
        from lumirss.gpt_digest_store import FEED_TOKEN_KEY
        from lumirss.new285_feed import BriefingFeedStore
        from lumirss.new308_outbound_subscriptions import (
            OutboundSubscriptionStore,
        )
        from lumirss.new344_share_links import ShareLinkStore

        items: list[dict[str, Any]] = []

        briefing = await BriefingFeedStore(self._db).get_state()
        items.append(
            {
                "kind": "briefing_feed",
                "ref": "default",
                "label": "个人简报 RSS 订阅",
                "active": bool(briefing and briefing["enabled"]),
                "detail": (f"启用于 {briefing['createdAt']}" if briefing else "未启用"),
                "affected": AFFECTED["briefing_feed"],
            }
        )

        for link in await ShareLinkStore(self._db).list_links():
            active = link["revokedAt"] is None
            items.append(
                {
                    "kind": "share_link",
                    "ref": str(link["id"]),
                    "label": f"共享链接：{link['title']}",
                    "active": active,
                    "detail": (
                        f"范围 {link['scope']}；已用 {link['useCount']}"
                        + (f"/{link['maxUses']}" if link["maxUses"] is not None else "")
                    ),
                    "affected": AFFECTED["share_link"],
                }
            )

        for source in await ApiSourceStore(self._db).list_sources():
            items.append(
                {
                    "kind": "api_source",
                    "ref": str(source.uuid),
                    "label": f"API 来源：{source.name}",
                    "active": bool(source.enabled),
                    "detail": f"端点 {source.endpoint}",
                    "affected": AFFECTED["api_source"],
                }
            )

        out_store = OutboundSubscriptionStore(self._db, self._secrets)
        for sub in await out_store.list_subscriptions():
            items.append(
                {
                    "kind": "out_webhook",
                    "ref": str(sub["id"]),
                    "label": f"Webhook 外发：{sub['event_type']}",
                    "active": str(sub["state"]) == "active",
                    "detail": f"目标 {sub['target_url']}",
                    "affected": AFFECTED["out_webhook"],
                }
            )

        digest_active = self._secrets.configured(FEED_TOKEN_KEY)
        items.append(
            {
                "kind": "gpt_digest_feed",
                "ref": "default",
                "label": "日报 RSS 订阅",
                "active": bool(digest_active),
                "detail": "订阅 token 存在" if digest_active else "未启用",
                "affected": AFFECTED["gpt_digest_feed"],
            }
        )
        return {
            "items": items,
            "note": "清单只含状态与影响说明；任何令牌材料（含前缀）都不会出现在响应里。",
        }

    async def revoke(self, kind: str, ref: str) -> dict[str, Any] | None:
        """执行单项撤销；未知 kind/对象 → None（404）。"""
        from lumirss.api_source_store import ApiSourceStore
        from lumirss.gpt_digest_store import FEED_TOKEN_KEY
        from lumirss.new285_feed import BriefingFeedStore
        from lumirss.new308_outbound_subscriptions import (
            OutboundSubscriptionStore,
        )
        from lumirss.new344_share_links import ShareLinkStore

        if kind not in KINDS:
            return None
        done = False
        if kind == "briefing_feed":
            done = await BriefingFeedStore(self._db).revoke()
        elif kind == "share_link":
            try:
                link_id = int(ref)
            except ValueError:
                return None
            done = await ShareLinkStore(self._db).revoke(link_id)
        elif kind == "api_source":
            source = await ApiSourceStore(self._db).update(
                ref, enabled=False
            )
            done = source is not None
        elif kind == "out_webhook":
            try:
                sub_id = int(ref)
            except ValueError:
                return None
            out = OutboundSubscriptionStore(self._db, self._secrets)
            done = await out.set_state(sub_id, "revoked")
            if done:
                out.delete_secret(sub_id)
        elif kind == "gpt_digest_feed":
            done = self._secrets.delete(FEED_TOKEN_KEY)
        if not done:
            return None
        await record_revoke(self._db, kind, ref)
        return {"kind": kind, "ref": ref, "revoked": True, "affected": AFFECTED[kind]}
