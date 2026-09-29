"""NEW-328 库同步冲突收件箱 —— 个人修正 vs 源文件更新并排展示。

口径：

- 个人修正层（obsidian_note_corrections）：用户对某条投影笔记的
  标题/笔记修正，base_content_hash 记录其所基于的源版本——纯 Lumi
  侧独立层，绝不回写 Vault；
- 检测（detect）：逐条对比修正的 base hash 与投影当前 hash；源文件
  更新（hash 变化）→ 生成/刷新 open 冲突行，并把并排数据（源标题/
  源正文摘录 vs 个人修正）快照进行内——之后源再变，打开中的冲突
  随检测如实刷新；
- 解决只能是显式二选一：``keep_independent``（保留独立层：修正重定
  基到当前源版本）或 ``adopted_source``（采用源版本：删除个人修正
  层）。已解决的冲突留档可查（有界）。

per-user：修正与冲突都在 per-user 库；投影是 owner 的 Vault 面
（路由层 owner 门槛），A 的冲突收件箱对 B 不可见。
"""

import uuid as _uuid
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

MAX_PERSONAL_TITLE = 200
MAX_PERSONAL_NOTE = 2000
_SOURCE_EXCERPT_CHARS = 200
_MAX_LISTED = 200

DECISION_KEEP_INDEPENDENT = "keep_independent"
DECISION_ADOPT_SOURCE = "adopt_source"


class ConflictInvalid(ValueError):
    """冲突输入非法（映射 400）。"""


class NoteNotFoundInProjection(Exception):
    """投影中没有该笔记（404）。"""


class ConflictNotFound(Exception):
    """冲突行不存在（404）。"""


def _clean(value: Any, limit: int) -> str:
    return str(value or "").strip()[:limit]


class ConflictInboxStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    # -- 个人修正层 ------------------------------------------------------

    async def put_correction(
        self, note_uuid: str, personal_title: str, personal_note: str
    ) -> dict[str, Any]:
        await self._db.migrate()
        clean_uuid = str(note_uuid or "").strip().replace("library:", "")
        row = await self._db.fetch_one(
            "SELECT content_hash FROM obsidian_notes WHERE item_uuid = ?",
            (clean_uuid,),
        )
        if row is None:
            raise NoteNotFoundInProjection(clean_uuid)
        title = _clean(personal_title, MAX_PERSONAL_TITLE)
        note = _clean(personal_note, MAX_PERSONAL_NOTE)
        if not title and not note:
            raise ConflictInvalid("个人修正不能全空（标题或笔记至少一项）。")
        now = utc_now()
        await self._db.execute(
            "INSERT INTO obsidian_note_corrections (note_uuid, base_content_hash, personal_title, personal_note, updated_at)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(note_uuid) DO UPDATE SET base_content_hash = excluded.base_content_hash,"
            " personal_title = excluded.personal_title, personal_note = excluded.personal_note,"
            " updated_at = excluded.updated_at",
            (clean_uuid, str(row["content_hash"]), title, note, now),
        )
        return {
            "noteUuid": clean_uuid,
            "baseContentHash": str(row["content_hash"]),
            "personalTitle": title,
            "personalNote": note,
            "updatedAt": now,
        }

    async def list_corrections(self) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT c.note_uuid, c.base_content_hash, c.personal_title, c.personal_note, c.updated_at,"
            " n.content_hash AS current_hash, n.rel_path"
            " FROM obsidian_note_corrections c"
            " LEFT JOIN obsidian_notes n ON n.item_uuid = c.note_uuid"
            " ORDER BY c.updated_at DESC LIMIT ?",
            (_MAX_LISTED,),
        )
        return [
            {
                "noteUuid": str(row["note_uuid"]),
                "relPath": row["rel_path"],
                "baseContentHash": str(row["base_content_hash"]),
                "currentContentHash": row["current_hash"],
                "stale": row["current_hash"] is not None
                and str(row["current_hash"]) != str(row["base_content_hash"]),
                "personalTitle": str(row["personal_title"]),
                "personalNote": str(row["personal_note"]),
                "updatedAt": str(row["updated_at"]),
            }
            for row in rows
        ]

    async def delete_correction(self, note_uuid: str) -> bool:
        await self._db.migrate()
        deleted = await self._db.execute(
            "DELETE FROM obsidian_note_corrections WHERE note_uuid = ?",
            (str(note_uuid or "").strip().replace("library:", ""),),
        )
        return bool(deleted)

    # -- 检测 + 收件箱 + 解决 ---------------------------------------------

    async def detect(self) -> dict[str, Any]:
        """逐条对比 base hash vs 当前投影 hash → open 冲突快照。"""
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT c.note_uuid, c.base_content_hash, c.personal_title, c.personal_note,"
            " n.content_hash AS current_hash, n.title AS source_title, n.body_text"
            " FROM obsidian_note_corrections c"
            " JOIN obsidian_notes n ON n.item_uuid = c.note_uuid"
            " LIMIT ?",
            (_MAX_LISTED,),
        )
        opened = refreshed = unchanged = 0
        now = utc_now()
        for row in rows:
            current_hash = str(row["current_hash"] or "")
            if current_hash == str(row["base_content_hash"]):
                unchanged += 1
                continue
            existing = await self._db.fetch_one(
                "SELECT id FROM obsidian_sync_conflicts WHERE note_uuid = ? AND status = 'open'",
                (str(row["note_uuid"]),),
            )
            source_excerpt = str(row["body_text"] or "")[:_SOURCE_EXCERPT_CHARS]
            conflict_id = (
                str(existing["id"]) if existing is not None else str(_uuid.uuid4())
            )
            await self._db.execute(
                "INSERT INTO obsidian_sync_conflicts (id, note_uuid, base_content_hash, current_content_hash,"
                " source_title, source_excerpt, personal_title, personal_note, status, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)"
                " ON CONFLICT(id) DO UPDATE SET current_content_hash = excluded.current_content_hash,"
                " source_title = excluded.source_title, source_excerpt = excluded.source_excerpt",
                (
                    conflict_id,
                    str(row["note_uuid"]),
                    str(row["base_content_hash"]),
                    current_hash,
                    str(row["source_title"] or ""),
                    source_excerpt,
                    str(row["personal_title"] or ""),
                    str(row["personal_note"] or ""),
                    now,
                ),
            )
            if existing is None:
                opened += 1
            else:
                refreshed += 1
        return {
            "checked": len(rows),
            "opened": opened,
            "refreshed": refreshed,
            "unchanged": unchanged,
            "honestyNote": "冲突只读检测：个人修正层与源版本并存展示，解决由你显式二选一；源文件从未被改写。",
        }

    async def list_open(self) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT * FROM obsidian_sync_conflicts WHERE status = 'open'"
            " ORDER BY created_at DESC, id DESC LIMIT ?",
            (_MAX_LISTED,),
        )
        return [self._row(row) for row in rows]

    async def resolve(self, conflict_id: str, decision: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT * FROM obsidian_sync_conflicts WHERE id = ?",
            (str(conflict_id).strip(),),
        )
        if row is None:
            raise ConflictNotFound(conflict_id)
        if str(row["status"]) != "open":
            raise ConflictInvalid("该冲突已解决。")
        clean = str(decision or "").strip()
        if clean not in (DECISION_KEEP_INDEPENDENT, DECISION_ADOPT_SOURCE):
            raise ConflictInvalid("decision 必须是 keep_independent 或 adopt_source。")
        now = utc_now()
        if clean == DECISION_KEEP_INDEPENDENT:
            # 保留独立层：修正重定基到当前源版本（独立层继续生效）。
            await self._db.execute(
                "UPDATE obsidian_note_corrections SET base_content_hash = ?, updated_at = ? WHERE note_uuid = ?",
                (str(row["current_content_hash"]), now, str(row["note_uuid"])),
            )
        else:
            # 采用源版本：删除个人修正层。
            await self._db.execute(
                "DELETE FROM obsidian_note_corrections WHERE note_uuid = ?",
                (str(row["note_uuid"]),),
            )
        await self._db.execute(
            "UPDATE obsidian_sync_conflicts SET status = ?, resolved_at = ? WHERE id = ?",
            (
                "kept_independent" if clean == DECISION_KEEP_INDEPENDENT else "adopted_source",
                now,
                str(conflict_id).strip(),
            ),
        )
        updated = await self._db.fetch_one(
            "SELECT * FROM obsidian_sync_conflicts WHERE id = ?",
            (str(conflict_id).strip(),),
        )
        return self._row(updated) if updated is not None else None

    async def history(self) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT * FROM obsidian_sync_conflicts WHERE status != 'open'"
            " ORDER BY resolved_at DESC, id DESC LIMIT ?",
            (_MAX_LISTED,),
        )
        return [self._row(row) for row in rows]

    @staticmethod
    def _row(row: Any) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "noteUuid": str(row["note_uuid"]),
            "baseContentHash": str(row["base_content_hash"]),
            "currentContentHash": str(row["current_content_hash"]),
            "source": {
                "title": str(row["source_title"] or ""),
                "excerpt": str(row["source_excerpt"] or ""),
            },
            "personal": {
                "title": str(row["personal_title"] or ""),
                "note": str(row["personal_note"] or ""),
            },
            "status": str(row["status"]),
            "createdAt": str(row["created_at"]),
            "resolvedAt": row["resolved_at"],
        }
