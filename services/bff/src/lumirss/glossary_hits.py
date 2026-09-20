"""F029 术语命中预览 —— 现役 glossary 在文章正文中的匹配。

匹配规则（与 UI 预览共用同一实现）：

- 拉丁词（ASCII 字母/数字开头）按词边界匹配（\\b），不误中更长词；
- CJK 词按子串匹配；
- 重叠命中时最长术语优先（同位置只记一次，取最长）；
- 术语表为空 → 无命中、prompt 附加块为空字符串（行为与从前一致）。

prompt 附加块与预览端点由同一函数产出（format_glossary_prompt_block），
保证「预览的 = 实际发给 Provider 的」。
"""

import re
from typing import Any

from lumirss.storage import Database

# 拉丁词边界：术语两端是非字母数字（Unicode 词边界按 ASCII 判定足够）。
_WORD_RE_CACHE: dict[str, re.Pattern[str]] = {}


def _is_latin(term: str) -> bool:
    return all(ord(ch) < 0x2E80 for ch in term)


def _term_pattern(term: str) -> re.Pattern[str]:
    if _is_latin(term):
        pattern = _WORD_RE_CACHE.get(term)
        if pattern is None:
            pattern = re.compile(
                r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])",
                re.IGNORECASE,
            )
            _WORD_RE_CACHE[term] = pattern
        return pattern
    return re.compile(re.escape(term))


def compute_hits(
    content_text: str, terms: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """在正文中匹配术语：返回 [{term, translation, count}]（最长优先）。

    实现：对每个术语找全部命中区间；重叠时保留最长术语——按区间起点
    排序后贪心选择（同起点取更长；被已选区间完全覆盖的丢弃）。
    """
    if not content_text or not terms:
        return []
    intervals: list[tuple[int, int, str, str]] = []
    for item in terms:
        term = str(item.get("term") or "")
        translation = str(item.get("translation") or item.get("definition") or "")
        if not term:
            continue
        pattern = _term_pattern(term)
        for match in pattern.finditer(content_text):
            intervals.append((match.start(), match.end(), term, translation))
    # 最长优先 + 起点升序的贪心覆盖选择。
    intervals.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    selected: list[tuple[int, int, str, str]] = []
    counts: dict[str, int] = {}
    for start, end, term, translation in intervals:
        if any(start < s_end and s_start < end for s_start, s_end, _, _ in selected):
            continue
        selected.append((start, end, term, translation))
        counts[term] = counts.get(term, 0) + 1
    # 输出按术语首次出现顺序；每术语一行（count 聚合）。
    ordered: list[str] = []
    for _, _, term, _ in selected:
        if term not in ordered:
            ordered.append(term)
    translation_by_term: dict[str, str] = {
        str(item.get("term") or ""): str(
            item.get("translation") or item.get("definition") or ""
        )
        for item in terms
    }
    return [
        {"term": term, "translation": translation_by_term.get(term, ""), "count": counts[term]}
        for term in ordered
    ]


async def load_glossary_terms(db: Database, limit: int = 500) -> list[dict[str, Any]]:
    """现役术语表（term + translation(=definition)）。"""
    await db.migrate()
    rows = await db.fetch_all(
        "SELECT term, definition FROM glossary_terms ORDER BY updated_at DESC LIMIT ?",
        (limit,),
    )
    return [
        {"term": str(row["term"]), "translation": str(row["definition"])}
        for row in rows
    ]


def format_glossary_prompt_block(hits: list[dict[str, Any]]) -> str:
    """受控格式（预览端点与生成端点共用；空表 → 空串 = 行为不变）。"""
    if not hits:
        return ""
    lines = ["术语表："] + [
        f"{hit['term']}→{hit['translation']}" for hit in hits
    ]
    return "\n".join(lines)


async def attach_glossary_block(db: Database, content_text: str) -> str:
    """生成端点的便捷入口：读术语表 → 命中 → 格式化（空表 = ''）。"""
    terms = await load_glossary_terms(db)
    return format_glossary_prompt_block(compute_hits(content_text, terms))
