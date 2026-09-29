"""NEW-366 段落级搜索结果 —— 长文多段落命中分别列出 + 只保存相关片段。

语义：
- 命中段落从本人投影的 content_text（纯文本）按换行切分；每段带
  「命中词 + 段内文本」，偏移为字符口径（与 F072 一致，可交叉定位）；
- 只列有命中的段落（上限 20 + complete 诚实标注）；正文不出站整篇，
  只回命中段落（每段 ≤400 字）；
- 「只保存相关片段」是用户显式动作：POST fragments 落 per-user
  search_saved_fragments（单条 ≤400 字，总量上限 500，超界如实拒绝
  而非静默淘汰最老）。
"""

from typing import Any

from lumirss.search_index import split_terms
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_PARAGRAPHS = 20
_MAX_PARA_CHARS = 400
_MAX_SAVED = 500
_MAX_SAVED_TEXT = 400


class FragmentEntryMissing(LookupError):
    """entryRef 不在本账户投影 → 404 语义。"""


def split_paragraphs(content_text: str) -> list[tuple[int, str]]:
    """按换行切段，保留字符偏移（offset 指向段首；空段剔除）。"""
    paragraphs: list[tuple[int, str]] = []
    cursor = 0
    for line in (content_text or "").splitlines():
        start = cursor
        cursor += len(line) + 1  # +1 还原换行符宽度（近似口径，定位够用）
        stripped = line.strip()
        if stripped:
            paragraphs.append((start, stripped))
    return paragraphs


def hit_paragraphs(
    content_text: str, terms_folded: list[str]
) -> list[dict[str, Any]]:
    """含任一词条的段落（index 为非空段序号；offset 为字符偏移）。"""
    paragraphs = split_paragraphs(content_text)
    hits: list[dict[str, Any]] = []
    for index, (offset, text) in enumerate(paragraphs):
        lowered = text.casefold()
        matched = [term for term in terms_folded if term in lowered]
        if not matched:
            continue
        truncated = text[:_MAX_PARA_CHARS]
        hits.append(
            {
                "index": index,
                "offset": offset,
                "terms": matched,
                "text": truncated,
                "truncatedText": len(truncated) < len(text),
            }
        )
        if len(hits) >= _MAX_PARAGRAPHS:
            break
    return hits


async def paragraph_hits(
    db: Database, *, entry_ref: str, query: str
) -> dict[str, Any] | None:
    await db.migrate()
    row = await db.fetch_one(
        "SELECT entry_ref, title, content_text FROM search_entries"
        " WHERE entry_ref = ?",
        (entry_ref,),
    )
    if row is None:
        return None
    terms_folded = [term.casefold() for term in split_terms(query)]
    total_paragraphs = len(split_paragraphs(str(row["content_text"] or "")))
    hits = hit_paragraphs(str(row["content_text"] or ""), terms_folded)
    return {
        "entry": {
            "entryRef": entry_ref,
            "title": str(row["title"]),
        },
        "paragraphs": hits,
        "paragraphTotal": total_paragraphs,
        "complete": len(hits) < _MAX_PARAGRAPHS,
        "note": "只列有命中的段落；偏移为纯文本字符口径（与命中定位一致）。",
    }


# -- 片段保存（用户显式动作；唯一写路径） ------------------------------------


async def save_fragment(
    db: Database,
    *,
    entry_ref: str,
    query: str,
    paragraph_index: int,
    text: str,
) -> dict[str, Any]:
    await db.migrate()
    row = await db.fetch_one(
        "SELECT title FROM search_entries WHERE entry_ref = ?", (entry_ref,)
    )
    if row is None:
        raise FragmentEntryMissing(entry_ref)
    count_row = await db.fetch_one(
        "SELECT COUNT(*) AS n FROM search_saved_fragments"
    )
    if int(count_row["n"]) >= _MAX_SAVED:
        raise OverflowError(
            f"已保存片段达 {_MAX_SAVED} 条上限（如实拒绝；请先清理不再需要的片段）。"
        )
    clean_text = " ".join(text.split())
    if len(clean_text) > _MAX_SAVED_TEXT:
        clean_text = clean_text[:_MAX_SAVED_TEXT]
    now = utc_now()
    await db.execute(
        "INSERT INTO search_saved_fragments (entry_ref, entry_title, query,"
        " paragraph_index, text, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            entry_ref,
            str(row["title"]),
            " ".join(query.split())[:200],
            int(paragraph_index),
            clean_text,
            now,
        ),
    )
    saved = await db.fetch_one(
        "SELECT id, entry_ref, entry_title, query, paragraph_index, text,"
        " created_at FROM search_saved_fragments ORDER BY id DESC LIMIT 1"
    )
    assert saved is not None
    return _view(saved)


def _view(row: Any) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "entryRef": str(row["entry_ref"]),
        "entryTitle": str(row["entry_title"]),
        "query": str(row["query"]),
        "paragraphIndex": int(row["paragraph_index"]),
        "text": str(row["text"]),
        "createdAt": str(row["created_at"]),
    }


async def list_fragments(
    db: Database, *, entry_ref: str | None = None, limit: int = 100
) -> dict[str, Any]:
    await db.migrate()
    clean_limit = max(1, min(int(limit), 200))
    if entry_ref is not None:
        rows = await db.fetch_all(
            "SELECT id, entry_ref, entry_title, query, paragraph_index, text,"
            " created_at FROM search_saved_fragments WHERE entry_ref = ?"
            " ORDER BY id DESC LIMIT ?",
            (entry_ref, clean_limit),
        )
    else:
        rows = await db.fetch_all(
            "SELECT id, entry_ref, entry_title, query, paragraph_index, text,"
            " created_at FROM search_saved_fragments ORDER BY id DESC LIMIT ?",
            (clean_limit,),
        )
    return {"items": [_view(row) for row in rows]}


async def delete_fragment(db: Database, *, fragment_id: int) -> bool:
    await db.migrate()
    row = await db.fetch_one(
        "SELECT id FROM search_saved_fragments WHERE id = ?", (fragment_id,)
    )
    if row is None:
        return False
    await db.execute(
        "DELETE FROM search_saved_fragments WHERE id = ?", (fragment_id,)
    )
    return True
