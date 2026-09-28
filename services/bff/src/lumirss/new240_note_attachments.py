"""NEW-240 笔记附件清单 —— 笔记上的本人小附件（查看/容量/移除留文字）。

- 附件是笔记的附加物：移除附件只删附件行——笔记正文
  （lumi_notes.content_md）永不被附件操作触碰（负向断言依赖）。
- 限额（应用层执行，诚实 422）：单文件 ≤256KB；每笔记总量 ≤1MB；
  每笔记 ≤10 个；同名附件拒绝（duplicate）。
- BLOB 内联在 per-user 库（本人选定的小附件，与笔记同库同隔离）。
"""

import uuid as _uuid
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

MAX_FILE_BYTES = 256 * 1024
MAX_NOTE_TOTAL_BYTES = 1024 * 1024
MAX_FILES_PER_NOTE = 10
MAX_FILENAME = 200


class NoteAttachmentInvalid(ValueError):
    """附件负载非法/超限（reason 稳定短码 + 中文消息）。"""


class NoteAttachmentNotFound(Exception):
    """笔记或附件不存在，映射 404。"""


class NoteAttachmentStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def _note_exists(self, note_id: str) -> bool:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT deleted_at FROM lumi_notes WHERE uuid = ?", (note_id,)
        )
        return row is not None and row["deleted_at"] is None

    async def usage(self, note_id: str) -> dict[str, int]:
        row = await self._db.fetch_one(
            "SELECT COUNT(*) AS n, COALESCE(SUM(size_bytes), 0) AS total FROM note_attachments WHERE note_id = ?",
            (note_id,),
        )
        return {
            "count": int(row["n"]) if row else 0,
            "totalBytes": int(row["total"]) if row else 0,
            "fileCapBytes": MAX_FILE_BYTES,
            "noteCapBytes": MAX_NOTE_TOTAL_BYTES,
            "fileCapCount": MAX_FILES_PER_NOTE,
        }

    async def add(
        self,
        note_id: str,
        *,
        filename: str,
        mime_type: str,
        content: bytes,
    ) -> dict[str, Any]:
        if not await self._note_exists(note_id):
            raise NoteAttachmentNotFound(note_id)
        clean_name = str(filename or "").strip()
        if not clean_name:
            raise NoteAttachmentInvalid("文件名不能为空。")
        if len(clean_name) > MAX_FILENAME:
            raise NoteAttachmentInvalid(f"文件名过长（≤{MAX_FILENAME} 字符）。")
        if not isinstance(content, (bytes, bytearray)) or len(content) == 0:
            raise NoteAttachmentInvalid("附件内容不能为空。")
        size = len(content)
        if size > MAX_FILE_BYTES:
            raise NoteAttachmentInvalid(
                f"单个附件过大（≤{MAX_FILE_BYTES // 1024}KB）。"
            )
        usage = await self.usage(note_id)
        if usage["count"] >= MAX_FILES_PER_NOTE:
            raise NoteAttachmentInvalid(
                f"每条笔记最多 {MAX_FILES_PER_NOTE} 个附件。"
            )
        if usage["totalBytes"] + size > MAX_NOTE_TOTAL_BYTES:
            raise NoteAttachmentInvalid(
                f"笔记附件总量超出上限（≤{MAX_NOTE_TOTAL_BYTES // 1024}KB）。"
            )
        dup = await self._db.fetch_one(
            "SELECT id FROM note_attachments WHERE note_id = ? AND filename = ?",
            (note_id, clean_name),
        )
        if dup is not None:
            raise NoteAttachmentInvalid("同名附件已存在。")
        attachment_id = str(_uuid.uuid4())
        mime = str(mime_type or "").strip() or "application/octet-stream"
        await self._db.execute(
            "INSERT INTO note_attachments (id, note_id, filename, mime_type, size_bytes, content, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (attachment_id, note_id, clean_name, mime, size, bytes(content), utc_now()),
        )
        return {
            "id": attachment_id,
            "noteId": note_id,
            "filename": clean_name,
            "mimeType": mime,
            "sizeBytes": size,
        }

    async def list_attachments(self, note_id: str) -> dict[str, Any]:
        if not await self._note_exists(note_id):
            raise NoteAttachmentNotFound(note_id)
        rows = await self._db.fetch_all(
            "SELECT id, filename, mime_type, size_bytes, created_at FROM note_attachments "
            "WHERE note_id = ? ORDER BY created_at ASC, rowid ASC",
            (note_id,),
        )
        usage = await self.usage(note_id)
        return {
            "noteId": note_id,
            "items": [
                {
                    "id": str(row["id"]),
                    "filename": str(row["filename"]),
                    "mimeType": str(row["mime_type"]),
                    "sizeBytes": int(row["size_bytes"]),
                    "createdAt": str(row["created_at"]),
                }
                for row in rows
            ],
            "usage": usage,
        }

    async def get_content(self, note_id: str, attachment_id: str) -> dict[str, Any]:
        row = await self._db.fetch_one(
            "SELECT filename, mime_type, size_bytes, content FROM note_attachments WHERE id = ? AND note_id = ?",
            (attachment_id, note_id),
        )
        if row is None:
            raise NoteAttachmentNotFound(attachment_id)
        return {
            "filename": str(row["filename"]),
            "mimeType": str(row["mime_type"]),
            "content": bytes(row["content"]),
        }

    async def remove(self, note_id: str, attachment_id: str) -> bool:
        """移除附件（笔记正文不动）。"""
        row = await self._db.fetch_one(
            "SELECT id FROM note_attachments WHERE id = ? AND note_id = ?",
            (attachment_id, note_id),
        )
        if row is None:
            return False
        await self._db.execute(
            "DELETE FROM note_attachments WHERE id = ?", (attachment_id,)
        )
        return True
