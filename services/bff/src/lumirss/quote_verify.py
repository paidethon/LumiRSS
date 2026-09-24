"""N154/N155 证据核验共享模块 —— 引用核验 / 主张切分 / 证据强弱。

- quote_verified：locateSentence 式核验（规范化空白后子串匹配，≥8 字）。
  语义与 entry_ai（F067 compare）原有的 _quote_verified 完全一致——
  本模块是唯一实现，entry_ai 改为复用（行为零变化）。
- claim_segments：把回答切成「文档事实主张」候选句（中英标点分句，
  规范化后 ≥ MIN_CLAIM_CHARS 才算主张——寒暄/短语不产生主张）。
- evidence_strength：cited spans（被引用分块/正文文本）vs 回答主张的
  重叠分级：direct（全部主张可定位到引用文本）/ partial（部分）/
  none（零重叠或无主张）。纯函数、只读、绝无 provider 调用。
"""

import re
from typing import Literal

# 与 F067/F069 引用核验同款下限：过短的「引用」无法可靠定位。
MIN_QUOTE_CHARS = 8
# 主张句最小规范化长度：低于此值视为寒暄/连接语，不构成文档事实主张。
MIN_CLAIM_CHARS = 12

EvidenceStrength = Literal["direct", "partial", "none"]

_WS_RE = re.compile(r"\s+")
_SPLIT_RE = re.compile(r"[。！？!?；;\n]+")


def normalize_claim(value: str) -> str:
    """规范化：去除全部空白 + 小写（与 quote 核验同一口径）。"""
    return _WS_RE.sub("", value or "").lower()


def quote_verified(quote: str, source: str) -> bool:
    """quote 是否为 source 的逐字子串（规范化空白后；≥8 字才核验）。"""
    q = normalize_claim(quote)
    if len(q) < MIN_QUOTE_CHARS:
        return False
    return q in normalize_claim(source)


def claim_segments(text: str, *, min_chars: int = MIN_CLAIM_CHARS) -> list[str]:
    """回答 → 文档事实主张候选句（保序去重；规范化后 ≥ min_chars）。"""
    segments: list[str] = []
    seen: set[str] = set()
    for raw in _SPLIT_RE.split(text or ""):
        normalized = normalize_claim(raw)
        if len(normalized) < min_chars:
            continue
        if normalized in seen:
            continue
        seen.add(normalized)
        segments.append(raw.strip())
    return segments


def evidence_strength(
    answer: str, cited_texts: list[str]
) -> EvidenceStrength:
    """回答的证据强弱（N154）：主张 vs 被引用文本的重叠分级。

    - direct：≥1 条主张且全部主张都能定位到引用文本；
    - partial：部分主张可定位；
    - none：无主张或零定位（诚实「无直接支持」，绝不叫「置信度」）。
    """
    segments = claim_segments(answer)
    if not segments:
        return "none"
    corpus = normalize_claim("\n".join(t or "" for t in cited_texts))
    if not corpus:
        return "none"
    verified = sum(1 for segment in segments if normalize_claim(segment) in corpus)
    if verified == 0:
        return "none"
    if verified == len(segments):
        return "direct"
    return "partial"
