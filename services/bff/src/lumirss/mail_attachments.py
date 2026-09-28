"""N125 邮件附件的有界存储（mail_attachments，0102）。

策略（ingest 时执行，三重判定 = 扩展名 + MIME + 实际内容魔法字节）：

- 放行：pdf、图片（png/jpeg/gif/webp/bmp）、文本（txt/csv/md/ics）、
  office 文档（doc/docx/xls/xlsx/ppt/pptx/odt/ods/odp）；
- 拒绝：脚本与可执行类型（.exe/.msi/.bat/.cmd/.sh/.ps1/.js/.mjs/.vbs/
  .jar/.py/.html/.htm/.svg 等，含对应脚本型 MIME）——绝不存盘；
- 其余未知类型一律拒绝（allowlist 语义，宁可少存不少存危险物）；
- FIX-322：放行名单内的二进制类型再按魔法字节核对实际内容（pdf/
  图片/OLE2/ZIP 容器各自的特征头；文本类拒绝 HTML 文档标记开头），
  改名/改声明的不一致样本按 skipped_mismatch 安全拒绝并给出原因；
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


# FIX-322：放行的二进制类型按魔法字节核对实际内容——扩展名/声明 MIME
# 都由发送方自证，改名/改声明的不一致样本（如 HTML 改名 .png）必须在
# 存盘前拦下。键为 _ALLOWED 的扩展名，值为 (magic 前缀们, 类型说明)。
_BINARY_MAGIC: dict[str, tuple[tuple[bytes, ...], str]] = {
    ".pdf": ((b"%PDF-",), "PDF"),
    ".png": ((b"\x89PNG\r\n\x1a\n",), "PNG 图片"),
    ".jpg": ((b"\xff\xd8\xff",), "JPEG 图片"),
    ".jpeg": ((b"\xff\xd8\xff",), "JPEG 图片"),
    ".gif": ((b"GIF87a", b"GIF89a"), "GIF 图片"),
    ".webp": ((b"RIFF",), "WebP 图片"),
    ".bmp": ((b"BM",), "BMP 图片"),
    ".doc": (
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",),
        "Word 文档",
    ),
    ".xls": ((b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",), "Excel 工作簿"),
    ".ppt": ((b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",), "PowerPoint 演示"),
    ".docx": (
        (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"),
        "Word 文档",
    ),
    ".xlsx": (
        (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"),
        "Excel 工作簿",
    ),
    ".pptx": (
        (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"),
        "PowerPoint 演示",
    ),
    ".odt": ((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"), "ODF 文档"),
    ".ods": ((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"), "ODF 表格"),
    ".odp": ((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"), "ODF 演示"),
}

# WebP 的 RIFF 头需要核对 8..12 字节的 WEBP 标记（RIFF 容器复用）。
def _matches_magic(ext: str, content: bytes) -> bool:
    magics, _label = _BINARY_MAGIC[ext]
    if ext == ".webp":
        return content[:4] == b"RIFF" and content[8:12] == b"WEBP"
    return any(content.startswith(magic) for magic in magics)


# 文本类（txt/csv/md/ics）的嗅探规则：拒绝以 HTML 文档标记开头的内容
# ——「不把 HTML 当文本/图片嵌入」；其余文本原样放行（下载始终是
# Content-Disposition: attachment，不进入渲染面）。
_HTML_MARKERS = (b"<!doctype html", b"<html")


def attachment_content_mismatch(filename: str, content: bytes) -> str | None:
    """内容嗅探：返回不一致原因（拒绝理由），None = 与声明类型一致。

    只对「存在明确魔法字节的类型」做硬核对；文本类做 HTML 标记检查。
    嗅探失败是安全拒绝（宁可少存不少存危险物），原因如实进入 ingest
    的附件清单（status=skipped_mismatch）。"""
    name = str(filename or "").strip().lower()
    dot = name.rfind(".")
    ext = name[dot:] if dot >= 0 else ""
    if ext in _BINARY_MAGIC:
        if not _matches_magic(ext, content):
            _label = _BINARY_MAGIC[ext][1]
            return f"附件内容与声明的类型不一致（实际内容不是{_label}），未保存。"
        return None
    lowered = content[:512].lower()
    if any(lowered.startswith(marker) for marker in _HTML_MARKERS):
        return "附件内容与声明的类型不一致（实际内容是 HTML 文档），未保存。"
    return None


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
