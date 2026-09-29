"""NEW-363 跨字段命中说明 —— 标题/正文/作者/来源/本人笔记的命中归位。

语义：
- RSS 四列复用 search_index.matched_fields 的既有口径（casefold 子串）；
- 新增「本人笔记」列：annotations 表在 per-user 库——只可能是本人
  批注；任一词条出现在 excerpt 或 note 中即算笔记命中，随响应给出
  命中计数与首条摘录（点击定位的锚点）；
- 本路由只做归位说明，不改变 /search 的命中集合本身。

有界：单次最多 50 个 entryRef；不在本账户投影的 ref 如实计入
missing（与 404 同语义，不泄露他人条目存在性）。
"""

from typing import Any

from lumirss.search_index import matched_fields, split_terms

_MAX_REFS = 50
_NOTE_SNIPPET_WIDTH = 80


def _note_snippet(text: str, terms_folded: list[str]) -> str:
    lowered = text.casefold()
    position = -1
    for term in terms_folded:
        position = lowered.find(term)
        if position >= 0:
            break
    if position < 0:
        return text[:_NOTE_SNIPPET_WIDTH]
    start = max(0, position - _NOTE_SNIPPET_WIDTH // 2)
    end = min(len(text), position + _NOTE_SNIPPET_WIDTH // 2)
    prefix = "… " if start > 0 else ""
    suffix = " …" if end < len(text) else ""
    return f"{prefix}{text[start:end].strip()}{suffix}"


async def field_hits(
    db: Any, *, query: str, entry_refs: list[str]
) -> dict[str, Any]:
    """逐 ref 的命中字段归位（含本人笔记列）。"""
    await db.migrate()
    terms_folded = [term.casefold() for term in split_terms(query)]
    refs = [ref.strip() for ref in entry_refs if ref.strip()][:_MAX_REFS]
    items: list[dict[str, Any]] = []
    missing: list[str] = []
    for ref in refs:
        row = await db.fetch_one(
            "SELECT entry_ref, title, feed_title, feed_url, author, url,"
            " content_text FROM search_entries WHERE entry_ref = ?",
            (ref,),
        )
        if row is None:
            missing.append(ref)
            continue
        fields = matched_fields(row, terms_folded)
        note_hit: dict[str, Any] | None = None
        annotation_rows = await db.fetch_all(
            "SELECT id, excerpt, note FROM annotations WHERE entry_ref = ?"
            " ORDER BY created_at ASC LIMIT 100",
            (ref,),
        )
        hits = 0
        first_text = ""
        for annotation in annotation_rows:
            combined = " ".join(
                part
                for part in (
                    str(annotation["excerpt"] or ""),
                    str(annotation["note"] or ""),
                )
                if part
            )
            lowered = combined.casefold()
            if any(term in lowered for term in terms_folded):
                hits += 1
                if not first_text:
                    first_text = _note_snippet(combined, terms_folded)
        if hits:
            note_hit = {"count": hits, "excerpt": first_text}
            if "note" not in fields:
                fields.append("note")
        items.append(
            {
                "entryRef": ref,
                "fields": fields,
                "noteHit": note_hit,
            }
        )
    return {
        "items": items,
        "missing": missing,
        "terms": terms_folded,
        "note": "fields 与 /search 的 matchedFields 同口径；note 列只统计本人批注。",
    }
