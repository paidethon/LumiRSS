"""F070 知识卡片 — 卡片存储 + library 搜索腿纳入。

- UNIQUE(entry_ref, concept)：同 concept 保存幂等（已存在 → skipped，
  不覆盖用户编辑）；
- 保存成功即写入 search_library（ref=knowledge_card:{id}，title=
  concept，body=explanation），concept/explanation 可被全局搜索的
  library 腿检索；删除同步移除索引行；
- 原文删除 → 卡保留：列表时按 search_entries 存在性标注 stale。

全部 SQL 为内联字面量 + 绑定参数；本文件写站点 3 处
（insert/update 卡 + delete 卡；搜索索引写入经 LibrarySearchWriter）。
"""

import contextlib
import json as _json
import uuid as _uuid
from dataclasses import dataclass
from typing import Any

from lumirss.util import utc_now

MAX_CARDS_PER_SAVE = 10
CONCEPT_MAX = 100
EXPLANATION_MAX = 1000
QUOTE_MAX = 500

_INSERT_SQL = """INSERT INTO knowledge_cards (
id, entry_ref, concept, explanation, source_quote, quote_verified, created_at)
VALUES (?, ?, ?, ?, ?, ?, ?)"""

_UPDATE_SQL = """UPDATE knowledge_cards SET explanation = ?, source_quote = ?,
quote_verified = ?, created_at = ? WHERE id = ?"""


@dataclass(frozen=True)
class KnowledgeCard:
    id: str
    entry_ref: str
    concept: str
    explanation: str
    source_quote: str
    quote_verified: bool
    created_at: str


async def find_by_concept(db: Any, entry_ref: str, concept: str) -> KnowledgeCard | None:
    row = await db.fetch_one(
        "SELECT id, entry_ref, concept, explanation, source_quote, quote_verified, created_at FROM knowledge_cards WHERE entry_ref = ? AND concept = ?",
        (entry_ref, concept),
    )
    return _card(row) if row is not None else None


async def upsert_card(
    db: Any,
    search_writer: Any,
    *,
    entry_ref: str,
    concept: str,
    explanation: str,
    source_quote: str,
    quote_verified: bool,
) -> tuple[KnowledgeCard, bool]:
    """保存卡片；同 (entry_ref, concept) 已存在 → 返回既有卡 + created=False
    （幂等 skipped，不覆盖）。成功后同步 library 搜索索引。"""
    await db.migrate()
    existing = await find_by_concept(db, entry_ref, concept)
    if existing is not None:
        return existing, False
    card_id = str(_uuid.uuid4())
    now = utc_now()
    await db.execute(
        _INSERT_SQL,
        (card_id, entry_ref, concept, explanation, source_quote, 1 if quote_verified else 0, now),
    )
    await _index_card(search_writer, card_id, concept, explanation)
    return (
        KnowledgeCard(card_id, entry_ref, concept, explanation, source_quote, quote_verified, now),
        True,
    )


async def _index_card(search_writer: Any, card_id: str, concept: str, explanation: str) -> None:
    if search_writer is None:
        return
    with contextlib.suppress(Exception):  # 索引失败不影响卡片落库
        await search_writer.upsert(
            ref=f"knowledge_card:{card_id}",
            kind="knowledge_card",
            title=concept,
            body=explanation,
            url=None,
        )


async def delete_card(db: Any, search_writer: Any, card_id: str) -> bool:
    await db.migrate()
    row = await db.fetch_one("SELECT id FROM knowledge_cards WHERE id = ?", (card_id,))
    if row is None:
        return False
    await db.execute("DELETE FROM knowledge_cards WHERE id = ?", (card_id,))
    if search_writer is not None:
        with contextlib.suppress(Exception):
            await search_writer.delete(f"knowledge_card:{card_id}")
    return True


async def list_cards(db: Any, q: str | None = None, limit: int = 200) -> list[dict[str, Any]]:
    """卡片列表（含 entry 标题；原文缺失 → stale=True 诚实标注）。"""
    await db.migrate()
    like = f"%{(q or '').strip()}%"
    rows = await db.fetch_all(
        """SELECT kc.id, kc.entry_ref, kc.concept, kc.explanation,
        kc.source_quote, kc.quote_verified, kc.created_at,
        se.title AS entry_title
        FROM knowledge_cards kc
        LEFT JOIN search_entries se ON se.entry_ref = kc.entry_ref
        WHERE ? = '' OR kc.concept LIKE ? OR kc.explanation LIKE ?
        ORDER BY kc.created_at DESC LIMIT ?""",
        ((q or '').strip(), like, like, max(1, min(limit, 500))),
    )
    return [
        {
            "id": str(row["id"]),
            "entryRef": str(row["entry_ref"]),
            "concept": str(row["concept"]),
            "explanation": str(row["explanation"]),
            "sourceQuote": str(row["source_quote"] or ""),
            "quoteVerified": bool(row["quote_verified"]),
            "createdAt": str(row["created_at"]),
            "entryTitle": row["entry_title"],
            # 原文删除 → 卡保留标 stale
            "stale": row["entry_title"] is None,
        }
        for row in rows
    ]


def _card(row: Any) -> KnowledgeCard:
    return KnowledgeCard(
        id=str(row["id"]),
        entry_ref=str(row["entry_ref"]),
        concept=str(row["concept"]),
        explanation=str(row["explanation"]),
        source_quote=str(row["source_quote"] or ""),
        quote_verified=bool(row["quote_verified"]),
        created_at=str(row["created_at"]),
    )


def dumps(value: Any) -> str:
    return _json.dumps(value, ensure_ascii=False)
