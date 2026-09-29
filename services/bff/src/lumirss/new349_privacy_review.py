"""NEW-349 隐私检查向导 —— 逐项查看已开启的公开分享、外部 AI 与
设备/服务端缓存，逐项「保留或撤回」。

硬规则：**不默认一键删除** —— 没有任何批量撤回端点（也不在响应里
提供"全选"动作）；每次撤回一行留痕（privacy_review_actions，0272），
动作与对象如实可审计。

撤回动作全部调用各主存储的真实撤销（与 NEW-347 同款）：
- briefing_feed / share_link:{id} / api_source:{uuid} / out_webhook:{id}
  / gpt_digest_feed / saved_search_feed:{viewId}；
- search_snapshots / ai_task_logs → 本人活动记录清除（N189 同款）；
- sessions_others → 只撤「其他会话」（保留当前）——真实执行；
- reader_offline_cache → **无法撤回**：阅读离线缓存在设备本地，
  服务端既看不到也清不掉 ——如实返回 withdraw.available=false 与
  说明（FIX-369 最小探针同款诚实）。
- external_ai → 不在这里直接清配置（破坏性大）：available=false +
  指路 AI 设置页。

per-user：清单与撤回都作用在本人库/本人凭据；A 的向导看不到 B。
"""

from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

WITHDRAWABLE = (
    "briefing_feed",
    "share_link",
    "api_source",
    "out_webhook",
    "gpt_digest_feed",
    "saved_search_feed",
    "search_snapshots",
    "ai_task_logs",
    "sessions_others",
)

NO_BULK_NOTE = "向导没有一键全删：每项撤回独立确认、独立留痕。"


class ReviewWithdrawInvalid(ValueError):
    """撤回请求非法（映射 404/422）。"""


async def record_review_action(
    db: Database, key: str, ref: str, action: str
) -> None:
    await db.migrate()
    await db.execute(
        "INSERT INTO privacy_review_actions (key, ref, action, created_at)"
        " VALUES (?, ?, ?, ?)",
        (str(key)[:40], str(ref)[:120], action, utc_now()),
    )


async def recent_actions(db: Database, limit: int = 20) -> list[dict[str, Any]]:
    await db.migrate()
    rows = await db.fetch_all(
        "SELECT key, ref, action, created_at FROM privacy_review_actions"
        " ORDER BY id DESC LIMIT ?",
        (max(1, min(int(limit), 200)),),
    )
    return [
        {
            "key": str(row["key"]),
            "ref": str(row["ref"]),
            "action": str(row["action"]),
            "createdAt": str(row["created_at"]),
        }
        for row in rows
    ]
