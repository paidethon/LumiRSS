"""F090 Lumi 笔记全生命周期 —— 创建 / 读取 / 更新（乐观锁）/ 软删 / 恢复。

- 搜索接线与 knowledge_cards 同模式：ref=note:{id} 写入 search_library
  （kind='note'），软删即移除投影、恢复即重写；
- PATCH 带 baseUpdatedAt 乐观锁：不一致 → 409 note_conflict；
- 软删进回收站（lumi_notes.deleted_at；trash 端点扩展 kind=note）；
- 笔记绝不写入 Obsidian Vault（本模块零文件 IO——负向断言依赖）。

本文件直接写站点 4 处（INSERT / UPDATE / 软删 / 恢复）。
"""

import sqlite3
from typing import Any

from lumirss.db_tx import transaction
from lumirss.itemref import new_library_uuid
from lumirss.lumi_notes import content_hash_of
from lumirss.search_library import LibrarySearchWriter
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_TITLE = 500
_MAX_CONTENT_BYTES = 100 * 1024


class NoteInvalid(ValueError):
    """笔记载荷非法（标题/正文长度/引用格式），映射 422。"""


class NoteConflict(Exception):
    """baseUpdatedAt 乐观锁冲突，映射 409。"""


class NoteNotFound(Exception):
    """笔记不存在（或已软删），映射 404。"""


class NoteLifecycleStore:
    def __init__(self, db: Database) -> None:
        self._db = db
        self._search = LibrarySearchWriter(db)

    @staticmethod
    def _validate_title(title: str) -> str:
        clean = str(title or "").strip()
        if not clean:
            raise NoteInvalid("标题不能为空。")
        if len(clean) > _MAX_TITLE:
            raise NoteInvalid("标题过长（≤500 字符）。")
        return clean

    @staticmethod
    def _validate_content(content_md: str) -> str:
        if not isinstance(content_md, str):
            raise NoteInvalid("contentMd 必须是字符串。")
        if len(content_md.encode("utf-8")) > _MAX_CONTENT_BYTES:
            raise NoteInvalid("contentMd 超过 100KB 上限。")
        return content_md

    def _index(self, conn: sqlite3.Connection, *, note_id: str, title: str, content: str, now: str) -> None:
        """事务内同步投影（同 upsert_search_row 惯例）。"""
        row = conn.execute(
            "SELECT ref FROM search_library WHERE ref = ?", (f"note:{note_id}",)
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO search_library (ref, kind, title, body, url, updated_at) VALUES (?, 'note', ?, ?, NULL, ?)",
                (f"note:{note_id}", title, content[:4000], now),
            )
        else:
            conn.execute(
                "UPDATE search_library SET kind = 'note', title = ?, body = ?, updated_at = ? WHERE ref = ?",
                (title, content[:4000], now, f"note:{note_id}"),
            )

    async def create_note(
        self, *, title: str, content_md: str, workspace_id: str | None
    ) -> dict[str, Any]:
        clean_title = self._validate_title(title)
        clean_content = self._validate_content(content_md)
        await self._db.migrate()
        note_id = new_library_uuid()
        now = utc_now()

        def _tx(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO lumi_notes (uuid, title, content_md, workspace_id, content_hash, source, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'manual', ?, ?)",
                (
                    note_id,
                    clean_title,
                    clean_content,
                    workspace_id,
                    content_hash_of(clean_content),
                    now,
                    now,
                ),
            )
            self._index(
                conn, note_id=note_id, title=clean_title, content=clean_content, now=now
            )

        await transaction(self._db, _tx)
        return {
            "uuid": note_id,
            "title": clean_title,
            "contentMd": clean_content,
            "workspaceId": workspace_id,
            "createdAt": now,
            "updatedAt": now,
        }

    async def get_note(self, note_id: str, *, include_deleted: bool = False) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT uuid, title, content_md, workspace_id, created_at, updated_at, deleted_at FROM lumi_notes WHERE uuid = ?",
            (note_id,),
        )
        if row is None:
            return None
        if row["deleted_at"] is not None and not include_deleted:
            return None
        return {
            "uuid": str(row["uuid"]),
            "title": str(row["title"]),
            "contentMd": str(row["content_md"]),
            "workspaceId": row["workspace_id"],
            "createdAt": str(row["created_at"]),
            "updatedAt": str(row["updated_at"]),
            "deletedAt": row["deleted_at"],
        }

    async def update_note(
        self,
        note_id: str,
        *,
        title: str | None,
        content_md: str | None,
        base_updated_at: str | None,
    ) -> dict[str, Any]:
        current = await self.get_note(note_id)
        if current is None:
            raise NoteNotFound(note_id)
        if (
            base_updated_at is not None
            and str(base_updated_at) != current["updatedAt"]
        ):
            raise NoteConflict("笔记已被其他编辑更新，请刷新后重试。")
        clean_title = (
            self._validate_title(title) if title is not None else current["title"]
        )
        clean_content = (
            self._validate_content(content_md)
            if content_md is not None
            else current["contentMd"]
        )
        now = utc_now()

        def _tx(conn: sqlite3.Connection) -> None:
            conn.execute(
                "UPDATE lumi_notes SET title = ?, content_md = ?, content_hash = ?, updated_at = ? WHERE uuid = ?",
                (
                    clean_title,
                    clean_content,
                    content_hash_of(clean_content),
                    now,
                    note_id,
                ),
            )
            self._index(
                conn, note_id=note_id, title=clean_title, content=clean_content, now=now
            )

        await transaction(self._db, _tx)
        return {
            "uuid": note_id,
            "title": clean_title,
            "contentMd": clean_content,
            "workspaceId": current["workspaceId"],
            "createdAt": current["createdAt"],
            "updatedAt": now,
        }

    async def soft_delete_note(self, note_id: str) -> bool:
        """软删（回收站 kind=note）+ 移除搜索投影。"""
        current = await self.get_note(note_id)
        if current is None:
            return False

        def _tx(conn: sqlite3.Connection) -> int:
            cursor = conn.execute(
                "UPDATE lumi_notes SET deleted_at = ? WHERE uuid = ? AND deleted_at IS NULL",
                (utc_now(), note_id),
            )
            if cursor.rowcount:
                conn.execute(
                    "DELETE FROM search_library WHERE ref = ?", (f"note:{note_id}",)
                )
            return cursor.rowcount

        return bool(await transaction(self._db, _tx))

    async def restore_note(self, note_id: str) -> bool:
        current = await self.get_note(note_id, include_deleted=True)
        if current is None or current["deletedAt"] is None:
            return False

        def _tx(conn: sqlite3.Connection) -> int:
            cursor = conn.execute(
                "UPDATE lumi_notes SET deleted_at = NULL WHERE uuid = ? AND deleted_at IS NOT NULL",
                (note_id,),
            )
            if cursor.rowcount:
                self._index(
                    conn,
                    note_id=note_id,
                    title=current["title"],
                    content=current["contentMd"],
                    now=utc_now(),
                )
            return cursor.rowcount

        return bool(await transaction(self._db, _tx))
