"""N125 邮件附件的有界存储（mail_attachments，0102）。

策略（ingest 时执行，双重判定 = 扩展名 + MIME）：

- 放行：pdf、图片（png/jpeg/gif/webp/bmp）、文本（txt/csv/md/ics）、
  office 文档（doc/docx/xls/xlsx/ppt/pptx/odt/ods/odp）；
- 拒绝：脚本与可执行类型（.exe/.msi/.bat/.cmd/.sh/.ps1/.js/.mjs/.vbs/
  .jar/.py/.html/.htm/.svg 等，含对应脚本型 MIME）——绝不存盘；
- 其余未知类型一律拒绝（allowlist 语义，宁可少存不少存危险物）；
- 单文件 >5MB → skipped_oversize；每封 >20 个 → 其余 skipped_limit。

下载走 GET /api/v1/mail/attachments/{id}：Content-Disposition:
attachment（绝不内联渲染）、按存储 size 原样回放、跨用户同型 404
（每用户独立数据库 + 按 id 精确匹配，不存在即 404，无存在性泄露）。
"""

import re
import uuid
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024
MAX_ATTACHMENTS_PER_MAIL = 20


def sanitize_attachment_name(name: str) -> str:
    """附件名净化展示（去尖括号/引号/控制符，限长）——名字只作展示与
    Content-Disposition 回显，绝不进入 HTML/Atom 渲染面。"""
    cleaned = re.sub(r"[<>&\"'\x00-\x1f]", "_", str(name))
    return cleaned[:120] or "(unnamed)"

# 扩展名 → 放行 MIME 白名单（二者须同时命中才存盘）。
_ALLOWED: dict[str, set[str]] = {
    ".pdf": {"application/pdf"},
    ".png": {"image/png"},
    ".jpg": {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
    ".gif": {"image/gif"},
    ".webp": {"image/webp"},
    ".bmp": {"image/bmp"},
    ".txt": {"text/plain"},
    ".csv": {"text/csv", "text/plain"},
    ".md": {"text/markdown", "text/plain"},
    ".ics": {"text/calendar", "text/plain"},
    ".doc": {"application/msword"},
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    },
    ".xls": {"application/vnd.ms-excel"},
    ".xlsx": {
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    },
    ".ppt": {"application/vnd.ms-powerpoint"},
    ".pptx": {
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    },
    ".odt": {"application/vnd.oasis.opendocument.text"},
    ".ods": {"application/vnd.oasis.opendocument.spreadsheet"},
    ".odp": {"application/vnd.oasis.opendocument.presentation"},
}


class MailAttachmentDenied(Exception):
    """附件被拒绝（扩展名或 MIME 不在放行名单）。不允许出现在存储里，
    仅用于把「拒绝」与「超限」区分成可测试的内部信号。"""


class MailAttachmentNotFound(Exception):
    """附件不存在（跨用户/错误 id 同型 404，不泄露存在性）。"""


def classify_attachment(filename: str, mime: str) -> str | None:
    """返回放行的规范化 MIME，拒绝时返回 None（allowlist 语义）。

    脚本/可执行类型（.exe/.sh/.js/.html 等）显式落在名单外——无论
    MIME 怎么声明，扩展名不命中即拒绝（双重判定取交集）。"""
    name = str(filename or "").strip().lower()
    dot = name.rfind(".")
    ext = name[dot:] if dot >= 0 else ""
    allowed_mimes = _ALLOWED.get(ext)
    if not allowed_mimes:
        return None
    clean_mime = str(mime or "").split(";")[0].strip().lower()
    if clean_mime in allowed_mimes:
        return clean_mime
    # 宽容文本类：服务器可能声明 application/octet-stream，但扩展名
    # 是纯文本类型且 MIME 声明为文本 → 按声明存；脚本型扩展名永远
    # 不会到这里（不在 _ALLOWED）。
    if ext in (".txt", ".csv", ".md", ".ics") and clean_mime.startswith("text/"):
        return clean_mime
    return None


class MailAttachmentStore:
    """mail_attachments 行级读写（ingest 写入；下载点读）。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    def save(
        self,
        conn,
        *,
        list_uuid: str,
        message_id: str,
        filename: str,
        mime: str,
        content: bytes,
    ) -> str:
        """在同一 ingest 事务里写入附件行（SQL 为单行内联字面量；同步 —
        由 ingest 的同步事务闭包调用，随事务一起提交/回滚）。"""
        attachment_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO mail_attachments (id, list_uuid, message_id, filename, mime, size, content, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                attachment_id,
                list_uuid,
                message_id,
                sanitize_attachment_name(filename),
                mime,
                len(content),
                content,
                utc_now(),
            ),
        )
        return attachment_id

    async def get(self, attachment_id: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, list_uuid, message_id, filename, mime, size, content, created_at FROM mail_attachments WHERE id = ?",
            (attachment_id,),
        )
        return dict(row) if row is not None else None

    async def list_for_message(
        self, list_uuid: str, message_id: str
    ) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, filename, mime, size, created_at FROM mail_attachments WHERE list_uuid = ? AND message_id = ? ORDER BY created_at ASC, id ASC",
            (list_uuid, message_id),
        )
        return [dict(row) for row in rows]

    async def delete_for_list(self, list_uuid: str) -> None:
        """删除列表时连带清理附件 BLOB（bridge delete_list 调用）。"""
        await self._db.migrate()
        await self._db.execute(
            "DELETE FROM mail_attachments WHERE list_uuid = ?", (list_uuid,)
        )
