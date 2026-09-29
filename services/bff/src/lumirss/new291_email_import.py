"""NEW-291 EML 拖入阅读 —— 用户上传自己的邮件文件，解析为主题、
发件信息与正文俱全的资料条目，并给出附件处理预览。

诚实口径（硬规则）：

- 解析只用 stdlib ``email``（policy.default）：主题/发件人/收件人/日期/
  正文/附件元数据来自文件真实头部与 MIME 结构，解析失败按「单文件
  失败」如实入结果，绝不静默丢文件；
- 上传的 EML 是不可信内容：body_html 只存 ``mail_sanitize`` 净化后的
  版本（脚本/样式/远程图片全部剥离），头部字段一律按纯文本处理；
- 大小封顶：单文件 >MAX_EML_BYTES 拒绝；单附件 >MAX_ATTACHMENT_STORED
  只存元数据并如实标 ``stored=false``（不假装存了内容）；
- 本组端点零网络：导入只是解析入库，绝不发信、绝不取远程资源。

per-user：表在 per-user 库（RoutingDatabase），A 导入的邮件对 B 不可见。
"""

import hashlib
import json
import uuid
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr
from typing import Any

from lumirss.mail_sanitize import html_to_text, sanitize_email_html
from lumirss.storage import Database
from lumirss.util import utc_now

MAX_EML_BYTES = 4 * 1024 * 1024  # 与平台请求体上限同量级（诚实口径）
MAX_ATTACHMENT_STORED = 2 * 1024 * 1024
MAX_BATCH_FILES = 20
_MAX_BODY_CHARS = 2 * 1024 * 1024
_MAX_HEADERS = 100
_MAX_HEADER_VALUE = 2000
_SNIPPET_CHARS = 160

HONESTY_NOTE = (
    "导入只解析你上传的文件内容入库（净化后的正文与附件元数据），"
    "LumiRSS 不发信、不访问远程资源；超出大小上限的附件只保留元数据。"
)


class EmailImportInvalid(ValueError):
    """导入负载非法（映射 422）。"""


def normalize_message_id(raw: str | None) -> str:
    """去尖括号与空白的 Message-ID（引用链匹配用；保留大小写）。"""
    return (raw or "").strip().strip("<>").strip()


def _bounded_headers(msg: Any) -> dict[str, str]:
    headers: dict[str, str] = {}
    for key, value in msg.items():
        if len(headers) >= _MAX_HEADERS:
            break
        try:
            text = str(value)
        except Exception:  # noqa: BLE001 — 坏头部退化为占位，不毁导入
            text = "<不可解码头部>"
        headers[str(key)] = text[:_MAX_HEADER_VALUE]
    return headers


def _body_parts(msg: Any) -> tuple[str, str]:
    """(body_text, body_html)；html 一律先过 mail_sanitize 边界。"""
    body_text = ""
    body_html = ""
    try:
        body = msg.get_body(preferencelist=("plain", "html"))
    except Exception:  # noqa: BLE001 — 结构异常按空正文处理
        body = None
    if body is not None:
        try:
            content = body.get_content()
        except Exception:  # noqa: BLE001
            content = ""
        if not isinstance(content, str):
            content = str(content)
        content = content[:_MAX_BODY_CHARS]
        if body.get_content_type() == "text/html":
            body_html = sanitize_email_html(content)
            body_text = html_to_text(content)
        else:
            body_text = content
    return body_text, body_html


def _iter_attachments(msg: Any) -> list[Any]:
    try:
        return list(msg.iter_attachments())
    except Exception:  # noqa: BLE001
        return []


def parse_eml(raw: bytes) -> dict[str, Any]:
    """把一份 EML 字节解析为资料条目字段（纯函数，不落库）。

    抛 EmailImportInvalid = 该文件不可读为邮件（诚实失败，不硬造条目）。
    """
    if len(raw) > MAX_EML_BYTES:
        raise EmailImportInvalid(
            f"文件超过大小上限（{MAX_EML_BYTES // (1024 * 1024)} MiB）。"
        )
    try:
        msg = BytesParser(policy=policy.default).parsebytes(raw)
    except Exception as exc:  # noqa: BLE001 — 解析器异常归一为导入失败
        raise EmailImportInvalid(f"无法解析为邮件：{exc}") from exc

    subject = str(msg["Subject"] or "")
    from_name, from_addr = parseaddr(str(msg["From"] or ""))
    message_id = normalize_message_id(str(msg["Message-ID"] or ""))
    body_text, body_html = _body_parts(msg)
    headers = _bounded_headers(msg)
    if not headers:
        # 没有任何头部 = 随手存的文本，不是邮件（诚实拒绝，不硬造条目）。
        raise EmailImportInvalid("文件里没有邮件头部，不是一封可识别的邮件。")
    if not any((subject, from_addr, message_id, body_text, body_html)):
        raise EmailImportInvalid("文件里没有可识别的主题、发件人、Message-ID 或正文。")

    attachments: list[dict[str, Any]] = []
    payloads: list[bytes | None] = []
    for part in _iter_attachments(msg):
        filename = str(part.get_filename() or "未命名附件")
        try:
            decoded = part.get_payload(decode=True)
        except Exception:  # noqa: BLE001
            decoded = None
        payload = decoded if isinstance(decoded, bytes) else b""
        payloads.append(payload if payload else None)
        attachments.append(
            {
                "filename": filename[:255],
                "contentType": str(part.get_content_type()),
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )

    snippet = " ".join(body_text.split())[:_SNIPPET_CHARS]
    return {
        "message_id": message_id,
        "subject": subject[:500],
        "from_name": from_name[:200],
        "from_addr": from_addr[:320],
        "to_addrs": str(msg["To"] or "")[:2000],
        "date_hdr": str(msg["Date"] or "")[:200],
        "snippet": snippet,
        "body_text": body_text,
        "body_html": body_html,
        "headers": headers,
        "attachments": attachments,
        "_payloads": payloads,
        "body_digest": hashlib.sha256(body_text.encode("utf-8")).hexdigest(),
        "raw_bytes": len(raw),
    }


async def insert_material(
    db: Database,
    parsed: dict[str, Any],
    *,
    tags: list[str] | None = None,
    source_label: str = "",
    import_kind: str = "manual",
) -> str:
    """写入一条资料条目（含附件字节），返回条目 id。

    供本模块导入流水线与后续冲突解决（NEW-298）共用同一条写入路径。
    """
    material_id = f"eml-{uuid.uuid4().hex[:20]}"
    now = utc_now()
    await db.execute(
        "INSERT INTO email_materials (id, message_id, subject, from_name,"
        " from_addr, to_addrs, date_hdr, snippet, body_text, body_html,"
        " headers_json, attachments_json, tags_json, body_digest, raw_bytes,"
        " source_label, import_kind, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            material_id,
            parsed["message_id"],
            parsed["subject"],
            parsed["from_name"],
            parsed["from_addr"],
            parsed["to_addrs"],
            parsed["date_hdr"],
            parsed["snippet"],
            parsed["body_text"],
            parsed["body_html"],
            json.dumps(parsed["headers"], ensure_ascii=False),
            json.dumps(parsed["attachments"], ensure_ascii=False),
            json.dumps(tags or [], ensure_ascii=False),
            parsed["body_digest"],
            int(parsed["raw_bytes"]),
            source_label,
            import_kind,
            now,
        ),
    )
    payloads = parsed.get("_payloads")
    for ord_, att in enumerate(parsed["attachments"]):
        blob: bytes | None = None
        if isinstance(payloads, list) and ord_ < len(payloads):
            candidate = payloads[ord_]
            if isinstance(candidate, bytes) and candidate:
                blob = candidate
        stored = blob is not None and len(blob) <= MAX_ATTACHMENT_STORED
        await db.execute(
            "INSERT INTO email_attachment_blobs (id, material_id, ord,"
            " filename, content_type, size, sha256, stored, data, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                f"eab-{uuid.uuid4().hex[:20]}",
                material_id,
                ord_,
                att["filename"],
                att["contentType"],
                att["size"],
                att["sha256"],
                1 if stored else 0,
                blob if stored else None,
                now,
            ),
        )
    return material_id


def _clean_files(raw_files: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_files, list) or not raw_files:
        raise EmailImportInvalid("至少提供一个 EML 文件。")
    if len(raw_files) > MAX_BATCH_FILES:
        raise EmailImportInvalid(f"单批最多 {MAX_BATCH_FILES} 个文件。")
    files: list[dict[str, Any]] = []
    for index, file in enumerate(raw_files):
        if not isinstance(file, dict):
            raise EmailImportInvalid("files 的元素必须是对象。")
        filename = str(file.get("filename") or f"邮件-{index + 1}.eml")[:255]
        content = file.get("content")
        if not isinstance(content, str) or not content:
            raise EmailImportInvalid(f"「{filename}」缺少文件内容。")
        files.append({"filename": filename, "content": content})
    return files


class EmailMaterialStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def import_files(self, raw_files: Any) -> dict[str, Any]:
        """导入一批 EML 文件；逐文件给出 imported/failed 结果。

        单文件解析失败只影响该文件（failed 里如实给原因），不毁整批。
        """
        files = _clean_files(raw_files)
        await self._db.migrate()
        imported: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        for index, file in enumerate(files):
            filename = str(file.get("filename") or f"邮件-{index + 1}.eml")
            content = file.get("content")
            if not isinstance(content, str) or not content:
                failed.append({"filename": filename, "reason": "文件内容为空。"})
                continue
            raw = content.encode("utf-8")
            try:
                parsed = parse_eml(raw)
            except EmailImportInvalid as exc:
                failed.append({"filename": filename, "reason": str(exc)})
                continue
            material_id = await insert_material(self._db, parsed)
            imported.append(
                {
                    "id": material_id,
                    "filename": filename,
                    "subject": parsed["subject"],
                    "fromAddr": parsed["from_addr"],
                    "snippet": parsed["snippet"],
                    "attachments": parsed["attachments"],
                    "messageId": parsed["message_id"],
                }
            )
        return {
            "imported": imported,
            "failed": failed,
            "honestyNote": HONESTY_NOTE,
        }

    async def list_materials(
        self, *, source: str = "", limit: int = 50
    ) -> dict[str, Any]:
        await self._db.migrate()
        limit = max(1, min(limit, 200))
        rows = await self._db.fetch_all(
            "SELECT id, message_id, subject, from_name, from_addr, to_addrs,"
            " date_hdr, snippet, source_label, tags_json, attachments_json,"
            " raw_bytes, created_at FROM email_materials"
            " ORDER BY created_at DESC, id DESC LIMIT ?",
            (limit,),
        )
        items = []
        for row in rows:
            item = self._row_summary(row)
            if source and item["sourceLabel"] != source:
                continue
            items.append(item)
        return {"items": items, "total": len(items), "limit": limit}

    def _row_summary(self, row: Any) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "messageId": str(row["message_id"]),
            "subject": str(row["subject"]),
            "fromName": str(row["from_name"]),
            "fromAddr": str(row["from_addr"]),
            "to": str(row["to_addrs"]),
            "date": str(row["date_hdr"]),
            "snippet": str(row["snippet"]),
            "sourceLabel": str(row["source_label"]),
            "tags": json.loads(str(row["tags_json"] or "[]")),
            "attachments": json.loads(str(row["attachments_json"] or "[]")),
            "rawBytes": int(row["raw_bytes"]),
            "createdAt": str(row["created_at"]),
        }

    async def get_material(self, material_id: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT * FROM email_materials WHERE id = ?", (material_id,)
        )
        if row is None:
            return None
        view = self._row_summary(row)
        view["bodyText"] = str(row["body_text"])
        view["bodyHtmlSanitized"] = str(row["body_html"])
        view["headers"] = json.loads(str(row["headers_json"] or "{}"))
        view["bodyDigest"] = str(row["body_digest"])
        view["importKind"] = str(row["import_kind"])
        return view

    async def get_blob(self, material_id: str, ord_: int) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT * FROM email_attachment_blobs WHERE material_id = ? AND ord = ?",
            (material_id, ord_),
        )
        if row is None:
            return None
        return dict(row)
