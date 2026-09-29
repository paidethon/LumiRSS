"""NEW-341 个人数据访问记录 —— 受授权共享入口经 Lumi 读取本人数据
的最小事件流，以及如实说明的「无法记录」边界。

能记录什么（且只记录这些）：
- 经 Lumi 公开共享入口（token 化的 feed / 共享链接）对本人数据的
  一次成功读取：purpose（哪个共享面）+ entry（哪个具体对象标签）+
  时间。绝不记录访问者 IP / User-Agent / 查询参数 —— 第三方身份
  不写进本人日志。

无法记录什么（UNRECORDED_NOTES，随 API 原样返回）：
- FreshRSS 直接服务的原生订阅：读者订阅 FreshRSS 原生 feed 时读取
  发生在 FreshRSS，Lumi 根本看不到这些请求；
- 用户本人浏览器会话的读取：那是用户自己，不是「被共享」；
- 被拒绝的访问（token 错）：与正确 token 同一 404，不留痕（不泄露
  存在性，也就没有可记录的事实）。

per-user：表在 per-user 库（RoutingDatabase），A 的事件对 B 不可见。
"""

from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

PURPOSE_LABELS = {
    "saved_view_feed": "保存视图私有 Atom 订阅",
    "briefing_feed": "个人简报 RSS 订阅",
    "gpt_digest_feed": "日报 RSS 订阅",
    "share_link": "个人共享链接",
}

UNRECORDED_NOTES = (
    "FreshRSS 直接服务的原生订阅不经过 Lumi，无法记录（读取发生在 FreshRSS）",
    "用户本人浏览器会话的读取不记录（那是本人，不是共享访问）",
    "token 错误的访问与正确 token 同一 404，不留痕也不泄露存在性",
    "绝不记录访问者 IP、User-Agent 与查询参数",
)

_MAX_EVENTS = 500
_MAX_LIMIT = 100
_MAX_ENTRY_CHARS = 120


async def record_access_event(
    db: Database, purpose: str, entry: str
) -> None:
    """记录一次共享入口读取（尽力而为：绝不影响主响应路径）。"""
    try:
        await db.migrate()
        await db.execute(
            "INSERT INTO personal_access_events (purpose, entry, accessed_at)"
            " VALUES (?, ?, ?)",
            (
                purpose,
                str(entry or "")[:_MAX_ENTRY_CHARS],
                utc_now(),
            ),
        )
    except Exception:  # noqa: BLE001 — 记录失败不阻塞 feed 渲染
        return


async def list_access_events(
    db: Database, limit: int = 50
) -> dict[str, Any]:
    """本人访问记录（新→旧，有界）+ 记录范围与边界的如实说明。"""
    await db.migrate()
    clean_limit = max(1, min(int(limit), _MAX_LIMIT))
    rows = await db.fetch_all(
        "SELECT id, purpose, entry, accessed_at FROM personal_access_events"
        " ORDER BY id DESC LIMIT ?",
        (clean_limit,),
    )
    total_row = await db.fetch_one(
        "SELECT COUNT(*) AS n FROM"
        " (SELECT 1 FROM personal_access_events LIMIT ?)",
        (_MAX_EVENTS,),
    )
    items = [
        {
            "id": int(row["id"]),
            "purpose": str(row["purpose"]),
            "purposeLabel": PURPOSE_LABELS.get(str(row["purpose"]), str(row["purpose"])),
            "entry": str(row["entry"]),
            "accessedAt": str(row["accessed_at"]),
        }
        for row in rows
    ]
    return {
        "items": items,
        "recordedScope": "仅记录经 Lumi 公开共享入口（token 化 feed / 共享链接）"
        "对本人数据的成功读取。",
        "unrecorded": list(UNRECORDED_NOTES),
        "bounded": int(total_row["n"] if total_row else 0) >= _MAX_EVENTS,
    }
