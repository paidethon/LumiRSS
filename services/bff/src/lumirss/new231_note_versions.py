"""NEW-231 笔记修订对照 —— 显式版本快照 / 文字差异 / 恢复（留恢复记录）。

- 快照：用户对某条本人笔记手动 snapshot（origin='manual'）；恢复前
  自动把当前版推入快照（origin='pre_restore'）——任何恢复都不销毁
  历史，旧版永远可再找回。
- 差异：difflib.unified_diff 逐行对比两个版本（from/to 可为
  'current'=当前正文），只读、零写入；返回统一 diff 文本与
  增/删行计数（诚实计数，不做语义改写）。
- 恢复：把选中版本的 title+content_md 写回笔记，恢复动作进
  note_restore_log（只追加）；恢复后重写搜索投影（复用 F090 同一
  writer 惯例），投影与正文永远一致。

边界：per-user 库（RoutingDatabase）——版本/恢复记录天然隔离，
本人笔记的版本只可能是本人的。
"""

import difflib
import sqlite3
import uuid as _uuid
from typing import Any

from lumirss.db_tx import transaction
from lumirss.lumi_notes import content_hash_of
from lumirss.note_sections import empty_sections
from lumirss.search_library import upsert_search_row
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_SNAPSHOTS = 100  # 每条笔记快照上限（更早的按 created_at 淘汰）


class NoteVersionInvalid(ValueError):
    """版本操作负载非法（映射 422）。"""


class NoteVersionNotFound(Exception):
    """笔记或版本不存在（映射 404）。"""


class NoteVersionStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    # -- 内部 ------------------------------------------------------------

    async def _note_row(self, note_id: str) -> dict[str, Any]:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT uuid, title, content_md, sections_json, created_at, updated_at, deleted_at "
            "FROM lumi_notes WHERE uuid = ?",
            (note_id,),
        )
        if row is None or row["deleted_at"] is not None:
            raise NoteVersionNotFound(note_id)
        return dict(row)

    def _cleanup(self, conn: sqlite3.Connection, note_id: str) -> None:
        """cap 100：只保留最近 100 条快照（created_at 降序，rowid 定平局）。"""
        conn.execute(
            "DELETE FROM note_versions WHERE note_id = ? AND rowid NOT IN "
            "(SELECT rowid FROM note_versions WHERE note_id = ? ORDER BY created_at DESC, rowid DESC LIMIT ?)",
            (note_id, note_id, _MAX_SNAPSHOTS),
        )

    # -- 快照 ------------------------------------------------------------

    async def snapshot(self, note_id: str) -> dict[str, Any]:
        """把笔记当前完整内容存为一版（origin='manual'）。"""
        note = await self._note_row(note_id)
        version_id = str(_uuid.uuid4())
        now = utc_now()

        def _tx(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO note_versions (id, note_id, title, content_md, origin, created_at) VALUES (?, ?, ?, ?, 'manual', ?)",
                (version_id, note_id, str(note["title"]), str(note["content_md"]), now),
            )
            self._cleanup(conn, note_id)

        await transaction(self._db, _tx)
        return {
            "id": version_id,
            "noteId": note_id,
            "title": str(note["title"]),
            "origin": "manual",
            "createdAt": now,
        }

    async def list_versions(self, note_id: str) -> dict[str, Any]:
        """版本列表（新→旧）+ 当前版摘要；current 也作为可比对象返回。"""
        note = await self._note_row(note_id)
        rows = await self._db.fetch_all(
            "SELECT id, title, origin, created_at FROM note_versions WHERE note_id = ? "
            "ORDER BY created_at DESC, rowid DESC",
            (note_id,),
        )
        return {
            "noteId": note_id,
            "current": {
                "ref": "current",
                "title": str(note["title"]),
                "updatedAt": str(note["updated_at"]),
            },
            "items": [
                {
                    "id": str(row["id"]),
                    "title": str(row["title"]),
                    "origin": str(row["origin"] or "manual"),
                    "createdAt": str(row["created_at"]),
                }
                for row in rows
            ],
        }

    async def get_version(self, note_id: str, version_ref: str) -> dict[str, Any]:
        """取一个版本（version_ref='current' → 当前正文）。"""
        if version_ref == "current":
            note = await self._note_row(note_id)
            return {
                "ref": "current",
                "noteId": note_id,
                "title": str(note["title"]),
                "contentMd": str(note["content_md"]),
            }
        row = await self._db.fetch_one(
            "SELECT id, note_id, title, content_md, origin, created_at FROM note_versions WHERE id = ? AND note_id = ?",
            (version_ref, note_id),
        )
        if row is None:
            raise NoteVersionNotFound(version_ref)
        return {
            "ref": str(row["id"]),
            "noteId": str(row["note_id"]),
            "title": str(row["title"]),
            "contentMd": str(row["content_md"]),
            "origin": str(row["origin"] or "manual"),
            "createdAt": str(row["created_at"]),
        }

    # -- 差异 ------------------------------------------------------------

    @staticmethod
    def diff_versions(
        from_version: dict[str, Any], to_version: dict[str, Any]
    ) -> dict[str, Any]:
        """两个版本的逐行统一 diff + 增/删行计数（纯函数，零 IO）。"""
        from_lines = str(from_version["contentMd"]).splitlines(keepends=True)
        to_lines = str(to_version["contentMd"]).splitlines(keepends=True)
        unified = list(
            difflib.unified_diff(
                from_lines,
                to_lines,
                fromfile=f"version:{from_version['ref']}",
                tofile=f"version:{to_version['ref']}",
            )
        )
        added = 0
        removed = 0
        for line in unified[2:]:  # 跳过 ---/+++ 头
            if line.startswith("+"):
                added += 1
            elif line.startswith("-"):
                removed += 1
        return {
            "unified": "".join(unified),
            "addedLines": added,
            "removedLines": removed,
            "identical": from_version["contentMd"] == to_version["contentMd"],
        }

    # -- 恢复 ------------------------------------------------------------

    async def restore(self, note_id: str, version_ref: str) -> dict[str, Any]:
        """恢复某版为当前内容。顺序（保历史，绝不覆盖）：

        1. 当前版先自动快照（origin='pre_restore'）；
        2. 写回选中版本的 title+content_md（sections 清空为三空栏——
           版本快照不含分栏，诚实归零，不伪造旧分栏）；
        3. note_restore_log 追加恢复记录；
        4. 搜索投影重写（复用 F090 writer）。"""
        target = await self.get_version(note_id, version_ref)
        note = await self._note_row(note_id)
        restored_at = utc_now()
        pre_id = str(_uuid.uuid4())
        log_id = str(_uuid.uuid4())
        clean_content = str(target["contentMd"])
        clean_title = str(target["title"])
        sections = empty_sections()

        def _tx(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO note_versions (id, note_id, title, content_md, origin, created_at) VALUES (?, ?, ?, ?, 'pre_restore', ?)",
                (pre_id, note_id, str(note["title"]), str(note["content_md"]), restored_at),
            )
            self._cleanup(conn, note_id)
            conn.execute(
                "UPDATE lumi_notes SET title = ?, content_md = ?, sections_json = NULL, content_hash = ?, updated_at = ? WHERE uuid = ?",
                (clean_title, clean_content, content_hash_of(clean_content), restored_at, note_id),
            )
            conn.execute(
                "INSERT INTO note_restore_log (id, note_id, version_id, version_origin, restored_at) VALUES (?, ?, ?, ?, ?)",
                (log_id, note_id, str(target["ref"]), str(target.get("origin") or "manual"), restored_at),
            )
            upsert_search_row(
                conn,
                ref=f"note:{note_id}",
                kind="note",
                title=clean_title,
                body=clean_content[:4000],
                url=None,
                now=restored_at,
            )

        await transaction(self._db, _tx)
        return {
            "noteId": note_id,
            "restoredFrom": str(target["ref"]),
            "restoredFromOrigin": str(target.get("origin") or "manual"),
            "preRestoreVersionId": pre_id,
            "title": clean_title,
            "contentMd": clean_content,
            "sections": sections,
            "restoredAt": restored_at,
        }

    async def restore_log(self, note_id: str) -> list[dict[str, Any]]:
        """恢复记录（新→旧，只追加台账）。"""
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, version_id, version_origin, restored_at FROM note_restore_log "
            "WHERE note_id = ? ORDER BY restored_at DESC, rowid DESC",
            (note_id,),
        )
        return [
            {
                "id": str(row["id"]),
                "versionId": str(row["version_id"]),
                "versionOrigin": str(row["version_origin"]),
                "restoredAt": str(row["restored_at"]),
            }
            for row in rows
        ]
