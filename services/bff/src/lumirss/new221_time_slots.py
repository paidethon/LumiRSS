"""NEW-221 分时段阅读队列 —— 命名时段（通勤/午休/晚间…）+ 文章归属。

r3 阅读队列家族（reading_queue.py N041-N046）的延伸，不是替代：
本模块管理「文章属于哪个生活时段」，条目身份仍是统一 ItemRef，
绝不复制内容（ADR 0004）；标题等呈现数据读取侧 LEFT JOIN
search_entries best-effort，消失的 ref 诚实占位。

用户决策边界（诚实契约）：

- 「打开时段即可接续」：POST open 返回该时段 pending 成员的接续视图
  并记录 last_opened_at；GET 永远无副作用；
- 「未完成文章由用户决定顺延」：carry-over 是显式 POST——用户指定
  目标时段（不可缺省、不可自动），原行转 carried 保留轨迹，目标时段
  生成新的 pending 行；服务端没有任何自动顺延路径；
- partial UNIQUE（status='pending' 上的 item_ref）：一篇文章同一时刻
  最多一个 pending 归属；已完成（done）可再次加入新时段。
"""

import sqlite3
import uuid
from typing import Any

from lumirss.db_tx import transaction
from lumirss.itemref import InvalidItemRef, parse_item_ref
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_SLOT_NAME = 60
_MAX_SLOTS = 20
_MAX_SLOT_ITEMS = 50

_SLOT_STATUSES = ("pending", "done", "carried")


class SlotInvalid(Exception):
    """时段/成员载荷非法——422 invalid_queue_slot。"""


class SlotNotFound(Exception):
    """时段不存在（或不属于当前用户）——404 queue_slot_not_found。"""


class SlotItemNotFound(Exception):
    """时段成员不存在——404 queue_slot_item_not_found。"""


class SlotItemConflict(Exception):
    """文章已有时段归属（pending 唯一）——409 queue_slot_item_conflict。"""


def validate_slot_name(name: str) -> str:
    if not isinstance(name, str):
        raise SlotInvalid("name 必须是字符串。")
    clean = name.strip()
    if not clean:
        raise SlotInvalid("name 不能为空。")
    if len(clean) > _MAX_SLOT_NAME:
        raise SlotInvalid(f"name 最长 {_MAX_SLOT_NAME} 字符。")
    return clean


def validate_item_ref(item_ref: str) -> str:
    try:
        parse_item_ref(item_ref)
    except InvalidItemRef as exc:
        raise SlotInvalid(f"itemRef 不合法：{exc}") from exc
    return item_ref


_ROW_SELECT = (
    "SELECT i.id, i.slot_id, i.item_ref, i.added_at, i.position, i.status,"
    " i.done_at, i.carried_at, i.carried_to_slot, s.name AS slot_name,"
    " se.title AS projection_title"
    " FROM queue_time_slot_items i"
    " JOIN queue_time_slots s ON s.id = i.slot_id"
    " LEFT JOIN search_entries se ON se.entry_ref = substr(i.item_ref, 5)"
)


def _item_view(row: Any) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "slotId": str(row["slot_id"]),
        "slotName": row["slot_name"],
        "itemRef": str(row["item_ref"]),
        "addedAt": str(row["added_at"]),
        "position": int(row["position"]),
        "status": str(row["status"]),
        "doneAt": row["done_at"],
        "carriedAt": row["carried_at"],
        "carriedToSlot": row["carried_to_slot"],
        # 无投影行（条目已删除/退订）为 None → Web 诚实占位。
        "title": row["projection_title"],
    }


class TimeSlotStore:
    """Persistence for queue_time_slots / queue_time_slot_items."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # -- slots ---------------------------------------------------------------

    async def list_slots(self) -> dict[str, Any]:
        """时段列表（含每时段 pending/done 计数；顺序 = position, rowid）。"""
        await self._db.migrate()
        slots = await self._db.fetch_all(
            "SELECT s.id, s.name, s.position, s.created_at, s.last_opened_at,"
            " COUNT(CASE WHEN i.status = 'pending' THEN 1 END) AS pending_count,"
            " COUNT(CASE WHEN i.status = 'done' THEN 1 END) AS done_count"
            " FROM queue_time_slots s"
            " LEFT JOIN queue_time_slot_items i ON i.slot_id = s.id"
            " GROUP BY s.id"
            " ORDER BY s.position ASC, s.rowid ASC"
        )
        return {
            "slots": [
                {
                    "id": str(row["id"]),
                    "name": str(row["name"]),
                    "position": int(row["position"]),
                    "createdAt": str(row["created_at"]),
                    "lastOpenedAt": row["last_opened_at"],
                    "pendingCount": int(row["pending_count"]),
                    "doneCount": int(row["done_count"]),
                }
                for row in slots
            ]
        }

    async def create_slot(self, name: str) -> dict[str, Any]:
        await self._db.migrate()
        clean = validate_slot_name(name)
        count = await self._db.fetch_one("SELECT COUNT(*) AS n FROM queue_time_slots")
        if count is not None and int(count["n"]) >= _MAX_SLOTS:
            raise SlotInvalid(f"时段数已达上限（{_MAX_SLOTS}）。")
        slot_id = f"qslot-{uuid.uuid4().hex}"
        now = utc_now()
        await self._db.execute(
            "INSERT INTO queue_time_slots (id, name, position, created_at)"
            " VALUES (?, ?, (SELECT COALESCE(MAX(position), 0) + 1"
            "  FROM queue_time_slots), ?)",
            (slot_id, clean, now),
        )
        return await self.get_slot_detail(slot_id)

    async def delete_slot(self, slot_id: str) -> None:
        """删除空时段（仍有 pending 成员 → 409：先决定它们的去处）。"""
        await self._db.migrate()
        await self._require_slot(slot_id)
        pending = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM queue_time_slot_items"
            " WHERE slot_id = ? AND status = 'pending'",
            (slot_id,),
        )
        if pending is not None and int(pending["n"]) > 0:
            raise SlotInvalid(
                "时段仍有未完成文章：请先处理（完成或顺延），再删除时段。"
            )

        def _tx(conn: sqlite3.Connection) -> None:
            conn.execute("DELETE FROM queue_time_slot_items WHERE slot_id = ?", (slot_id,))
            conn.execute("DELETE FROM queue_time_slots WHERE id = ?", (slot_id,))

        await transaction(self._db, _tx)

    async def _require_slot(self, slot_id: str) -> dict[str, Any]:
        row = await self._db.fetch_one(
            "SELECT id, name, position, created_at, last_opened_at"
            " FROM queue_time_slots WHERE id = ?",
            (slot_id,),
        )
        if row is None:
            raise SlotNotFound(slot_id)
        return {
            "id": str(row["id"]),
            "name": str(row["name"]),
            "position": int(row["position"]),
            "createdAt": str(row["created_at"]),
            "lastOpenedAt": row["last_opened_at"],
        }

    # -- membership ------------------------------------------------------------

    async def add_item(self, slot_id: str, item_ref: str) -> tuple[dict[str, Any], str]:
        """加入文章（新 201 / 已在该时段 pending → duplicate 200 /
        其他时段已有 pending 归属 → 409 SlotItemConflict）。"""
        await self._db.migrate()
        await self._require_slot(slot_id)
        validate_item_ref(item_ref)
        existing = await self._db.fetch_one(
            "SELECT id, slot_id, status FROM queue_time_slot_items"
            " WHERE item_ref = ? AND status = 'pending'",
            (item_ref,),
        )
        if existing is not None:
            if str(existing["slot_id"]) == slot_id:
                row = await self._get_item(str(existing["id"]))
                return row, "duplicate"
            raise SlotItemConflict(
                "该文章已有时段归属：请先在原时段完成或顺延，再分配到新时段。"
            )
        count = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM queue_time_slot_items"
            " WHERE slot_id = ? AND status = 'pending'",
            (slot_id,),
        )
        if count is not None and int(count["n"]) >= _MAX_SLOT_ITEMS:
            raise SlotInvalid(f"单个时段成员上限 {_MAX_SLOT_ITEMS} 条。")
        item_id = f"qsi-{uuid.uuid4().hex}"
        await self._db.execute(
            "INSERT INTO queue_time_slot_items (id, slot_id, item_ref, added_at,"
            " position, status) VALUES (?, ?, ?, ?,"
            " (SELECT COALESCE(MAX(position), 0) + 1 FROM queue_time_slot_items"
            "  WHERE slot_id = ? AND status = 'pending'), 'pending')",
            (item_id, slot_id, item_ref, utc_now(), slot_id),
        )
        row = await self._get_item(item_id)
        return row, "created"

    async def _get_item(self, item_id: str) -> dict[str, Any]:
        row = await self._db.fetch_one(_ROW_SELECT + " WHERE i.id = ?", (item_id,))
        if row is None:
            raise SlotItemNotFound(item_id)
        return _item_view(row)

    async def set_item_done(self, item_id: str, done: bool) -> dict[str, Any]:
        """完成状态（set 语义；绝不隐式改写上游已读）。"""
        await self._db.migrate()
        row = await self._get_item(item_id)
        if row["status"] == "carried" and done:
            raise SlotInvalid("该文章已被顺延：请在目标时段中标记完成。")
        status = "done" if done else "pending"
        await self._db.execute(
            "UPDATE queue_time_slot_items SET status = ?, done_at = ? WHERE id = ?",
            (status, utc_now() if done else None, item_id),
        )
        return await self._get_item(item_id)

    async def remove_item(self, item_id: str) -> dict[str, Any]:
        """从时段移出（物理删除成员行；pending 唯一约束随之释放）。"""
        await self._db.migrate()
        row = await self._get_item(item_id)

        def _tx(conn: sqlite3.Connection) -> None:
            conn.execute("DELETE FROM queue_time_slot_items WHERE id = ?", (item_id,))

        await transaction(self._db, _tx)
        return row

    # -- open（接续） -----------------------------------------------------------

    async def open_slot(self, slot_id: str) -> dict[str, Any]:
        """打开时段 = 接续视图：pending 成员原样按序返回 + 记录
        last_opened_at（显式动作；GET 恒无副作用）。"""
        await self._db.migrate()
        slot = await self._require_slot(slot_id)
        now = utc_now()
        await self._db.execute(
            "UPDATE queue_time_slots SET last_opened_at = ? WHERE id = ?",
            (now, slot_id),
        )
        items = await self._slot_items(slot_id)
        pending = [item for item in items if item["status"] == "pending"]
        return {
            **slot,
            "lastOpenedAt": now,
            "pendingCount": len(pending),
            "doneCount": sum(1 for item in items if item["status"] == "done"),
            "items": items,
            "resume": {
                "pendingCount": len(pending),
                "nextItemRef": pending[0]["itemRef"] if pending else None,
                "nextTitle": pending[0]["title"] if pending else None,
            },
        }

    async def _slot_items(self, slot_id: str) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            _ROW_SELECT + " WHERE i.slot_id = ? ORDER BY i.position ASC, i.rowid ASC",
            (slot_id,),
        )
        return [_item_view(row) for row in rows]

    async def get_slot_detail(self, slot_id: str) -> dict[str, Any]:
        """无副作用视图（时段 + 全部成员 pending/done/carried）。"""
        await self._db.migrate()
        slot = await self._require_slot(slot_id)
        items = await self._slot_items(slot_id)
        return {
            **slot,
            "pendingCount": sum(1 for item in items if item["status"] == "pending"),
            "doneCount": sum(1 for item in items if item["status"] == "done"),
            "items": items,
        }

    # -- carry-over（用户显式顺延） ----------------------------------------------

    async def carry_over(self, slot_id: str, target_slot_id: str) -> dict[str, Any]:
        """把该时段全部 pending 顺延到目标时段（用户显式决策；目标
        不可为原时段，顺延成员在目标时段垫到队尾；原行转 carried 保留
        轨迹）。返回 {moved, fromSlot, toSlot}。"""
        await self._db.migrate()
        await self._require_slot(slot_id)
        if target_slot_id == slot_id:
            raise SlotInvalid("顺延目标不能是原时段（留在原处无需顺延）。")
        await self._require_slot(target_slot_id)
        pending_rows = await self._db.fetch_all(
            "SELECT id, item_ref FROM queue_time_slot_items"
            " WHERE slot_id = ? AND status = 'pending'"
            " ORDER BY position ASC, rowid ASC",
            (slot_id,),
        )
        now = utc_now()
        moved = 0

        def _tx(conn: sqlite3.Connection) -> None:
            nonlocal moved
            for row in pending_rows:
                # partial UNIQUE（pending item_ref）：先转 carried 再插入。
                conn.execute(
                    "UPDATE queue_time_slot_items SET status = 'carried',"
                    " carried_at = ?, carried_to_slot = ? WHERE id = ?",
                    (now, target_slot_id, str(row["id"])),
                )
                try:
                    conn.execute(
                        "INSERT INTO queue_time_slot_items (id, slot_id, item_ref,"
                        " added_at, position, status)"
                        " VALUES (?, ?, ?, ?,"
                        " (SELECT COALESCE(MAX(position), 0) + 1"
                        "  FROM queue_time_slot_items WHERE slot_id = ?), 'pending')",
                        (
                            f"qsi-{uuid.uuid4().hex}",
                            target_slot_id,
                            str(row["item_ref"]),
                            now,
                            target_slot_id,
                        ),
                    )
                    moved += 1
                except sqlite3.IntegrityError:
                    # 目标时段已有同文 pending（并发）：本轮跳过该篇，
                    # 原行已转 carried——诚实上报 moved 数，绝不静默吞。
                    raise SlotItemConflict(
                        "目标时段已存在同篇文章的待读归属。"
                    ) from None

        await transaction(self._db, _tx)
        return {
            "moved": moved,
            "fromSlotId": slot_id,
            "toSlotId": target_slot_id,
            "carriedAt": now,
        }
