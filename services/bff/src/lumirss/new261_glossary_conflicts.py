"""NEW-261 术语表冲突处理 —— 同名多义术语的来源/适用范围与生效译法。

glossary_terms 天然允许同一 term 多条词目。冲突时「哪条译法生效」
此前由列表顺序偶然决定；本模块给出显式、可解释的解析：

- 冲突发现：按 term 分组，组内存在 >1 条「译法（definition）不同」
  的词目即冲突；每组列出全部变体（id / 译法 / 来源关联 / 更新时间）
  ——来源与适用范围可见；
- 生效选择：用户为当前来源（scope='source'，绑定 feed_url）或项目
  （scope='project'）选择一条词目作为生效译法；解析优先级
  来源选择 > 项目选择 > 默认（updated_at 最新）；
- 缓存纪律（与 FIX-144 同口径）：任何选择写入/清除都推进
  glossary_version（分段翻译缓存身份组成部分）——已产生的译文缓存
  行保持原身份、原样展示；其后的新生成按生效译法出稿。

``effective_terms`` 是术语读取路径（prompt 附加块、命中预览）的
统一入口：按 term 去重后恰好返回一条生效词目。

全部 SQL 为内联字面量 + 绑定参数；写站点：set/clear 各一处。
"""

import uuid
from typing import Any

from lumirss.glossary import bump_glossary_version
from lumirss.storage import Database
from lumirss.util import utc_now

MAX_TERM = 100

_LIST_TERMS_SQL = (
    "SELECT id, term, definition, source_ref, protect, created_at, updated_at "
    "FROM glossary_terms ORDER BY updated_at DESC, id DESC LIMIT ?"
)
_LIST_CHOICES_SQL = (
    "SELECT id, term, chosen_term_id, scope, source_url, updated_at "
    "FROM glossary_term_choices ORDER BY updated_at DESC"
)


class GlossaryChoiceInvalid(ValueError):
    """选择负载非法（未知术语/词目、scope 与 sourceUrl 组合错误）→ 422。"""


def _variant(row: Any) -> dict[str, Any]:
    return {
        "termId": str(row["id"]),
        "definition": str(row["definition"]),
        "sourceRef": row["source_ref"],
        "protect": bool(row["protect"]),
        "updatedAt": str(row["updated_at"] or ""),
    }


async def list_conflicts(db: Database) -> list[dict[str, Any]]:
    """同名多义冲突清单（术语按 updated_at 新→旧；变体同序）。"""
    await db.migrate()
    rows = await db.fetch_all(_LIST_TERMS_SQL, (500,))
    groups: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for row in rows:
        term = str(row["term"])
        if term not in groups:
            groups[term] = []
            order.append(term)
        groups[term].append(_variant(row))
    choices = await _choices_by_term(db)
    result: list[dict[str, Any]] = []
    for term in order:
        variants = groups[term]
        definitions = {v["definition"] for v in variants}
        if len(variants) < 2 or len(definitions) < 2:
            continue
        result.append(
            {
                "term": term,
                "variants": variants,
                "chosen": choices.get(term),
            }
        )
    return result


async def _choices_by_term(db: Database) -> dict[str, dict[str, Any]]:
    rows = await db.fetch_all(_LIST_CHOICES_SQL)
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        result.setdefault(
            str(row["term"]),
            {
                "chosenTermId": str(row["chosen_term_id"]),
                "scope": str(row["scope"]),
                "sourceUrl": str(row["source_url"] or ""),
                "updatedAt": str(row["updated_at"] or ""),
            },
        )
    return result


async def set_choice(
    db: Database,
    term: str,
    chosen_term_id: str,
    scope: str,
    source_url: str = "",
) -> dict[str, Any]:
    """登记生效译法选择（来源选择 / 项目选择；upsert 覆盖同键选择）。

    chosen_term_id 必须是现役词目且 term 与之匹配；scope='project'
    时忽略 source_url（归一为 ''）。写入推进 glossary_version。"""
    clean_term = term.strip() if isinstance(term, str) else ""
    if not clean_term or len(clean_term) > MAX_TERM:
        raise GlossaryChoiceInvalid("term 非法。")
    if scope not in ("project", "source"):
        raise GlossaryChoiceInvalid("scope 必须是 project 或 source。")
    clean_url = (source_url or "").strip() if scope == "source" else ""
    if scope == "source" and not clean_url:
        raise GlossaryChoiceInvalid("scope=source 需要 sourceUrl。")
    await db.migrate()
    row = await db.fetch_one(
        "SELECT id, term FROM glossary_terms WHERE id = ?", (chosen_term_id,)
    )
    if row is None or str(row["term"]) != clean_term:
        raise GlossaryChoiceInvalid("chosenTermId 不是该术语的现役词目。")
    now = utc_now()
    existing = await db.fetch_one(
        "SELECT id FROM glossary_term_choices WHERE term = ? AND scope = ? AND source_url = ?",
        (clean_term, scope, clean_url),
    )
    if existing is not None:
        await db.execute(
            "UPDATE glossary_term_choices SET chosen_term_id = ?, updated_at = ? WHERE id = ?",
            (chosen_term_id, now, str(existing["id"])),
        )
        choice_id = str(existing["id"])
    else:
        choice_id = f"gtc-{uuid.uuid4().hex[:16]}"
        await db.execute(
            "INSERT INTO glossary_term_choices "
            "(id, term, chosen_term_id, scope, source_url, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (choice_id, clean_term, chosen_term_id, scope, clean_url, now, now),
        )
    await bump_glossary_version(db)
    return {
        "term": clean_term,
        "chosenTermId": chosen_term_id,
        "scope": scope,
        "sourceUrl": clean_url,
        "updatedAt": now,
    }


async def clear_choice(
    db: Database, term: str, scope: str, source_url: str = ""
) -> bool:
    """清除一条选择（回到默认解析）。无该选择 → False。"""
    clean_term = term.strip() if isinstance(term, str) else ""
    clean_url = (source_url or "").strip() if scope == "source" else ""
    await db.migrate()
    row = await db.fetch_one(
        "SELECT id FROM glossary_term_choices WHERE term = ? AND scope = ? AND source_url = ?",
        (clean_term, scope, clean_url),
    )
    if row is None:
        return False
    await db.execute(
        "DELETE FROM glossary_term_choices WHERE id = ?", (str(row["id"]),)
    )
    await bump_glossary_version(db)
    return True


async def effective_terms(
    db: Database, feed_url: str | None = None, limit: int = 500
) -> list[dict[str, Any]]:
    """生效术语表：按 term 去重，恰好一条生效词目。

    解析优先级：来源选择（feed_url 匹配）> 项目选择 > 默认
    （updated_at 最新，即词目列表序第一条）。feed_url 为 None 时
    来源选择不参与。选择指向已删除词目 → 诚实降级到默认。
    输出形状与 glossary_hits.load_glossary_terms 一致。"""
    await db.migrate()
    rows = await db.fetch_all(_LIST_TERMS_SQL, (max(1, min(limit, 500)),))
    project_choice: dict[str, str] = {}
    source_choice: dict[str, str] = {}
    for row in await db.fetch_all(_LIST_CHOICES_SQL):
        term = str(row["term"])
        chosen_id = str(row["chosen_term_id"])
        if str(row["scope"]) == "source":
            if feed_url and str(row["source_url"] or "") == feed_url:
                source_choice.setdefault(term, chosen_id)
        else:
            project_choice.setdefault(term, chosen_id)
    chosen_ids = {**project_choice, **source_choice}

    by_term: dict[str, list[Any]] = {}
    order: list[str] = []
    for row in rows:
        term = str(row["term"])
        if term not in by_term:
            by_term[term] = []
            order.append(term)
        by_term[term].append(row)
    result: list[dict[str, Any]] = []
    for term in order:
        variants = by_term[term]
        chosen = chosen_ids.get(term)
        pick = (
            next((v for v in variants if str(v["id"]) == chosen), None)
            if chosen
            else None
        )
        if pick is None:  # 无选择 / 选择词目已删除 → 默认（最新一条）
            pick = variants[0]
        result.append({"term": term, "translation": str(pick["definition"])})
    return result


async def attach_effective_glossary_block(
    db: Database, content_text: str
) -> str:
    """生成端的术语附加块：按生效译法去重后的术语表 → 命中 → 受控格式。

    与 ``glossary_hits.attach_glossary_block`` 的唯一差异是术语读取
    走 ``effective_terms``（来源/项目选择生效；同词多义只出一条译法
    ——不再由列表顺序偶然决定）。空表 → 空串（行为与从前一致）。"""
    from lumirss.glossary_hits import (
        compute_hits,
        format_glossary_prompt_block,
    )

    terms = await effective_terms(db)
    if not terms:
        return ""
    return format_glossary_prompt_block(compute_hits(content_text, terms))
