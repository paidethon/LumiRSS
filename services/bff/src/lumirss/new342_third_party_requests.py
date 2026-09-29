"""NEW-342 第三方请求清单 —— 一次阅读 / AI 操作前后会访问的外部
域名与用途（配置推导，非逐请求日志）+ 可选请求的真实开关。

诚实口径：
- 本清单从「当前真实配置」实时推导（FreshRSS/RSSHub 实例、AI
  provider base_url、远程图片模式、WebDAV、IMAP、webhook 目标、
  共享链接）——Lumi 不记录逐请求网络遥测，所以没有也绝不冒充
  「实际请求日志」；每个条目都注明这是配置推导；
- 「可关闭可选请求」是真的关：remote_images 写既有便携设置
  readerImageMode=hidden（阅读器真实生效）；outbound_webhooks 暂停
  全部活跃订阅（dispatch 真实停发）；动作留痕到
  third_party_optout_events（0265）供本人回顾；
- 零新增网络调用：本模块只读本地配置与库。

per-user：开关与留痕在 per-user 库；AI host 等实例/用户配置按既有
读取路径（与 FIX-148 data-flows 同一数据源口径）。
"""

from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

REMOTE_IMAGES_KEY = "remote_images"
OUTBOUND_WEBHOOKS_KEY = "outbound_webhooks"

OPTOUT_LABELS = {
    REMOTE_IMAGES_KEY: "文章远程图片（图片来源站可见你的 IP 与 User-Agent）",
    OUTBOUND_WEBHOOKS_KEY: "Webhook 外发订阅（事件推送到你配置的目标）",
}

DERIVED_NOTE = "清单从当前配置实时推导，不是逐请求网络日志（Lumi 不记录请求遥测）。"

_MAX_NOTE_ROWS = 200


async def _optout_state(db: Database, key: str) -> bool:
    row = await db.fetch_one(
        "SELECT 1 FROM third_party_optout_events"
        " WHERE key = ? AND action = 'off'"
        " AND id > COALESCE((SELECT MAX(id) FROM third_party_optout_events"
        " WHERE key = ? AND action = 'on'), 0)",
        (key, key),
    )
    return row is not None


async def record_optout_action(
    db: Database, key: str, action: str
) -> None:
    """开关动作留痕（off/on；尽力而为）。"""
    await db.migrate()
    await db.execute(
        "INSERT INTO third_party_optout_events (key, action, created_at)"
        " VALUES (?, ?, ?)",
        (key, action, utc_now()),
    )


async def recent_optout_actions(db: Database, limit: int = 20) -> list[dict[str, Any]]:
    await db.migrate()
    rows = await db.fetch_all(
        "SELECT key, action, created_at FROM third_party_optout_events"
        " ORDER BY id DESC LIMIT ?",
        (max(1, min(int(limit), _MAX_NOTE_ROWS)),),
    )
    return [
        {
            "key": str(row["key"]),
            "action": str(row["action"]),
            "createdAt": str(row["created_at"]),
        }
        for row in rows
    ]


def build_third_party_inventory(
    *,
    freshrss_host: str | None,
    rsshub_host: str | None,
    ai_host: str | None,
    libretranslate_host: str | None,
    tts_host: str | None,
    webdav_host: str | None,
    imap_host: str | None,
    remote_images_hidden: bool,
    webhook_hosts: list[str],
    share_link_count: int,
    optouts: dict[str, bool],
) -> dict[str, Any]:
    """纯函数组装（可独立测试）。host 只含主机名，绝无密钥/路径。"""

    def item(
        key: str,
        scope: str,
        host: str | None,
        purpose: str,
        *,
        optional: bool,
        optout_key: str | None = None,
        controlled_by: str | None = None,
    ) -> dict[str, Any]:
        disabled = bool(optout_key and optouts.get(optout_key))
        return {
            "key": key,
            "scope": scope,
            "host": host,
            "purpose": purpose,
            "optional": optional,
            "disabled": disabled,
            "controlledBy": controlled_by,
            "optoutKey": optout_key,
        }

    reading = [
        item(
            "freshrss",
            "reading",
            freshrss_host,
            "订阅与条目同步（FreshRSS 抓取源与正文存储）",
            optional=False,
            controlled_by="实例配置（FRESHRSS_BASE_URL）",
        ),
        item(
            "rsshub",
            "reading",
            rsshub_host,
            "非 RSS 源的内容生成（RSSHub 拉取上游）",
            optional=True,
            controlled_by="实例配置（RSSHUB_BASE_URL）；未配置即无此请求",
        ),
        item(
            REMOTE_IMAGES_KEY,
            "reading",
            None,
            "文章远程图片（图片来源站可见你的 IP 与 User-Agent）",
            optional=True,
            optout_key=REMOTE_IMAGES_KEY,
            controlled_by="便携设置 readerImageMode",
        ),
        item(
            "webdav",
            "reading",
            webdav_host,
            "服务器端备份上传（完整备份包，不含秘密值）",
            optional=True,
            controlled_by="备份设置（未配置即无此请求）",
        ),
        item(
            "imap",
            "reading",
            imap_host,
            "邮件简报收信（收件箱邮件内容）",
            optional=True,
            controlled_by="邮件简报设置（未配置即无此请求）",
        ),
        item(
            OUTBOUND_WEBHOOKS_KEY,
            "reading",
            "、".join(webhook_hosts) or None,
            "事件外发（entry.starred 等推送到你配置的目标 URL）",
            optional=True,
            optout_key=OUTBOUND_WEBHOOKS_KEY,
            controlled_by="Webhook 订阅（可逐条删除，见授权撤销中心）",
        ),
        item(
            "share_link_visitors",
            "reading",
            None,
            f"你发布的共享链接被外部访问者拉取（当前 {share_link_count} 条有效）",
            optional=True,
            controlled_by="共享链接（可撤销，见授权撤销中心）",
        ),
    ]
    ai = [
        item(
            "ai-provider",
            "ai",
            ai_host,
            "AI 摘要 / 对话 / AI 翻译（标题、正文或待翻译文本发往该主机）",
            optional=True,
            controlled_by="AI 设置 ai.base_url（未配置即无此请求）",
        ),
        item(
            "libretranslate",
            "ai",
            libretranslate_host,
            "本地引擎翻译（待翻译文本发往该主机）",
            optional=True,
            controlled_by="翻译设置 translation.libretranslate_url",
        ),
        item(
            "tts",
            "ai",
            tts_host,
            "服务端语音合成（当前朗读文本发往该主机）",
            optional=True,
            controlled_by="purpose=tts provider（未配置 = 浏览器本机合成，不出设备）",
        ),
    ]
    return {
        "reading": reading,
        "ai": ai,
        "note": DERIVED_NOTE,
        "optoutLabels": OPTOUT_LABELS,
    }
