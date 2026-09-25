"""N045 阅读中断便签 —— 离开长文前的一句话便签（每用户库，一行一条目）。

- ``reading_notes.entry_ref`` 主键：PUT 恒覆盖（latest-wins，单行单
  用户语义，无冲突分支）；note ≤200 字符（路由层校验，这里再钳一次）；
- ``para_id`` = 留便签时的段落锚点（与 F056 reading-progress 同构），
  重开文章时用于把便签放回原段落位置；
- 便签是 Lumi 自有状态：绝不写入 FreshRSS，也绝不参与任何同步。
"""

from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_NOTE_LENGTH = 200
_MAX_PARA_ID_LENGTH = 200


class ReadingNoteInvalid(Exception):
    """便签非法（空 / 超长 / 类型错误）——422 invalid_reading_note。"""


class ReadingNoteNotFound(Exception):
    """便签不存在——404 reading_note_not_found。"""


def validate_note(note: str) -> str:
    if not isinstance(note, str):
        raise ReadingNoteInvalid("note 必须是字符串。")
    clean = note.strip()
    if not clean:
        raise ReadingNoteInvalid("note 不能为空（删除请用 DELETE）。")
    if len(clean) > _MAX_NOTE_LENGTH:
        raise ReadingNoteInvalid(f"note 最长 {_MAX_NOTE_LENGTH} 字符（一句话便签）。")
    return clean


def validate_para_id(para_id: str | None) -> str | None:
    if para_id is None:
        return None
    if not isinstance(para_id, str):
        raise ReadingNoteInvalid("paraId 必须是字符串或 null。")
    clean = para_id.strip()
    if not clean:
        return None
    if len(clean) > _MAX_PARA_ID_LENGTH:
        raise ReadingNoteInvalid(f"paraId 最长 {_MAX_PARA_ID_LENGTH} 字符。")
    return clean


class ReadingNoteStore:
    """Persistence for reading_notes."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def put(
        self, entry_ref: str, note: str, para_id: str | None = None
    ) -> dict[str, Any]:
        clean_note = validate_note(note)
        clean_para = validate_para_id(para_id)
        await self._db.migrate()
        updated_at = utc_now()
        await self._db.execute(
            "INSERT INTO reading_notes (entry_ref, note, para_id, updated_at)"
            " VALUES (?, ?, ?, ?)"
            " ON CONFLICT(entry_ref) DO UPDATE SET"
            " note = excluded.note, para_id = excluded.para_id, updated_at = excluded.updated_at",
            (entry_ref, clean_note, clean_para, updated_at),
        )
        return {
            "entryRef": entry_ref,
            "note": clean_note,
            "paraId": clean_para,
            "updatedAt": updated_at,
        }

    async def get(self, entry_ref: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT entry_ref, note, para_id, updated_at FROM reading_notes WHERE entry_ref = ?",
            (entry_ref,),
        )
        if row is None:
            return None
        return {
            "entryRef": str(row["entry_ref"]),
            "note": str(row["note"]),
            "paraId": row["para_id"],
            "updatedAt": str(row["updated_at"]),
        }

    async def delete(self, entry_ref: str) -> bool:
        """删除便签；返回是否存在（false = 本就没有，幂等友好）。"""
        await self._db.migrate()
        cursor = await self._db.execute(
            "DELETE FROM reading_notes WHERE entry_ref = ?", (entry_ref,)
        )
        return bool(cursor)
