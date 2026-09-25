"""N154 证据文本收集 —— cited refs → 可核验的原文文本。

来源优先级（纯只读）：
1. rag_chunks（当前模型的分块全文）—— 语义检索实际喂给模型的内容；
2. 投影正文回退（search_entries.content_text / search_library.body，
   截断）—— 未索引条目仍可对引用做诚实核验。

返回 {ref: text}；文本在收集处即截断（单 ref 有界，绝不整库取）。
"""

from typing import Any

# 单 ref 证据文本上限（chars）：足够核验主张，绝不把整篇长文留在内存。
_MAX_TEXT_PER_REF = 4000
_MAX_REFS = 12


async def collect_evidence_texts(db: Any, refs: list[str]) -> dict[str, str]:
    """cited refs → {ref: 拼接后的分块/正文文本}（有界）。"""
    from lumirss.rag import DEFAULT_MODEL_ID, live_model_id

    cleaned = list(dict.fromkeys(str(r) for r in refs if r))[:_MAX_REFS]
    if not cleaned:
        return {}
    await db.migrate()
    # N157：分块按 LIVE 模型读取（换模型后 swap 前仍是旧模型的行）。
    model_id = await live_model_id(db, DEFAULT_MODEL_ID)
    texts: dict[str, str] = {}
    for ref in cleaned:
        rows = await db.fetch_all(
            "SELECT text FROM rag_chunks WHERE ref = ? AND model_id = ? ORDER BY ord ASC LIMIT ?",
            (ref, model_id, 40),
        )
        if rows:
            joined = "\n".join(str(row["text"] or "") for row in rows)
            texts[ref] = joined[:_MAX_TEXT_PER_REF]
            continue
        row = await db.fetch_one(
            "SELECT content_text FROM search_entries WHERE entry_ref = ?", (ref,)
        )
        if row is not None:
            texts[ref] = str(row["content_text"] or "")[:_MAX_TEXT_PER_REF]
            continue
        row = await db.fetch_one(
            "SELECT body FROM search_library WHERE ref = ?", (ref,)
        )
        if row is not None:
            texts[ref] = str(row["body"] or "")[:_MAX_TEXT_PER_REF]
    return texts
