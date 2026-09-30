"""NEW-381 Zotero RDF 书目导入 —— 解析用户主动导出的书目文件，预览
字段映射与重复资料，保留原始引用标识。

边界：

- 输入是用户文件（非网络）；解析走 defusedxml（实体展开/DTD 禁用，
  与 opml 同口径）；文件文本 ≤2MiB、条目 ≤2000；
- 字段映射如实报告：支持的 Zotero/DC/BIBO 字段进映射预览，出现但
  不支持的命名空间字段逐条列入 unsupportedFields（不假装映射、不
  丢弃不管）；
- 原始引用标识：Zotero RDF 的 ``rdf:about`` 末段 item key（缺失时
  依次回退 z:uuid / dc:identifier / 内容摘要散列），原样保留为
  external_id；
- creator 间接引用（dc:creator rdf:resource → foaf 节点）用全树
  agent 表解析；
- 重复检测：existing (source_format, external_id) 命中 → duplicate
  并给出对应记录 id；标题（大小写折叠）+年份相同也如实提示；
- 落库：per-user 库 new381_bib_records，重复默认跳过（台账计数，
  不无声覆盖——保原始值）；
- 防御性上限：单条字段截断（title 2000 / abstract 8000 / 其余
  500），creator ≤50，tag ≤100 —— 敌意文件只报错或截断，不放大。

per-user：落库与重复检测都发生在 member 自己的库（路由层 session
门槛），A 的书目对 B 不可见。
"""

import hashlib
import json
import re
import sqlite3
import uuid as _uuid
import xml.etree.ElementTree as ET  # noqa: S405 — 仅类型注解；解析走 defusedxml
from typing import Any

import defusedxml.ElementTree as SafeET

from lumirss.db_tx import transaction
from lumirss.storage import Database
from lumirss.util import utc_now

MAX_FILE_CHARS = 2 * 1024 * 1024
MAX_RECORDS = 2000
_MAX_CREATORS = 50
_MAX_TAGS = 100

NS = {
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "dc": "http://purl.org/dc/elements/1.1/",
    "dcterms": "http://purl.org/dc/terms/",
    "bibo": "http://purl.org/ontology/bibo/",
    "z": "http://www.zotero.org/namespaces/export#",
    "foaf": "http://xmlns.com/foaf/0.1/",
}
_Z_ITEM = f"{{{NS['z']}}}item"
_RDF_ABOUT = f"{{{NS['rdf']}}}about"
_RDF_RESOURCE = f"{{{NS['rdf']}}}resource"

# 支持映射的字段（按命名空间前缀 × 本地名）。
_SUPPORTED = {
    "dc": {"title", "date", "publisher", "subject", "identifier",
           "creator", "contributor", "source", "description"},
    "dcterms": {"title", "abstract", "issued", "created", "modified", "isPartOf"},
    "z": {"itemType", "uuid"},
    "bibo": {"uri", "doi"},
}


class BibInvalid(ValueError):
    """书目文件非法（映射 400）。"""


def _clean(value: Any, limit: int = 500) -> str:
    return str(value or "").strip()[:limit]


def _text_of(node: ET.Element, path: str) -> str:
    found = node.find(path, NS)
    if found is None:
        return ""
    return _clean("".join(found.itertext()))


def _prefix_for(uri: str) -> str:
    for prefix, known in NS.items():
        if known == uri:
            return prefix
    return (uri.rstrip("/").rsplit("/", 1)[-1] or "ns").lower()


def _unsupported_of(node: ET.Element) -> list[str]:
    unsupported: list[str] = []
    for child in node:
        if not isinstance(child.tag, str):  # 注释 / 处理指令
            continue
        if "}" in child.tag:
            uri, local = child.tag[1:].split("}", 1)
            prefix = _prefix_for(uri)
        else:
            prefix, local = "", child.tag
        if prefix == "rdf" or local in ("type",):
            continue
        if local in _SUPPORTED.get(prefix, set()):
            continue
        label = f"{prefix}:{local}" if prefix else local
        if label not in unsupported:
            unsupported.append(label)
    return unsupported


def _external_id_of(node: ET.Element, title: str, date_value: str) -> str:
    about = node.get(_RDF_ABOUT, "")
    key_match = re.search(r"/items/([A-Za-z0-9]+)(?:[?#].*)?$", about)
    if key_match:
        return key_match.group(1)
    uuid_value = _text_of(node, "z:uuid")
    if uuid_value:
        return uuid_value
    for ident in node.findall("dc:identifier", NS):
        text = _clean("".join(ident.itertext()))
        if text:
            return text
    return "zotero:" + hashlib.sha256(
        f"{title}\n{date_value}".encode()
    ).hexdigest()[:16]


def _agent_table(root: ET.Element) -> dict[str, str]:
    agents: dict[str, str] = {}
    for candidate in root.iter():
        about = candidate.get(_RDF_ABOUT)
        if not about:
            continue
        family = _text_of(candidate, "foaf:surname")
        given = _text_of(candidate, "foaf:givenName")
        name = (
            _clean(f"{family}, {given}" if family else given, 200)
            if (family or given)
            else _text_of(candidate, "foaf:name")
        )
        if name:
            agents[about] = name
    return agents


def _creators_of(node: ET.Element, agents: dict[str, str]) -> list[str]:
    out: list[str] = []
    for tag in ("dc:creator", "dc:contributor"):
        for child in node.findall(tag, NS):
            if len(out) >= _MAX_CREATORS:
                break
            ref = child.get(_RDF_RESOURCE)
            if ref and ref in agents:
                out.append(agents[ref])
                continue
            text = _clean("".join(child.itertext()))
            if text:
                out.append(text)
    return out[:_MAX_CREATORS]


def _parse_item(node: ET.Element, agents: dict[str, str]) -> dict[str, Any]:
    title = _text_of(node, "dc:title") or _text_of(node, "dcterms:title")
    date_value = _text_of(node, "dc:date")
    year_match = re.search(r"\d{4}", date_value)

    url = ""
    for ident in node.findall("dc:identifier", NS):
        candidate = ident.get(_RDF_RESOURCE) or _clean("".join(ident.itertext()))
        if candidate.startswith(("http://", "https://")):
            url = candidate
            break
    if not url:
        url = _text_of(node, "bibo:uri")

    item_type = ""
    rdf_type = node.find("rdf:type", NS)
    if rdf_type is not None:
        item_type = (rdf_type.get(_RDF_RESOURCE) or "").rsplit("/", 1)[-1]
    item_type = _clean(item_type) or _text_of(node, "z:itemType")

    tags = [
        _clean("".join(child.itertext()))
        for child in node.findall("dc:subject", NS)
    ]
    tags = [t for t in tags if t][:_MAX_TAGS]

    return {
        "externalId": _external_id_of(node, title, date_value),
        "title": title or "(无题)",
        "creators": _creators_of(node, agents),
        "pubYear": year_match.group(0) if year_match else "",
        "publication": _text_of(node, "dc:source"),
        "publisher": _text_of(node, "dc:publisher"),
        "url": url,
        "doi": _text_of(node, "bibo:doi"),
        "abstract": _text_of(node, "dcterms:abstract") or _text_of(node, "dc:description"),
        "itemType": item_type,
        "tags": tags,
        "unsupportedFields": _unsupported_of(node),
    }


def parse_zotero_rdf(text: str) -> list[dict[str, Any]]:
    """Zotero RDF 文本 → 解析后的条目列表（零写入）。

    敌意输入（非 XML / 超上限）→ BibInvalid。
    """
    if len(text) > MAX_FILE_CHARS:
        raise BibInvalid(f"文件超过 {MAX_FILE_CHARS // (1024 * 1024)}MiB 上限。")
    try:
        root = SafeET.fromstring(text)
    except ET.ParseError as exc:
        raise BibInvalid("不是有效的 XML（Zotero RDF）。") from exc
    agents = _agent_table(root)
    items: list[dict[str, Any]] = []
    for node in root.iter(_Z_ITEM):
        if len(items) >= MAX_RECORDS:
            raise BibInvalid(f"条目超过 {MAX_RECORDS} 条上限。")
        items.append(_parse_item(node, agents))
    if not items:
        raise BibInvalid("未在文件中找到 Zotero 条目（z:item）。")
    return items


class BibStore:
    """new381_bib_records 持久化（per-user 库）。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def existing_keys(self, source_format: str) -> dict[str, str]:
        """external_id → record id（重复检测面）。"""
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, external_id FROM new381_bib_records"
            " WHERE source_format = ? LIMIT 20000",
            (source_format,),
        )
        return {str(row["external_id"]): str(row["id"]) for row in rows}

    async def existing_titles_years(self, source_format: str) -> set[tuple[str, str]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT title, pub_year FROM new381_bib_records"
            " WHERE source_format = ? LIMIT 20000",
            (source_format,),
        )
        return {(str(row["title"]).casefold(), str(row["pub_year"])) for row in rows}

    async def preview(
        self, source_format: str, records: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """预览字段映射 + 重复资料（零写入）。"""
        keys = await self.existing_keys(source_format)
        titles = await self.existing_titles_years(source_format)
        items: list[dict[str, Any]] = []
        for record in records:
            dup_of = keys.get(record["externalId"])
            second = (record["title"].casefold(), record["pubYear"]) in titles
            items.append(
                {
                    **record,
                    "duplicate": dup_of is not None or second,
                    "duplicateOf": dup_of,
                    "duplicateReason": (
                        "external_id" if dup_of else ("title_year" if second else "")
                    ),
                }
            )
        unsupported = sorted(
            {field for record in records for field in record["unsupportedFields"]}
        )
        return {
            "format": source_format,
            "total": len(records),
            "duplicates": sum(1 for item in items if item["duplicate"]),
            "unsupportedFields": unsupported,
            "items": items,
        }

    async def import_records(
        self,
        source_format: str,
        records: list[dict[str, Any]],
        *,
        include_duplicates: bool = False,
    ) -> dict[str, Any]:
        """写入书目记录（重复默认跳过），建批次台账。"""
        await self._db.migrate()
        if not records:
            raise BibInvalid("没有可导入的条目。")
        if len(records) > MAX_RECORDS:
            raise BibInvalid(f"条目超过 {MAX_RECORDS} 条上限。")
        keys = await self.existing_keys(source_format)
        titles = await self.existing_titles_years(source_format)
        batch_id = f"bibimp-{_uuid.uuid4().hex[:12]}"
        counters = {"imported": 0, "duplicates": 0, "failed": 0}
        failures: list[dict[str, str]] = []

        def _tx(conn: Any) -> None:
            conn.execute(
                "INSERT INTO new381_import_batches"
                " (id, format, total, imported, duplicates, failed,"
                " unsupported_json, created_at) VALUES (?, ?, ?, 0, 0, 0, '[]', ?)",
                (batch_id, source_format, len(records), utc_now()),
            )
            for record in records:
                try:
                    external_id = _clean(record.get("externalId"), 500)
                    title = _clean(record.get("title"), 2000) or "(无题)"
                    if not external_id:
                        raise ValueError("缺少引用标识")
                    pub_year = _clean(record.get("pubYear"), 10)
                    dup_key = external_id in keys
                    dup_title = (title.casefold(), pub_year) in titles
                    if (dup_key or dup_title) and not include_duplicates:
                        counters["duplicates"] += 1
                        continue
                    record_id = f"bib-{_uuid.uuid4().hex[:16]}"
                    conn.execute(
                        "INSERT INTO new381_bib_records"
                        " (id, source_format, external_id, title, creators_json,"
                        " pub_year, publication, publisher, url, doi, abstract,"
                        " item_type, tags_json, unsupported_fields_json,"
                        " import_batch_id, created_at)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            record_id,
                            source_format,
                            external_id,
                            title,
                            json.dumps(record.get("creators") or [], ensure_ascii=False),
                            pub_year,
                            _clean(record.get("publication")),
                            _clean(record.get("publisher")),
                            _clean(record.get("url"), 2048),
                            _clean(record.get("doi"), 200),
                            _clean(record.get("abstract"), 8000),
                            _clean(record.get("itemType"), 100),
                            json.dumps(record.get("tags") or [], ensure_ascii=False),
                            json.dumps(
                                record.get("unsupportedFields") or [], ensure_ascii=False
                            ),
                            batch_id,
                            utc_now(),
                        ),
                    )
                    keys[external_id] = record_id
                    counters["imported"] += 1
                except (KeyError, ValueError, TypeError) as exc:
                    counters["failed"] += 1
                    failures.append(
                        {
                            "externalId": _clean(record.get("externalId", ""), 100),
                            "reason": str(exc)[:200],
                        }
                    )
                except sqlite3.IntegrityError:
                    # includeDuplicates 时库级唯一索引仍然兜底：同一
                    # (source_format, external_id) 只保首条原始值。
                    counters["failed"] += 1
                    failures.append(
                        {
                            "externalId": _clean(record.get("externalId", ""), 100),
                            "reason": "已存在同标识记录（不覆盖既有值）",
                        }
                    )
            conn.execute(
                "UPDATE new381_import_batches SET imported = ?, duplicates = ?,"
                " failed = ? WHERE id = ?",
                (counters["imported"], counters["duplicates"], counters["failed"], batch_id),
            )

        await transaction(self._db, _tx)
        unsupported = sorted(
            {
                field
                for record in records
                for field in record.get("unsupportedFields") or []
            }
        )
        await self._db.execute(
            "UPDATE new381_import_batches SET unsupported_json = ? WHERE id = ?",
            (json.dumps(unsupported, ensure_ascii=False), batch_id),
        )
        return {
            "batchId": batch_id,
            "format": source_format,
            "total": len(records),
            **counters,
            "failures": failures,
            "unsupportedFields": unsupported,
        }

    async def list_records(
        self, source_format: str | None = None
    ) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, source_format, external_id, title, creators_json, pub_year,"
            " publication, publisher, url, doi, abstract, item_type, tags_json,"
            " unsupported_fields_json, created_at"
            " FROM new381_bib_records"
            " WHERE (? IS NULL OR source_format = ?)"
            " ORDER BY created_at DESC, id ASC LIMIT 2000",
            (source_format, source_format),
        )
        return [self._row_view(row) for row in rows]

    def _row_view(self, row: Any) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "format": str(row["source_format"]),
            "externalId": str(row["external_id"]),
            "title": str(row["title"]),
            "creators": json.loads(str(row["creators_json"])),
            "pubYear": str(row["pub_year"]),
            "publication": str(row["publication"]),
            "publisher": str(row["publisher"]),
            "url": str(row["url"]),
            "doi": str(row["doi"]),
            "abstract": str(row["abstract"]),
            "itemType": str(row["item_type"]),
            "tags": json.loads(str(row["tags_json"])),
            "unsupportedFields": json.loads(str(row["unsupported_fields_json"])),
            "createdAt": str(row["created_at"]),
        }

    async def get_records_by_ids(
        self, ids: list[str], source_format: str | None = None
    ) -> list[dict[str, Any]]:
        """按 id 列表取记录（保序）；未知 id 静默跳过，调用方负责报告。"""
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, source_format, external_id, title, creators_json, pub_year,"
            " publication, publisher, url, doi, abstract, item_type, tags_json,"
            " unsupported_fields_json, created_at"
            " FROM new381_bib_records"
            " WHERE (? IS NULL OR source_format = ?)"
            " ORDER BY created_at DESC, id ASC LIMIT 2000",
            (source_format, source_format),
        )
        by_id = {str(row["id"]): self._row_view(row) for row in rows}
        return [by_id[ref] for ref in ids if ref in by_id]
