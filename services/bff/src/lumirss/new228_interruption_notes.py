"""NEW-228 阅读中断便签 —— 离开前记「下次从哪里继续、正在想什么」。

与 N045 reading_notes（段落锚点一句话便签，恒在原地）互补：本模块是
**会话接续**便签——

- 一篇材料最多一个活跃便签（``item_ref`` UNIQUE；upsert latest-wins，
  单行单用户语义，无冲突分支）；
- ``resumeHint``：下次从哪里继续（章节/位置的自由描述，≤300 字符）；
- ``thought``：正在想什么（1..500 字符）；
- 返回文章时 ``GET`` 显示活跃便签（无活跃 → 200 + null，诚实空态）；
- 读完显式归档（``archive``）：archived_at 记账，历史可查；归档后
  可再写新便签（新的一篇旅程）。

便签是 Lumi 自有状态：绝不写入 FreshRSS，绝不参与任何同步。
"""

from typing import Any

import uuid

from lumirss.itemref import InvalidItemRef, parse_item_ref
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_THOUGHT = 500
_MAX_HINT = 300


class InterruptionNoteInvalid(Exception):
    """便签非法（thought 空/超长）——422 invalid_interruption_note。"""


class InterruptionNoteNotFound(Exception):
    """便签不存在——404 interruption_note_not_found。"""


def validate_thought(thought: str) -> str:
    if not isinstance(thought, str):
        raise InterruptionNoteInvalid("thought 必须是字符串。")
    clean = thought.strip()
    if not clean:
        raise InterruptionNoteInvalid("thought 不能为空（不写请用删除）。")
    if len(clean) > _MAX_THOUGHT:
        raise InterruptionNoteInvalid(f"thought 最长 {_MAX_THOUGHT} 字符。")
    return clean


def validate_hint(resume_hint: str | None) -> str | None:
    if resume_hint is None:
        return None
    if not isinstance(resume_hint, str):
        raise InterruptionNoteInvalid("resumeHint 必须是字符串或 null。")
    clean = resume_hint.strip()
    if not clean:
        return None
    if len(clean) > _MAX_HINT:
        raise InterruptionNoteInvalid(f"resumeHint 最长 {_MAX_HINT} 字符。")
    return clean


def validate_ref(value: str) -> str:
    try:
        parse_item_ref(value)
    except InvalidItemRef as exc:
        raise InterruptionNoteInvalid(f"itemRef 不合法：{exc}") from exc
    return value


class InterruptionNoteStore:
    """Persistence for interruption_notes."""

    def __init__(self, db: Database) -> None:
        self._db = db

    @staticmethod
    def _view(row: Any) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "itemRef": str(row["item_ref"]),
            "resumeHint": row["resume_hint"],
            "thought": str(row["thought"]),
            "createdAt": str(row["created_at"]),
            "updatedAt": str(row["updated_at"]),
            "archivedAt": row["archived_at"],
            "title": row["projection_title"],
        }

    _SELECT = (
        "SELECT n.id, n.item_ref, n.resume_hint, n.thought, n.created_at,"
        " n.updated_at, n.archived_at, se.title AS projection_title"
        " FROM interruption_notes n"
        " LEFT JOIN search_entries se ON se.entry_ref = substr(n.item_ref, 5)"
    )

    async def upsert(
        self, item_ref: str, thought: str, resume_hint: str | None = None
    ) -> dict[str, Any]:
        """离开前写/改活跃便签（latest-wins；归档行不覆盖——归档后
        再写 = 新旅程新便签）。"""
        await self._db.migrate()
        validate_ref(item_ref)
        clean_thought = validate_thought(thought)
        clean_hint = validate_hint(resume_hint)
        now = utc_now()
        existing = await self._db.fetch_one(
            "SELECT id, archived_at FROM interruption_notes WHERE item_ref = ?",
            (item_ref,),
        )
        if existing is not None and existing["archived_at"] is None:
            await self._db.execute(
                "UPDATE interruption_notes SET thought = ?, resume_hint = ?,"
                " updated_at = ? WHERE id = ?",
                (clean_thought, clean_hint, now, str(existing["id"])),
            )
            return await self._by_id(str(existing["id"]))
        note_id = f"inote-{uuid.uuid4().hex}"
        await self._db.execute(
            "INSERT INTO interruption_notes (id, item_ref, resume_hint, thought,"
            " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (note_id, item_ref, clean_hint, clean_thought, now, now),
        )
        return await self._by_id(note_id)

    async def _by_id(self, note_id: str) -> dict[str, Any]:
        row = await self._db.fetch_one(self._SELECT + " WHERE n.id = ?", (note_id,))
        if row is None:
            raise InterruptionNoteNotFound(note_id)
        return self._view(row)

    async def get_active(self, item_ref: str) -> dict[str, Any]:
        """返回文章时的接续视图：活跃便签或 null（诚实空态）。"""
        await self._db.migrate()
        validate_ref(item_ref)
        row = await self._db.fetch_one(
            self._SELECT + " WHERE n.item_ref = ? AND n.archived_at IS NULL",
            (item_ref,),
        )
        archived = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM interruption_notes"
            " WHERE item_ref = ? AND archived_at IS NOT NULL",
            (item_ref,),
        )
        return {
            "itemRef": item_ref,
            "note": self._view(row) if row is not None else None,
            "archivedCount": int(archived["n"]) if archived else 0,
        }

    async def archive(self, item_ref: str) -> dict[str, Any]:
        """读完归档（显式；活跃便签不存在 → 404）。"""
        await self._db.migrate()
        validate_ref(item_ref)
        row = await self._db.fetch_one(
            "SELECT id FROM interruption_notes"
            " WHERE item_ref = ? AND archived_at IS NULL",
            (item_ref,),
        )
        if row is None:
            raise InterruptionNoteNotFound(item_ref)
        await self._db.execute(
            "UPDATE interruption_notes SET archived_at = ? WHERE id = ?",
            (utc_now(), str(row["id"])),
        )
        return await self._by_id(str(row["id"]))

    async def list_active(self) -> dict[str, Any]:
        """全部活跃便签（跨材料的「读到一半」清单；新→旧）。"""
        await self._db.migrate()
        rows = await self._db.fetch_all(
            self._SELECT + " WHERE n.archived_at IS NULL"
            " ORDER BY n.updated_at DESC, n.rowid DESC"
        )
        return {
            "items": [self._view(row) for row in rows],
            "note": "活跃便签 = 读到一半的材料清单；读完请归档。",
        }

    async def list_archived(self, item_ref: str | None = None) -> dict[str, Any]:
        """归档历史（可按材料过滤）。"""
        await self._db.migrate()
        where = " WHERE n.archived_at IS NOT NULL"
        params: tuple[Any, ...] = ()
        if item_ref is not None:
            validate_ref(item_ref)
            where += " AND n.item_ref = ?"
            params = (item_ref,)
        rows = await self._db.fetch_all(
            self._SELECT + where + " ORDER BY n.archived_at DESC, n.rowid DESC",
            params,
        )
        return {"items": [self._view(row) for row in rows]}

    async def delete(self, item_ref: str) -> None:
        """删除活跃便签（不归档的直接丢弃；用户显式动作）。"""
        await self._db.migrate()
        validate_ref(item_ref)
        row = await self._db.fetch_one(
            "SELECT id FROM interruption_notes"
            " WHERE item_ref = ? AND archived_at IS NULL",
            (item_ref,),
        )
        if row is None:
            raise InterruptionNoteNotFound(item_ref)
        await self._db.execute(
            "DELETE FROM interruption_notes WHERE id = ?", (str(row["id"]),)
        )
