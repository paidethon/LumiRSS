"""F028 术语表批量导入导出 —— 导入校验与模式的 SQL 入口。

- 一批 ≤500 条；term ≤100 字、translation(=definition) ≤500 字；
- mode=skip：已存在的 term 跳过；mode=overwrite：覆盖第一条同名词目
  （同词不同含义可并存是本表语义，覆盖只作用于最早一条并如实计数）；
- 非法结构逐条进 errors[]，不整体失败（一条坏数据不拖垮整批）；
- 导出 = 现库内容序列化为 {terms:[{term, translation}]}，与导入同一
  形状（roundtrip 幂等：导出→skip 导入 → 全部 skipped）。
"""

import uuid
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_BATCH = 500
_MAX_TERM = 100
_MAX_TRANSLATION = 500


class GlossaryImportInvalid(ValueError):
    """导入请求本身非法（terms 缺失/超批上限），422。"""


def _clean_pair(raw: Any) -> tuple[str, str] | None:
    """单条校验：结构合法返回 (term, translation)，否则 None。"""
    if not isinstance(raw, dict):
        return None
    term = raw.get("term")
    translation = raw.get("translation")
    if not isinstance(term, str) or not isinstance(translation, str):
        return None
    term = term.strip()
    translation = translation.strip()
    if not term or len(term) > _MAX_TERM:
        return None
    if not translation or len(translation) > _MAX_TRANSLATION:
        return None
    return term, translation


async def import_terms(
    db: Database, terms: list[Any], mode: str
) -> dict[str, Any]:
    """批量导入；返回 {imported, skipped, overwritten, errors}。"""
    if not isinstance(terms, list) or len(terms) > _MAX_BATCH:
        raise GlossaryImportInvalid(f"terms 必须是数组且每批最多 {_MAX_BATCH} 条。")
    await db.migrate()
    imported = skipped = overwritten = 0
    errors: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw in enumerate(terms):
        pair = _clean_pair(raw)
        if pair is None:
            errors.append(
                {
                    "index": index,
                    "reason": "结构非法：需要 term(≤100字) 与 translation(≤500字) 两个非空字段。",
                }
            )
            continue
        term, translation = pair
        if term in seen:
            errors.append({"index": index, "reason": f"批内重复 term：{term}。"})
            continue
        seen.add(term)
        existing = await db.fetch_one(
            "SELECT id FROM glossary_terms WHERE term = ? ORDER BY created_at ASC, id ASC LIMIT 1",
            (term,),
        )
        now = utc_now()
        if existing is None:
            term_id = f"glo-{uuid.uuid4().hex[:16]}"
            await db.execute(
                "INSERT INTO glossary_terms (id, term, definition, source_ref, created_at, updated_at) VALUES (?, ?, ?, NULL, ?, ?)",
                (term_id, term, translation, now, now),
            )
            imported += 1
        elif mode == "overwrite":
            await db.execute(
                "UPDATE glossary_terms SET definition = ?, updated_at = ? WHERE id = ?",
                (translation, now, str(existing["id"])),
            )
            overwritten += 1
        else:
            skipped += 1
    return {
        "imported": imported,
        "skipped": skipped,
        "overwritten": overwritten,
        "errors": errors,
    }


async def export_terms(db: Database) -> dict[str, Any]:
    """全部术语 → 导入同形状（term + translation）。"""
    await db.migrate()
    rows = await db.fetch_all(
        "SELECT term, definition FROM glossary_terms ORDER BY term ASC LIMIT 5000",
        (),
    )
    return {
        "terms": [
            {"term": str(row["term"]), "translation": str(row["definition"])}
            for row in rows
        ]
    }
