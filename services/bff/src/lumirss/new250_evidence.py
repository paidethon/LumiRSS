"""NEW-250 证据完整性检查单 —— 报告引文证据面 + 逐项补齐。

语义边界（模块存在的理由）：

- evidence_items：一份个人报告（report_label）里每条引文的证据记录；
  三项证据，全以**显式记录**为准，另参考既有事实防「指向不存在的东西」：
  * source（来源指向）：source_ref 非空；
  * version（保存版本）：version_id 非空 **且** article_saved_versions
    里真有这一版（NEW-241 的表；指向被删版本 → honest missing）；
  * excerpt（可定位片段）：excerpt 非空；
- 缺项不代填：用户通过 PATCH 单项补（sourceRef / versionId / excerpt
  逐个字段，PATCH 只改提交了的字段）；
- 建单幂等：同一 (report, citation) 重复提交 → 更新既有行不重复建；
  报告不存在时 PATCH → 404（诚实：没有这个检查单）。

per-user 库：检查单天然按账户隔离。
"""

import sqlite3
import uuid as _uuid
from typing import Any

from lumirss.db_tx import transaction
from lumirss.storage import Database
from lumirss.util import utc_now

_LABEL_MAX = 120
_EXCERPT_MAX = 2000
_REF_MAX = 300
_MAX_CITATIONS = 200


class EvidenceInvalid(ValueError):
    """检查单负载非法（映射 422）。"""


class EvidenceNotFound(Exception):
    """检查单或引文项不存在（映射 404）。"""


def _clean(value: Any, field: str, *, max_len: int, required: bool) -> str:
    if not isinstance(value, str):
        raise EvidenceInvalid(f"{field} 必须是字符串。")
    cleaned = value.strip()
    if required and not cleaned:
        raise EvidenceInvalid(f"{field} 不能为空。")
    if len(cleaned) > max_len:
        raise EvidenceInvalid(f"{field} 超出 {max_len} 字符上限。")
    return cleaned


class EvidenceChecklistStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    # -- 建单 / 幂等登记 -------------------------------------------------------

    async def create_items(self, report_label: str, citation_refs: list[str]) -> dict[str, Any]:
        clean_label = _clean(report_label, "reportLabel", max_len=_LABEL_MAX, required=True)
        if not isinstance(citation_refs, list) or not citation_refs:
            raise EvidenceInvalid("citationRefs 不能为空。")
        if len(citation_refs) > _MAX_CITATIONS:
            raise EvidenceInvalid(f"单份检查单最多 {_MAX_CITATIONS} 条引文。")
        clean_refs = [_clean(r, "citationRef", max_len=_REF_MAX, required=True) for r in citation_refs]
        now = utc_now()

        def _tx(conn: sqlite3.Connection) -> None:
            for ref in dict.fromkeys(clean_refs):
                existing = conn.execute(
                    "SELECT id FROM evidence_items WHERE report_label = ? AND citation_ref = ?",
                    (clean_label, ref),
                ).fetchone()
                if existing is None:
                    conn.execute(
                        "INSERT INTO evidence_items (id, report_label, citation_ref, updated_at) "
                        "VALUES (?, ?, ?, ?)",
                        (str(_uuid.uuid4()), clean_label, ref, now),
                    )

        await transaction(self._db, _tx)
        return {"reportLabel": clean_label, "citationRefs": list(dict.fromkeys(clean_refs))}

    # -- 查询 -----------------------------------------------------------------

    async def get_report(self, report_label: str) -> dict[str, Any]:
        clean_label = _clean(report_label, "reportLabel", max_len=_LABEL_MAX, required=True)
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, citation_ref, source_ref, version_id, excerpt, updated_at "
            "FROM evidence_items WHERE report_label = ? ORDER BY citation_ref",
            (clean_label,),
        )
        if not rows:
            raise EvidenceNotFound(clean_label)
        items = [await self._item_view(row) for row in rows]
        complete = sum(1 for item in items if item["complete"])
        return {
            "reportLabel": clean_label,
            "items": items,
            "total": len(items),
            "completeCount": complete,
            "missingCount": len(items) - complete,
        }

    async def _item_view(self, row: Any) -> dict[str, Any]:
        source_ref = str(row["source_ref"]) if row["source_ref"] else None
        version_id = str(row["version_id"]) if row["version_id"] else None
        excerpt = str(row["excerpt"]) if row["excerpt"] else None
        has_source = source_ref is not None
        has_version = version_id is not None
        version_exists = None
        if version_id is not None:
            version_row = await self._db.fetch_one(
                "SELECT id FROM article_saved_versions WHERE id = ?", (version_id,)
            )
            version_exists = version_row is not None
            # 指向不存在的版本 = 证据缺失（诚实），不冒充已具备
            has_version = version_exists
        has_excerpt = excerpt is not None
        missing = [name for name, ok in (("source", has_source), ("version", has_version), ("excerpt", has_excerpt)) if not ok]
        return {
            "id": str(row["id"]),
            "citationRef": str(row["citation_ref"]),
            "sourceRef": source_ref,
            "versionId": version_id,
            "excerpt": excerpt,
            "hasSource": has_source,
            "hasVersion": has_version,
            "versionExists": version_exists,
            "hasExcerpt": has_excerpt,
            "missing": missing,
            "complete": not missing,
            "updatedAt": str(row["updated_at"]),
        }

    # -- 逐项补齐 ---------------------------------------------------------------

    async def patch_item(
        self,
        report_label: str,
        citation_ref: str,
        *,
        source_ref: str | None = None,
        version_id: str | None = None,
        excerpt: str | None = None,
    ) -> dict[str, Any]:
        clean_label = _clean(report_label, "reportLabel", max_len=_LABEL_MAX, required=True)
        clean_ref = _clean(citation_ref, "citationRef", max_len=_REF_MAX, required=True)
        clean_source = (
            None if source_ref is None
            else _clean(source_ref, "sourceRef", max_len=_REF_MAX, required=True)
        )
        clean_version = (
            None if version_id is None
            else _clean(version_id, "versionId", max_len=_REF_MAX, required=True)
        )
        clean_excerpt = (
            None if excerpt is None
            else _clean(excerpt, "excerpt", max_len=_EXCERPT_MAX, required=True)
        )
        now = utc_now()

        def _tx(conn: sqlite3.Connection) -> None:
            row = conn.execute(
                "SELECT id FROM evidence_items WHERE report_label = ? AND citation_ref = ?",
                (clean_label, clean_ref),
            ).fetchone()
            if row is None:
                raise EvidenceNotFound(f"{clean_label}/{clean_ref}")
            if clean_source is not None:
                conn.execute(
                    "UPDATE evidence_items SET source_ref = ?, updated_at = ? WHERE id = ?",
                    (clean_source, now, str(row["id"])),
                )
            if clean_version is not None:
                conn.execute(
                    "UPDATE evidence_items SET version_id = ?, updated_at = ? WHERE id = ?",
                    (clean_version, now, str(row["id"])),
                )
            if clean_excerpt is not None:
                conn.execute(
                    "UPDATE evidence_items SET excerpt = ?, updated_at = ? WHERE id = ?",
                    (clean_excerpt, now, str(row["id"])),
                )

        await transaction(self._db, _tx)
        await self._db.migrate()
        updated = await self._db.fetch_one(
            "SELECT id, citation_ref, source_ref, version_id, excerpt, updated_at "
            "FROM evidence_items WHERE report_label = ? AND citation_ref = ?",
            (clean_label, clean_ref),
        )
        assert updated is not None  # 刚更新过
        return await self._item_view(updated)
