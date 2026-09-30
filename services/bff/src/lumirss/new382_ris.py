"""NEW-382 RIS 引文导入与导出 —— 字段映射、不支持字段如实报告、
导出后可往返校验。

边界：

- 解析/序列化都是 stdlib 文本处理（无新依赖）；文件 ≤2MiB、
  条目 ≤2000（与 NEW-381 同口径）；
- 支持的 RIS tag 映射到书目记录（TY/TI/AU/A1/PY/T2/JO/JF/PB/UR/
  AB/KW/DO/AN/ID/SP/EP/VL/IS）；其余出现的 tag 逐条列入
  unsupportedFields（计数如实报告，不丢弃不管、不假装映射）；
- 原始引用标识：AN / ID tag 原样保留；两者皆缺时以标题内容散列
  派生稳定 id（ris:<hash16>）并在响应里说明；
- 导出：记录 → RIS 文本（每条 TY…ER），导出即附带往返校验：把
  导出文本重新解析，逐字段对比，差异如实进 roundtrip 报告；
- per-user：导入/导出/查重都在 member 自己的库。
"""

import hashlib
import re
from typing import Any

from lumirss.new381_bib import MAX_FILE_CHARS, MAX_RECORDS, BibInvalid, _clean
from lumirss.storage import Database
from lumirss.util import utc_now

# RIS 行：行首 2 位 tag + "  - " + 值（宽松匹配 1-2 空格）。
_RIS_LINE = re.compile(r"^([A-Z][A-Z0-9])  ?- ?(.*)$")

# 支持映射的 RIS tag → 记录字段。其余 tag 一律进 unsupportedFields。
_TAG_MAP = {
    "TY": "itemType",
    "TI": "title",
    "AU": "creators",
    "A1": "creators",
    "PY": "pubYear",
    "T2": "publication",
    "JO": "publication",
    "JF": "publication",
    "PB": "publisher",
    "UR": "url",
    "AB": "abstract",
    "KW": "tags",
    "DO": "doi",
}
_ID_TAGS = ("AN", "ID")
_RIS_TYPE_DEFAULT = "GEN"
_KNOWN_TAGS = set(_TAG_MAP) | set(_ID_TAGS) | {"ER"}


def parse_ris(text: str) -> list[dict[str, Any]]:
    """RIS 文本 → 解析后的条目列表（零写入，形状与 NEW-381 一致）。"""
    if len(text) > MAX_FILE_CHARS:
        raise BibInvalid(f"文件超过 {MAX_FILE_CHARS // (1024 * 1024)}MiB 上限。")
    records: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    unsupported: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.rstrip("\r")
        match = _RIS_LINE.match(line)
        if match is None:
            continue  # 空行 / 残缺行：跳过并在结尾校验
        tag, value = match.group(1), match.group(2).strip()
        if tag == "ER":
            if current is not None:
                records.append(_finalize(current, unsupported))
                current = None
                unsupported = []
            continue
        if tag == "TY":
            if current is not None:
                records.append(_finalize(current, unsupported))
            current = {"fields": {"itemType": value or _RIS_TYPE_DEFAULT}}
            unsupported = []
            continue
        if current is None:
            continue  # TY 之前的散行不构成记录
        if tag in _ID_TAGS:
            current["fields"]["externalId"] = value
            continue
        if tag in _TAG_MAP:
            _append_field(current["fields"], _TAG_MAP[tag], value)
        elif tag not in _KNOWN_TAGS and tag not in unsupported:
            unsupported.append(tag)
    if current is not None:  # 缺 ER 的残卷：按遇到的内容收尾
        records.append(_finalize(current, unsupported))
    if not records:
        raise BibInvalid("未在文件中找到 RIS 条目（TY … ER）。")
    if len(records) > MAX_RECORDS:
        raise BibInvalid(f"条目超过 {MAX_RECORDS} 条上限。")
    return records


def _append_field(fields: dict[str, Any], key: str, value: str) -> None:
    if not value:
        return
    if key in ("creators", "tags"):
        bucket = fields.setdefault(key, [])
        if len(bucket) < (50 if key == "creators" else 100):
            bucket.append(_clean(value, 300))
    else:
        limit = 2000 if key == "title" else (8000 if key == "abstract" else 500)
        fields.setdefault(key, _clean(value, limit))


def _finalize(current: dict[str, Any], unsupported: list[str]) -> dict[str, Any]:
    fields = current["fields"]
    title = fields.get("title") or "(无题)"
    external_id = fields.get("externalId") or "ris:" + hashlib.sha256(
        title.encode("utf-8")
    ).hexdigest()[:16]
    return {
        "externalId": external_id,
        "title": title,
        "creators": fields.get("creators", []),
        "pubYear": fields.get("pubYear", ""),
        "publication": fields.get("publication", ""),
        "publisher": fields.get("publisher", ""),
        "url": fields.get("url", ""),
        "doi": fields.get("doi", ""),
        "abstract": fields.get("abstract", ""),
        "itemType": fields.get("itemType", _RIS_TYPE_DEFAULT),
        "tags": fields.get("tags", []),
        "unsupportedFields": unsupported,
        "idDerived": "externalId" not in fields,
    }


def _ris_escape(value: str) -> str:
    return value.replace("\r", " ").replace("\n", " ")


def serialize_ris(records: list[dict[str, Any]]) -> str:
    """书目记录 → RIS 文本（每条 TY…ER；仅写支持映射的字段）。"""
    blocks: list[str] = []
    for record in records:
        lines = [f"TY  - {record.get('itemType') or _RIS_TYPE_DEFAULT}"]
        if record.get("title"):
            lines.append(f"TI  - {_ris_escape(str(record['title']))}")
        for creator in record.get("creators") or []:
            lines.append(f"AU  - {_ris_escape(str(creator))}")
        if record.get("pubYear"):
            lines.append(f"PY  - {record['pubYear']}")
        if record.get("publication"):
            lines.append(f"T2  - {_ris_escape(str(record['publication']))}")
        if record.get("publisher"):
            lines.append(f"PB  - {_ris_escape(str(record['publisher']))}")
        if record.get("url"):
            lines.append(f"UR  - {record['url']}")
        if record.get("doi"):
            lines.append(f"DO  - {record['doi']}")
        for tag_value in record.get("tags") or []:
            lines.append(f"KW  - {_ris_escape(str(tag_value))}")
        if record.get("abstract"):
            lines.append(f"AB  - {_ris_escape(str(record['abstract']))}")
        lines.append("ER  - ")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"


def roundtrip_report(
    records: list[dict[str, Any]], exported: str
) -> dict[str, Any]:
    """导出文本重解析 → 逐字段对比（往返校验报告）。

    compared 字段集 = serialize_ris 写出的字段。差异 = expected 有而
    reparsed 无（lost）/ 值不一致（changed）；多出的 creator/tag 截断
    也按 changed 报告。不受支持字段本来就不进 RIS，不算往返损失
    （由 NEW-381/382 的 unsupportedFields 另行如实报告）。
    """
    reparsed = parse_ris(exported)
    per_record: list[dict[str, Any]] = []
    ok = True
    for index, record in enumerate(records):
        got = reparsed[index] if index < len(reparsed) else None
        entry: dict[str, Any] = {
            "externalId": record.get("externalId", ""),
            "index": index,
            "lost": [],
            "changed": [],
        }
        if got is None:
            entry["lost"] = ["*record*"]
            ok = False
            per_record.append(entry)
            continue
        single = ("itemType", "title", "pubYear", "publication",
                  "publisher", "url", "doi", "abstract")
        for field in single:
            expected_value = str(record.get(field) or "")
            got_value = str(got.get(field) or "")
            if not expected_value:
                continue
            if not got_value:
                entry["lost"].append(field)
            elif got_value != expected_value:
                entry["changed"].append(field)
        for field in ("creators", "tags"):
            expected_list = [str(v) for v in record.get(field) or []]
            got_list = [str(v) for v in got.get(field) or []]
            if not expected_list:
                continue
            if not got_list:
                entry["lost"].append(field)
            elif got_list != expected_list:
                entry["changed"].append(field)
        if entry["lost"] or entry["changed"]:
            ok = False
        per_record.append(entry)
    return {
        "roundtripOk": ok,
        "compared": len(records),
        "records": per_record,
        "checkedAt": utc_now(),
    }


class RisExportStore:
    """new382_ris_exports 台账。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def persist(
        self, record_count: int, report: dict[str, Any]
    ) -> str:
        import uuid as _uuid

        await self._db.migrate()
        export_id = f"risexp-{_uuid.uuid4().hex[:12]}"
        import json

        await self._db.execute(
            "INSERT INTO new382_ris_exports"
            " (id, record_count, roundtrip_ok, roundtrip_report_json, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                export_id,
                record_count,
                1 if report["roundtripOk"] else 0,
                json.dumps(report, ensure_ascii=False),
                utc_now(),
            ),
        )
        return export_id

    async def list_exports(self) -> list[dict[str, Any]]:
        import json

        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, record_count, roundtrip_ok, roundtrip_report_json, created_at"
            " FROM new382_ris_exports ORDER BY created_at DESC, id ASC LIMIT 100"
        )
        return [
            {
                "id": str(row["id"]),
                "recordCount": int(row["record_count"]),
                "roundtripOk": bool(row["roundtrip_ok"]),
                "roundtripReport": json.loads(str(row["roundtrip_report_json"])),
                "createdAt": str(row["created_at"]),
            }
            for row in rows
        ]
