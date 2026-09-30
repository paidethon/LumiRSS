"""NEW-388 个人索引导出 —— 只导出资料目录、标签、来源与校验值，
不附全文，便于盘点与迁移准备。

口径：

- 字段白名单（目录级）：sourceFormat / externalId / title / creators
  / pubYear / itemType / tags / publication（来源）/ url / sha256；
  明确不含 abstract、不含正文——模块与响应都如实说明；
- 校验值：每条记录对目录字段的 canonical JSON 做 sha256；整个目录
  再做整体 sha256（catalogSha256），迁移前后可比对；
- 聚合视图：tags 全集计数、sources（publication）全集计数；
- 输出即时返回（JSON 响应或 .json 下载）；台账只存条数、标签/来源
  计数与整体校验值。

per-user：目录面是 member 自己的书目库。
"""

import hashlib
import json
import uuid as _uuid
from typing import Any

from lumirss.new381_bib import BibStore
from lumirss.storage import Database
from lumirss.util import utc_now

# 索引导出字段白名单——刻意不含 abstract/正文。
_INDEX_FIELDS = (
    "format", "externalId", "title", "creators", "pubYear",
    "itemType", "tags", "publication", "url",
)


def _canonical(record: dict[str, Any]) -> dict[str, Any]:
    return {field: record.get(field) for field in _INDEX_FIELDS}


def _record_sha256(record: dict[str, Any]) -> str:
    canonical = json.dumps(
        _canonical(record), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def build_catalog(db: Database, source_format: str | None = None) -> dict[str, Any]:
    await db.migrate()
    if source_format not in (None, "", "zotero_rdf", "ris"):
        from lumirss.new381_bib import BibInvalid

        raise BibInvalid("未知来源格式（可选 zotero_rdf / ris / 全部）。")
    records = await BibStore(db).list_records(source_format or None)
    entries = [
        {**_canonical(record), "sha256": _record_sha256(record)}
        for record in records
    ]
    tags: dict[str, int] = {}
    sources: dict[str, int] = {}
    for record in records:
        for tag in record["tags"]:
            tags[tag] = tags.get(tag, 0) + 1
        if record["publication"]:
            sources[record["publication"]] = sources.get(record["publication"], 0) + 1
    catalog = {
        "kind": "lumi-index-export",
        "generatedAt": utc_now(),
        "recordCount": len(entries),
        "records": entries,
        "tags": dict(sorted(tags.items(), key=lambda kv: (-kv[1], kv[0]))),
        "sources": dict(sorted(sources.items(), key=lambda kv: (-kv[1], kv[0]))),
        "excluded": ["abstract", "正文"],
        "note": "索引导出只含目录、标签、来源与校验值，不含摘要或全文。",
    }
    catalog_sha = hashlib.sha256(
        json.dumps(
            {key: catalog[key] for key in ("recordCount", "records", "tags", "sources")},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    catalog["catalogSha256"] = catalog_sha
    return catalog


async def persist_export(db: Database, catalog: dict[str, Any]) -> str:
    await db.migrate()
    export_id = f"idxexp-{_uuid.uuid4().hex[:12]}"
    await db.execute(
        "INSERT INTO new388_index_exports"
        " (id, record_count, tag_count, source_count, catalog_sha256, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (
            export_id,
            int(catalog["recordCount"]),
            len(catalog["tags"]),
            len(catalog["sources"]),
            catalog["catalogSha256"],
            utc_now(),
        ),
    )
    return export_id


async def list_exports(db: Database) -> list[dict[str, Any]]:
    await db.migrate()
    rows = await db.fetch_all(
        "SELECT id, record_count, tag_count, source_count, catalog_sha256, created_at"
        " FROM new388_index_exports ORDER BY created_at DESC, id ASC LIMIT 100"
    )
    return [
        {
            "id": str(row["id"]),
            "recordCount": int(row["record_count"]),
            "tagCount": int(row["tag_count"]),
            "sourceCount": int(row["source_count"]),
            "catalogSha256": str(row["catalog_sha256"]),
            "createdAt": str(row["created_at"]),
        }
        for row in rows
    ]
