"""NEW-365 搜索排除词建议审批 —— 从用户标记的不相关结果提取候选词。

语义（诚实边界）：
- 候选只从用户显式标记为「不相关」的结果（entryRefs）提取：分词
  （拉丁词按空白+边界；CJK 连续串切 2-gram），剔除查询词本身与
  stopword 级超高频规则外，按「含该词的标记条数」排序——纯计数，
  无模型调用、无黑盒分数；
- 候选绝不自动生效：只有 POST approve（用户确认）后才写入
  search_exclusion_words（per-user），由客户端把它并进该查询的
  exclude 参数；删除即撤销；
- 全部 SQL 绑定参数；文本有界（词 ≤24 字，候选 ≤8）。
"""

import re
import unicodedata
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_MARKED_REFS = 50
_MAX_CANDIDATES = 8
_MAX_WORD_CHARS = 24
_MAX_STORED_PER_QUERY = 20

_LATIN_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'’\-]*")
_CJK_RUN = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]+")

# 出现在 ≥80% 标记结果里的词大概率是页面骨架词（如「转载」「阅读」
# ——仍允许进入候选（用户可自行判断），只做 display 排序不剔除。
_MIN_MARKED_HITS = 2


def query_key(query: str) -> str:
    """查询规范化键：casefold + 压缩空白（同查询跨写法共享确认词）。"""
    return " ".join(query.split()).casefold()


def tokenize_for_candidates(text: str) -> list[str]:
    """候选分词：拉丁词整取；CJK/日文/韩文连续串切 2-gram。"""
    tokens: list[str] = []
    for match in _LATIN_WORD.finditer(text):
        token = match.group(0).casefold()
        if 2 <= len(token) <= _MAX_WORD_CHARS:
            tokens.append(token)
    for match in _CJK_RUN.finditer(text):
        run = match.group(0)
        if len(run) == 1:
            tokens.append(run)
            continue
        for i in range(len(run) - 1):
            tokens.append(run[i : i + 2])
    return tokens


async def exclusion_candidates(
    db: Database, *, query: str, marked_refs: list[str]
) -> dict[str, Any]:
    """从标记为不相关的结果中提取候选排除词（纯计数，可解释）。"""
    await db.migrate()
    refs: list[str] = []
    for ref in marked_refs:
        clean = str(ref).strip()
        if clean and clean not in refs:
            refs.append(clean)
    refs = refs[:_MAX_MARKED_REFS]
    term_set = {t.casefold() for t in query.split()}
    counts: dict[str, int] = {}
    rows_total = 0
    for ref in refs:
        row = await db.fetch_one(
            "SELECT title, content_text FROM search_entries WHERE entry_ref = ?",
            (ref,),
        )
        if row is None:
            continue  # 不在本账户投影 → 静默跳过（missing 如实计数）
        rows_total += 1
        text = f"{row['title']}\n{row['content_text'] or ''}"
        seen_in_row: set[str] = set()
        for token in tokenize_for_candidates(text):
            if token in term_set:
                continue
            seen_in_row.add(token)
        for token in seen_in_row:
            counts[token] = counts.get(token, 0) + 1
    candidates = [
        {"word": word, "markedHits": count}
        for word, count in counts.items()
        if count >= _MIN_MARKED_HITS
    ]
    candidates.sort(key=lambda item: (-item["markedHits"], item["word"]))
    return {
        "candidates": candidates[:_MAX_CANDIDATES],
        "markedScanned": rows_total,
        "markedMissing": len(refs) - rows_total,
        "queryKey": query_key(query),
        "note": "候选按含该词的标记条数排序；确认前绝不进入查询。",
    }


# -- 已确认词（唯一的持久化面；approve 之外的写路径不存在） ----------------


async def approved_words(db: Database, *, query: str) -> dict[str, Any]:
    await db.migrate()
    key = query_key(query)
    rows = await db.fetch_all(
        "SELECT id, word, created_at FROM search_exclusion_words"
        " WHERE query_key = ? ORDER BY id DESC LIMIT ?",
        (key, _MAX_STORED_PER_QUERY),
    )
    return {
        "queryKey": key,
        "items": [
            {"id": int(row["id"]), "word": str(row["word"]), "createdAt": str(row["created_at"])}
            for row in rows
        ],
        "cap": _MAX_STORED_PER_QUERY,
    }


class ExclusionWordInvalid(ValueError):
    """确认词非法（长度/字符）→ 422。"""


_WORD_OK = re.compile(r"^.{1,24}$", re.DOTALL)


async def approve_word(db: Database, *, query: str, word: str) -> dict[str, Any]:
    clean = unicodedata.normalize("NFKC", word).strip()
    if not clean or not _WORD_OK.match(clean):
        raise ExclusionWordInvalid("排除词须为 1-24 个字符。")
    key = query_key(query)
    existing = await db.fetch_one(
        "SELECT id, word, created_at FROM search_exclusion_words"
        " WHERE query_key = ? AND word = ?",
        (key, clean),
    )
    if existing is not None:
        return {
            "id": int(existing["id"]),
            "word": str(existing["word"]),
            "createdAt": str(existing["created_at"]),
            "already": True,
        }
    count_row = await db.fetch_one(
        "SELECT COUNT(*) AS n FROM search_exclusion_words WHERE query_key = ?",
        (key,),
    )
    if int(count_row["n"]) >= _MAX_STORED_PER_QUERY:
        raise ExclusionWordInvalid(
            f"该查询已确认 {_MAX_STORED_PER_QUERY} 个排除词（如实拒绝，不静默淘汰）。"
        )
    now = utc_now()
    await db.execute(
        "INSERT INTO search_exclusion_words (query_key, word, created_at)"
        " VALUES (?, ?, ?)",
        (key, clean, now),
    )
    row = await db.fetch_one(
        "SELECT id, word, created_at FROM search_exclusion_words"
        " WHERE query_key = ? AND word = ?",
        (key, clean),
    )
    assert row is not None
    return {
        "id": int(row["id"]),
        "word": str(row["word"]),
        "createdAt": str(row["created_at"]),
        "already": False,
    }


async def delete_word(db: Database, *, word_id: int) -> bool:
    await db.migrate()
    row = await db.fetch_one(
        "SELECT id FROM search_exclusion_words WHERE id = ?", (word_id,)
    )
    if row is None:
        return False
    await db.execute("DELETE FROM search_exclusion_words WHERE id = ?", (word_id,))
    return True
