"""N156 资料冲突对照 —— 纯词法的重叠句差异检测（零模型调用）。

F28 compare_facts 的模型裁决之外的通用补位：对给定 refs 的两两组合，
在句级做纯文本比对——

- 分句：按中英终止符（。！？!?；;.）与换行切分；每 ref 有界
  （前 400 句），绝不整篇留在内存；
- 重叠：句子的字符 bigram 集合 Jaccard ≥ 0.55 且两句不完全相等
  → 视为「高度相似但存在差异」的候选对（bigram 对 CJK 与西文都
  稳定，不依赖分词器）；
- 差异分类（date 比 number 更具体，优先判定）：
  * date：日期 token 集合不同（YYYY-MM-DD / YYYY/MM/DD / M月D日；
  日期内的数字不误报为 number）；
  * number：非日期数字 token 集合不同（复用 N082 的千分位/小数/%
  口径）；
  * other：数字与日期一致但词汇仍有差异（其他内容性差异）；
- 诚实边界（响应 basis=lexical、UI 同口径）：本比对是纯词法，不是
  语义裁决——差异不必然是错误（可能是更正、口径或单位换算），判断
  留给读者。

本模块绝不 import 任何 provider/模型设施：测试可断言零模型调用。
"""

import re
from itertools import combinations

from lumirss.ai_translation_verification import extract_number_tokens

_OVERLAP_THRESHOLD = 0.5
_MAX_SENTENCES_PER_REF = 400
_MAX_CONFLICTS = 20
_QUOTE_LENGTH = 160
_DATE_RE = re.compile(r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[。！？!?；;])\s*|\n+")


class QaConflictInvalid(ValueError):
    """对照载荷非法（refs 数量/存在性），映射 422。"""


def split_sentences(text: str) -> list[str]:
    """分句（去空句；有界）。"""
    if not text:
        return []
    raw = _SENTENCE_SPLIT_RE.split(text)
    return [part.strip() for part in raw if part and part.strip()][
        :_MAX_SENTENCES_PER_REF
    ]


def extract_date_tokens(text: str) -> set[str]:
    """日期 token（形如 2024-01-02 / 2024/1/2 / 2024年1月2日）。"""
    if not text:
        return set()
    return set(_DATE_RE.findall(text))


def _bigrams(sentence: str) -> set[str]:
    """归一化后的字符 bigram 集合（空白/大小写归一）。"""
    normalized = re.sub(r"\s+", "", sentence.lower())
    if len(normalized) < 2:
        return {normalized} if normalized else set()
    return {
        normalized[i : i + 2] for i in range(len(normalized) - 1)
    }


def _jaccard(a: set[str], b: set[str]) -> float:
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


def _strip_dates(sentence: str) -> str:
    """去掉日期子串后的残句（日期里的数字不参与 number 分类）。"""
    return _DATE_RE.sub("", sentence)


def _diff_kind(sa: str, sb: str) -> str | None:
    """分类：日期集合不同 → date（日期里的数字不误报为 number）；
    非日期数字集合不同 → number；纯词汇差异 → other；完全相同 →
    None（无差异不成冲突）。"""
    dates_a = extract_date_tokens(sa)
    dates_b = extract_date_tokens(sb)
    if dates_a != dates_b:
        return "date"
    numbers_a = set(extract_number_tokens(_strip_dates(sa)))
    numbers_b = set(extract_number_tokens(_strip_dates(sb)))
    if numbers_a != numbers_b:
        return "number"
    if _bigrams(sa) == _bigrams(sb):
        return None
    return "other"


def detect_conflicts(texts: dict[str, str]) -> list[dict]:
    """{ref: text} → 两两 ref 的冲突清单（按重叠度降序，有界 20）。

    每条：{aRef, bRef, aQuote, bQuote, diffKind, overlap}——证据块定位
    （blockIndex）由调用方补充，本函数只做词法检测。"""
    conflicts: list[dict] = []
    refs = sorted(texts)
    for ref_a, ref_b in combinations(refs, 2):
        sentences_a = split_sentences(str(texts[ref_a]))
        sentences_b = split_sentences(str(texts[ref_b]))
        seen: set[tuple[str, str, str]] = set()
        for sa in sentences_a:
            grams_a = _bigrams(sa)
            for sb in sentences_b:
                overlap = _jaccard(grams_a, _bigrams(sb))
                if overlap < _OVERLAP_THRESHOLD:
                    continue
                kind = _diff_kind(sa, sb)
                if kind is None:
                    continue
                key = (sa[:80], sb[:80], kind)
                if key in seen:
                    continue
                seen.add(key)
                conflicts.append(
                    {
                        "aRef": ref_a,
                        "bRef": ref_b,
                        "aQuote": sa[:_QUOTE_LENGTH],
                        "bQuote": sb[:_QUOTE_LENGTH],
                        "diffKind": kind,
                        "overlap": round(overlap, 3),
                    }
                )
    conflicts.sort(key=lambda item: (-item["overlap"], item["aQuote"], item["bQuote"]))
    return conflicts[:_MAX_CONFLICTS]
