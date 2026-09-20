"""F021 手工关联内容 —— item_relations 表的 SQL 唯一入口。

- 纯手工元数据：无任何 AI 参与，只有显式用户动作写这里；
- UNIQUE(src_ref, dst_ref)：同向重复 = 幂等（note 相同返回既有行）
  或冲突（note 不同 → RelationDuplicate，映射 409）；
- 目标失效（RSS 条目被删）时关系保留——stale 判定在路由层按 registry
  解析结果标记，本模块只存 ref，绝不自动删除。
"""

from typing import Any

from lumirss.itemref import parse_item_ref
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_NOTE_CHARS = 500


class RelationInvalid(ValueError):
    """关联非法（自关联 / ref 域不合法），映射 422。"""


class RelationDuplicate(Exception):
    """同向关联已存在但备注不同，映射 409。"""


class RelationNotFound(Exception):
    """关联不存在（解除时），映射 404。"""


def _validate_ref(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RelationInvalid(f"{field} must be a non-empty item ref.")
    try:
        return parse_item_ref(value.strip()).format()
    except ValueError as exc:
        raise RelationInvalid(str(exc)) from exc


def _validate_note(note: Any) -> str:
    if note is None:
        return ""
    if not isinstance(note, str):
        raise RelationInvalid("note must be a string.")
    return note.strip()[:_MAX_NOTE_CHARS]


def _row_to_dict(row: Any) -> dict[str, Any]:
    try:
        kind = row["kind"]
    except (IndexError, KeyError):
        kind = "manual"
    return {
        "id": int(row["id"]),
        "srcRef": str(row["src_ref"]),
        "dstRef": str(row["dst_ref"]),
        "note": str(row["note"] or ""),
        # F071：关系种类（manual=手工；duplicate=疑似重复确认）
        "kind": str(kind or "manual"),
        "createdAt": str(row["created_at"]),
    }


class ItemRelationStore:
    """CRUD over item_relations（内联 SQL + 绑定参数）。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self, src_ref: Any, dst_ref: Any, note: Any, *, kind: str = "manual"
    ) -> dict[str, Any]:
        clean_src = _validate_ref(src_ref, "src_ref")
        clean_dst = _validate_ref(dst_ref, "dst_ref")
        if clean_src == clean_dst:
            raise RelationInvalid("条目不能与自身关联。")
        clean_note = _validate_note(note)
        await self._db.migrate()
        existing = await self._db.fetch_one(
            "SELECT id, src_ref, dst_ref, note, kind, created_at FROM item_relations WHERE src_ref = ? AND dst_ref = ?",
            (clean_src, clean_dst),
        )
        if existing is not None:
            if str(existing["note"] or "") != clean_note:
                raise RelationDuplicate(
                    "该关联已存在（备注不同）；如需修改请先解除再重建。"
                )
            return _row_to_dict(existing)
        await self._db.execute(
            "INSERT INTO item_relations (src_ref, dst_ref, note, kind, created_at) VALUES (?, ?, ?, ?, ?)",
            (clean_src, clean_dst, clean_note, kind if kind in ("manual", "duplicate") else "manual", utc_now()),
        )
        row = await self._db.fetch_one(
            "SELECT id, src_ref, dst_ref, note, kind, created_at FROM item_relations WHERE src_ref = ? AND dst_ref = ?",
            (clean_src, clean_dst),
        )
        assert row is not None
        return _row_to_dict(row)

    async def list_for_item(self, item_ref: str) -> list[dict[str, Any]]:
        """双向查询：以 item_ref 为起点或终点的全部关系（旧→新）。"""
        clean = _validate_ref(item_ref, "item_ref")
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, src_ref, dst_ref, note, kind, created_at FROM item_relations WHERE src_ref = ? OR dst_ref = ? ORDER BY id ASC",
            (clean, clean),
        )
        return [_row_to_dict(row) for row in rows]

    async def all_relations(self) -> list[dict[str, Any]]:
        """图谱派生用：全量手工边（有界）。"""
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, src_ref, dst_ref, note, kind, created_at FROM item_relations ORDER BY id ASC LIMIT 5000",
            (),
        )
        return [_row_to_dict(row) for row in rows]

    async def delete(self, relation_id: int) -> bool:
        await self._db.migrate()

        def _tx(conn: Any) -> int:
            cursor = conn.execute(
                "DELETE FROM item_relations WHERE id = ?", (relation_id,)
            )
            return cursor.rowcount

        from lumirss.db_tx import transaction

        return (await transaction(self._db, _tx)) == 1
