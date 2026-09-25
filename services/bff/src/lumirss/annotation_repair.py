"""N071 批注原文漂移修复 — 纯匹配逻辑（无 IO，可单测）。

批注的摘录在原文重构后可能找不回（resolveAnchor 失效）。这里把
「存量引文」对「当前正文块」重新检索：

- 块切分：html_to_text 的块级标签逐块换行，contentText 按行即块；
- 打分：exact/prefix 归一化包含 = 1.0；否则滑窗 difflib 模糊比，
  窗口与引文等长、步长 len/4，取最大值；
- 候选门槛 ≥0.8；修复接受门槛 ≥0.5（best < 0.5 → 拒绝自动修复，
  只能手动重选文本 —— 诚实优先，绝不假装命中）。

分数是相似度证据，不是内容缓存：本模块不保留任何原文片段之外
的派生文本（excerpt 只回显块内窗口，便于人工辨认）。
"""

import re
from difflib import SequenceMatcher

FUZZY_THRESHOLD = 0.8
REPAIR_MIN_SCORE = 0.5
MAX_CANDIDATES = 5
_EXCERPT_MAX = 200


def split_blocks(content_text: str) -> list[str]:
    """contentText → 非空正文块列表（顺序即文档顺序，blockIndex 从 0 起）。"""
    return [part.strip() for part in (content_text or "").split("\n") if part.strip()]


def _normalize(text: str) -> str:
    """匹配前归一化：去全部空白（换行差异不产生假阴性）、不折叠大小写
    （中英混排原文保持原样比较）。"""
    return re.sub(r"\s+", "", text or "")


def score_quote(quote: str, block: str) -> float:
    """引文与单个正文块的匹配分 ∈ [0, 1]。

    exact/prefix（归一化包含）= 1.0；否则 difflib 滑窗模糊比最大值。
    引文或块为空 → 0.0。"""
    q = _normalize(quote)
    b = _normalize(block)
    if not q or not b:
        return 0.0
    if q in b:
        return 1.0
    n = len(q)
    step = max(1, n // 4)
    starts = list(range(0, max(len(b) - n, 0) + 1, step))
    if starts and starts[-1] != max(len(b) - n, 0):
        starts.append(max(len(b) - n, 0))  # 尾窗对齐（防止步长跳过结尾）
    matcher = SequenceMatcher(None, "", q)  # b2j 缓存在引文上（seq2）
    best = 0.0
    for start in starts:
        matcher.set_seq1(b[start : start + n])
        if matcher.real_quick_ratio() < best or matcher.quick_ratio() < best:
            continue
        ratio = matcher.ratio()
        if ratio > best:
            best = ratio
    return best


def _excerpt_of(block: str, quote: str) -> str:
    compact = re.sub(r"\s+", " ", block).strip()
    if quote and quote in compact:
        return quote[:_EXCERPT_MAX]
    return compact[:_EXCERPT_MAX]


def repair_candidates(
    quote: str, blocks: list[str], *, prefix: str = ""
) -> list[dict[str, object]]:
    """全部达标候选（score ≥ 0.8），按分数降序、blockIndex 升序排列，
    最多 MAX_CANDIDATES 条。每条 {blockIndex, score, excerpt}。"""
    nq = _normalize(quote)
    nprefix = _normalize(prefix)
    out: list[dict[str, object]] = []
    for index, block in enumerate(blocks):
        nb = _normalize(block)
        if nq and nq in nb or nq and nprefix and (nprefix + nq) in nb:
            score = 1.0
        else:
            score = score_quote(quote, block)
        if score >= FUZZY_THRESHOLD:
            out.append(
                {
                    "blockIndex": index,
                    "score": round(score, 4),
                    "excerpt": _excerpt_of(block, quote),
                }
            )
    out.sort(key=lambda c: (-float(c["score"]), int(c["blockIndex"])))  # type: ignore[arg-type]
    return out[:MAX_CANDIDATES]
