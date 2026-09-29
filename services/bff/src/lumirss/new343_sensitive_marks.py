"""NEW-343 敏感资料标记 —— 用户为个人文章设置「不得发送至外部 AI」
策略；命中标记的条目在 Lumi 全部 AI 发送路径被后端阻止并说明原因。

诚实口径（硬规则）：
- 阻止是后端真实拦截：摘要（含任务中心重试）、对话、翻译分段、
  翻译对照四条发送路径统一走 ``ai_send_block_denial`` —— 标记存在
  即 403 ai_send_blocked（附用户自己的原因），不是仅 UI 隐藏；
- 无法阻止的路径如实说明：FreshRSS 侧或其他客户端直连 provider 的
  请求不经过 Lumi，标记管不到 —— denial 响应与列表 API 均随附该
  边界说明；
- 标记按 entry_ref（内容版本无关的条目标识）生效，本人可随时解除。

per-user：表在 per-user 库（RoutingDatabase），A 的标记对 B 完全
不可见、也拦不住 B 的 AI 任务（B 可对自己的同名条目另行标记）。
"""

from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

MAX_REASON_CHARS = 200

HONESTY_NOTE = (
    "标记只阻止 Lumi 发起的 AI 任务（摘要/对话/翻译分段/对照）；"
    "FreshRSS 侧或其他客户端直连 AI 服务的请求不经过 Lumi，无法阻止。"
)


class InvalidSensitiveMark(ValueError):
    """标记负载非法（映射 422）。"""


def clean_reason(raw: Any) -> str:
    if raw is None:
        return "含个人敏感信息，不发送至外部 AI。"
    if not isinstance(raw, str):
        raise InvalidSensitiveMark("reason 必须是字符串。")
    text = raw.strip()
    if len(text) > MAX_REASON_CHARS:
        raise InvalidSensitiveMark(f"reason 最长 {MAX_REASON_CHARS} 字符。")
    return text or "含个人敏感信息，不发送至外部 AI。"


class SensitiveMarkStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def set_mark(self, entry_ref: str, reason: str) -> dict[str, Any]:
        await self._db.migrate()
        clean = clean_reason(reason)
        await self._db.execute(
            "INSERT INTO ai_send_blocks (entry_ref, reason, created_at)"
            " VALUES (?, ?, ?)"
            " ON CONFLICT(entry_ref) DO UPDATE SET reason = excluded.reason",
            (entry_ref, clean, utc_now()),
        )
        return {"entryRef": entry_ref, "reason": clean, "note": HONESTY_NOTE}

    async def clear_mark(self, entry_ref: str) -> bool:
        await self._db.migrate()

        import sqlite3

        from lumirss.db_tx import transaction

        def _tx(conn: sqlite3.Connection) -> bool:
            cursor = conn.execute(
                "DELETE FROM ai_send_blocks WHERE entry_ref = ?", (entry_ref,)
            )
            return bool(cursor.rowcount)

        return bool(await transaction(self._db, _tx))

    async def get_mark(self, entry_ref: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT entry_ref, reason, created_at FROM ai_send_blocks"
            " WHERE entry_ref = ?",
            (entry_ref,),
        )
        if row is None:
            return None
        return {
            "entryRef": str(row["entry_ref"]),
            "reason": str(row["reason"]),
            "createdAt": str(row["created_at"]),
        }

    async def list_marks(self, limit: int = 200) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT entry_ref, reason, created_at FROM ai_send_blocks"
            " ORDER BY created_at DESC LIMIT ?",
            (max(1, min(int(limit), 500)),),
        )
        return [
            {
                "entryRef": str(row["entry_ref"]),
                "reason": str(row["reason"]),
                "createdAt": str(row["created_at"]),
            }
            for row in rows
        ]

    async def has_mark(self, entry_ref: str) -> bool:
        row = await self._db.fetch_one(
            "SELECT 1 FROM ai_send_blocks WHERE entry_ref = ?", (entry_ref,)
        )
        return row is not None


async def ai_send_block_denial(
    store: SensitiveMarkStore, entry_ref: str
) -> dict[str, Any] | None:
    """发送路径守卫：命中标记 → 403 错误体（含用户原因 + 边界说明）；
    未命中 → None（放行）。fail-open 于存储异常（与来源 AI 禁用同款
    降级：投影/读不到不阻塞主流程）。"""
    try:
        mark = await store.get_mark(entry_ref)
    except Exception:  # noqa: BLE001 — 存储不可用不伪装成「已阻止」之外的行为
        return None
    if mark is None:
        return None
    return {
        "error": {
            "type": "ai_send_blocked",
            "message": "该文章已被你标记为「不得发送至外部 AI」，任务被阻止。",
            "reason": mark["reason"],
            "markedAt": mark["createdAt"],
            "note": HONESTY_NOTE,
        }
    }
