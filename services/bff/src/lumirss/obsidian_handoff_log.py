"""N140 双向交接记录 — obsidian_handoff_log（每用户库）。

双向 = 导出到 Obsidian（export）/ 打开既有笔记（open）/ 用户显式导入
确认（import_confirm）。规则：

- 每次 export / open 交接自动落一条 ``pending``（服务端在交接组装成功
  后写入，note_name/policy 如实记录）；
- 置为 ``confirmed`` 的唯一路径是显式的确认动作（路由层
  ``POST /obsidian/handoff/{id}/confirm``，用户在 Obsidian 里完成保存后
  亲自点击）——页面可见性、重新加载等被动事件【绝不】自动确认；
  ``confirm`` 幂等：对已确认行重复确认无害（返回原行，不改 confirmed_at）；
- ``clear()`` 清空当前用户的全部历史（交接记录是可丢弃的辅助痕迹，
  不是事实源——事实永远在 Vault 和批注库本身）。

存储走 RoutingDatabase（每用户独立 SQLite）：路由即隔离，SQL 不含
user_id 列（与 annotations / 设备档案同一模式）。
"""

import uuid as _uuid
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

DIRECTIONS: tuple[str, ...] = ("export", "open", "import_confirm")
STATUSES: tuple[str, ...] = ("pending", "confirmed")

_MAX_NOTE_NAME = 300
_MAX_ENTRY_REF = 300
_MAX_POLICY = 50


class HandoffLogInvalid(ValueError):
    """交接记录负载未通过校验（方向未知 / 字段超长）。"""


def _clean(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


class HandoffLogStore:
    """CRUD for the per-user bidirectional handoff log."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def log_pending(
        self,
        *,
        direction: str,
        entry_ref: str = "",
        note_name: str = "",
        policy: str = "",
    ) -> dict[str, Any]:
        if direction not in DIRECTIONS:
            raise HandoffLogInvalid(
                f"direction 必须是 {'/'.join(DIRECTIONS)} 之一。"
            )
        row_id = str(_uuid.uuid4())
        await self._db.migrate()
        await self._db.execute(
            "INSERT INTO obsidian_handoff_log (id, direction, entry_ref, note_name, policy, status, created_at, confirmed_at) VALUES (?, ?, ?, ?, ?, 'pending', ?, NULL)",
            (
                row_id,
                direction,
                _clean(entry_ref, _MAX_ENTRY_REF),
                _clean(note_name, _MAX_NOTE_NAME),
                _clean(policy, _MAX_POLICY),
                utc_now(),
            ),
        )
        entry = await self.get(row_id)
        assert entry is not None  # 刚插入的行必可读回
        return entry

    async def get(self, handoff_id: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, direction, entry_ref, note_name, policy, status, created_at, confirmed_at FROM obsidian_handoff_log WHERE id = ?",
            (handoff_id,),
        )
        return _row_to_dict(row) if row is not None else None

    async def confirm(self, handoff_id: str) -> dict[str, Any] | None:
        """显式确认（唯一 confirmed 路径）。行不存在 → None（404）；
        已确认 → 原样返回（幂等，confirmed_at 不被覆盖）。"""
        current = await self.get(handoff_id)
        if current is None:
            return None
        if current["status"] == "confirmed":
            return current
        await self._db.migrate()
        await self._db.execute(
            "UPDATE obsidian_handoff_log SET status = 'confirmed', confirmed_at = ? WHERE id = ?",
            (utc_now(), handoff_id),
        )
        return await self.get(handoff_id)

    async def list_entries(self, *, limit: int = 50) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, direction, entry_ref, note_name, policy, status, created_at, confirmed_at FROM obsidian_handoff_log ORDER BY created_at DESC, id DESC LIMIT ?",
            (max(1, min(limit, 200)),),
        )
        return [_row_to_dict(row) for row in rows]

    async def clear(self) -> int:
        """清空当前用户的交接历史，返回删除条数（UI「清理」按钮）。"""
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM obsidian_handoff_log"
        )
        before = int(row["n"]) if row is not None else 0
        await self._db.execute("DELETE FROM obsidian_handoff_log")
        return before


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "direction": str(row["direction"]),
        "entryRef": str(row["entry_ref"] or ""),
        "noteName": str(row["note_name"] or ""),
        "policy": str(row["policy"] or ""),
        "status": str(row["status"]),
        "createdAt": str(row["created_at"]),
        "confirmedAt": row["confirmed_at"] if row["confirmed_at"] is None else str(row["confirmed_at"]),
    }
