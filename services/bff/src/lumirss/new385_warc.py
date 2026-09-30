"""NEW-385 WARC 档案索引导入 —— 对用户合法持有的 WARC 档案建立资源
索引和可选正文导入，限制解包体积与活动内容。

口径：

- 输入是用户文件（非网络）；原始字节 ≤3MiB（低于全局请求体上限），
  记录数 ≤5000；逐记录 Content-Length 超过单记录上限（512KiB）→
  只建索引元数据、不落正文（oversized，如实计数）；
- 解析是逐记录有界的：只读 WARC 头（bounded 行）+ 按声明的
  Content-Length 切片定位下一个记录；response 记录的 HTTP 头最多
  读 8KiB 且行数封顶——绝不把敌意超大 payload 整块展开成字符串；
- 索引字段：WARC-Target-URI / WARC-Type / WARC-Record-ID（原始
  标识原样保留）/ Content-Length / WARC-Payload-Digest / WARC-Date
  / HTTP 状态 / Content-Type；
- 活动内容：Content-Type 为 HTML/XHTML/JS（可执行或可携带脚本的
  类型）→ active_content=1，一律不落正文（FIX-328 模式：无活动
  内容入库）；其余 text/* 且用户显式选择「导入正文」才存正文，
  且 HTML 会先剥标签、单条截断 200KiB；
- 防重复：同一 batch 内同 target_uri+record_type 去重；跨批次不拦
  （台账批次可追溯）。

per-user：索引落在 member 自己的库，A 导入的档案对 B 不可见。
"""

import uuid as _uuid
from typing import Any

from lumirss.db_tx import transaction
from lumirss.storage import Database
from lumirss.util import utc_now

MAX_FILE_BYTES = 3 * 1024 * 1024
MAX_RECORDS = 5000
MAX_RECORD_PAYLOAD_BYTES = 512 * 1024
MAX_BODY_TEXT_CHARS = 200_000
MAX_HEADER_SCAN = 8192
_MAX_HEADER_LINES = 60

_ACTIVE_TYPES = ("html", "xhtml", "javascript", "ecmascript")


class WarcInvalid(ValueError):
    """WARC 文件非法（映射 400）。"""


def _active_content(content_type: str) -> bool:
    lowered = content_type.lower()
    return any(marker in lowered for marker in _ACTIVE_TYPES)


def _strip_tags(html_text: str) -> str:
    import re

    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", html_text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_headers(block: bytes, limit_lines: int) -> dict[str, str]:
    headers: dict[str, str] = {}
    for line in block.split(b"\r\n")[:limit_lines]:
        if b":" not in line:
            continue
        name, _, value = line.partition(b":")
        try:
            headers[name.decode("ascii", "replace").strip().lower()] = value.decode(
                "utf-8", "replace"
            ).strip()
        except Exception:  # noqa: BLE001 — 敌意字节永不 500
            continue
    return headers


def parse_warc(
    raw: bytes, *, import_bodies: bool = False
) -> dict[str, Any]:
    """有界解析 WARC 1.0/1.1 → 索引列表 + 计数（零写入）。"""
    if len(raw) > MAX_FILE_BYTES:
        raise WarcInvalid(
            f"档案超过 {MAX_FILE_BYTES // (1024 * 1024)}MiB 上限。"
        )
    if not raw.startswith(b"WARC/"):
        raise WarcInvalid("不是 WARC 档案（缺少 WARC/ 记录头）。")

    records: list[dict[str, Any]] = []
    skipped = 0
    oversized = 0
    active_count = 0
    body_count = 0
    notes: list[str] = []
    offset = 0
    size = len(raw)

    while offset < size and len(records) < MAX_RECORDS + 200:
        head_start = raw.find(b"WARC/", offset)
        if head_start < 0:
            break
        header_end = raw.find(b"\r\n\r\n", head_start)
        if header_end < 0:
            notes.append("记录头不完整，解析停止。")
            break
        header_block = raw[head_start:header_end][: MAX_HEADER_SCAN * 4]
        headers = _parse_headers(header_block, _MAX_HEADER_LINES)
        content_length_raw = headers.get("content-length", "0")
        try:
            content_length = max(0, int(content_length_raw))
        except ValueError:
            content_length = 0
        payload_start = header_end + 4
        payload_end = min(payload_start + content_length, size)

        if headers.get("warc-type") in ("response", "resource", "conversion"):
            content_type = ""
            http_status = ""
            body_bytes = b""
            payload = raw[payload_start:payload_end]
            if headers.get("warc-type") == "response" and payload[:5] == b"HTTP/":
                http_header_end = payload.find(b"\r\n\r\n")
                scan_limit = min(
                    http_header_end if http_header_end >= 0 else MAX_HEADER_SCAN,
                    MAX_HEADER_SCAN,
                )
                http_headers = _parse_headers(payload[: scan_limit + 4], _MAX_HEADER_LINES)
                first_line = payload.split(b"\r\n", 1)[0]
                http_status = first_line.decode("ascii", "replace")[:60]
                content_type = http_headers.get("content-type", "")
                body_bytes = payload[scan_limit + 4 :] if http_header_end >= 0 else b""
            elif headers.get("warc-http-type"):
                content_type = headers.get("warc-http-type", "")
                body_bytes = payload

            body_text = ""
            wants_body = import_bodies and not _active_content(content_type)
            is_oversized = content_length > MAX_RECORD_PAYLOAD_BYTES
            if is_oversized:
                oversized += 1
            elif wants_body and content_type.lower().startswith("text/"):
                decoded = body_bytes[: MAX_BODY_TEXT_CHARS * 4].decode(
                    "utf-8", "replace"
                )
                body_text = (
                    _strip_tags(decoded)
                    if "html" in content_type.lower()
                    else decoded
                )[:MAX_BODY_TEXT_CHARS]
                if body_text:
                    body_count += 1
            if _active_content(content_type):
                active_count += 1

            target_uri = headers.get("warc-target-uri", "")
            record_type = headers.get("warc-type", "")
            if target_uri:
                duplicate = any(
                    r["targetUri"] == target_uri and r["recordType"] == record_type
                    for r in records
                )
                if duplicate:
                    skipped += 1
                else:
                    records.append(
                        {
                            "targetUri": target_uri[:2048],
                            "recordType": record_type,
                            "recordId": headers.get("warc-record-id", "")[:300],
                            "contentType": content_type[:200],
                            "contentLength": content_length,
                            "payloadDigest": headers.get("warc-payload-digest", "")[:200],
                            "warcDate": headers.get("warc-date", "")[:60],
                            "httpStatus": http_status,
                            "activeContent": _active_content(content_type),
                            "oversized": is_oversized,
                            "bodyText": body_text,
                        }
                    )
            else:
                skipped += 1
                if len(notes) < 20:
                    notes.append("缺少 WARC-Target-URI 的记录已跳过。")
        # 其他 WARC-Type（request / metadata / wakeup…）只计数不索引
        elif headers.get("warc-type"):
            skipped += 1
        offset = payload_end + 2  # 跳过 payload 后的分隔 CRLF
        if len(records) >= MAX_RECORDS:
            notes.append(f"达到 {MAX_RECORDS} 条索引上限，其余记录未解析。")
            break

    if not records and skipped == 0:
        raise WarcInvalid("未找到可索引的 WARC 记录。")
    return {
        "records": records,
        "skipped": skipped,
        "oversized": oversized,
        "activeContent": active_count,
        "bodyImported": body_count,
        "notes": notes,
    }


class WarcStore:
    """new385_warc_records / new385_warc_batches 持久化。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def import_index(
        self, parsed: dict[str, Any]
    ) -> dict[str, Any]:
        import json

        await self._db.migrate()
        batch_id = f"warc-{_uuid.uuid4().hex[:12]}"
        records = parsed["records"]

        def _tx(conn: Any) -> None:
            conn.execute(
                "INSERT INTO new385_warc_batches"
                " (id, record_count, imported, skipped_count, oversized_count,"
                " active_content_count, body_imported_count, notes_json, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    batch_id,
                    len(records),
                    len(records),
                    int(parsed["skipped"]),
                    int(parsed["oversized"]),
                    int(parsed["activeContent"]),
                    int(parsed["bodyImported"]),
                    json.dumps(parsed["notes"], ensure_ascii=False),
                    utc_now(),
                ),
            )
            for record in records:
                conn.execute(
                    "INSERT INTO new385_warc_records"
                    " (id, batch_id, target_uri, record_type, record_id,"
                    " content_type, content_length, payload_digest, warc_date,"
                    " http_status, active_content, body_text, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        f"wrec-{_uuid.uuid4().hex[:16]}",
                        batch_id,
                        record["targetUri"],
                        record["recordType"],
                        record["recordId"],
                        record["contentType"],
                        int(record["contentLength"]),
                        record["payloadDigest"],
                        record["warcDate"],
                        record["httpStatus"],
                        1 if record["activeContent"] else 0,
                        record["bodyText"],
                        utc_now(),
                    ),
                )

        await transaction(self._db, _tx)
        return {
            "batchId": batch_id,
            "imported": len(records),
            **{k: v for k, v in parsed.items() if k != "records"},
        }

    async def list_batches(self) -> list[dict[str, Any]]:
        import json

        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, record_count, imported, skipped_count, oversized_count,"
            " active_content_count, body_imported_count, notes_json, created_at"
            " FROM new385_warc_batches ORDER BY created_at DESC, id ASC LIMIT 100"
        )
        return [
            {
                "id": str(row["id"]),
                "recordCount": int(row["record_count"]),
                "imported": int(row["imported"]),
                "skipped": int(row["skipped_count"]),
                "oversized": int(row["oversized_count"]),
                "activeContent": int(row["active_content_count"]),
                "bodyImported": int(row["body_imported_count"]),
                "notes": json.loads(str(row["notes_json"])),
                "createdAt": str(row["created_at"]),
            }
            for row in rows
        ]

    async def list_records(self, batch_id: str | None) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, batch_id, target_uri, record_type, record_id, content_type,"
            " content_length, payload_digest, warc_date, http_status, active_content,"
            " body_text, created_at FROM new385_warc_records"
            " WHERE (? IS NULL OR batch_id = ?)"
            " ORDER BY created_at DESC, id ASC LIMIT 2000",
            (batch_id, batch_id),
        )
        return [
            {
                "id": str(row["id"]),
                "batchId": str(row["batch_id"]),
                "targetUri": str(row["target_uri"]),
                "recordType": str(row["record_type"]),
                "recordId": str(row["record_id"]),
                "contentType": str(row["content_type"]),
                "contentLength": int(row["content_length"]),
                "payloadDigest": str(row["payload_digest"]),
                "warcDate": str(row["warc_date"]),
                "httpStatus": str(row["http_status"]),
                "activeContent": bool(row["active_content"]),
                "bodyText": str(row["body_text"]),
                "createdAt": str(row["created_at"]),
            }
            for row in rows
        ]
