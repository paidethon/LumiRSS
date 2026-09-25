"""N078 批注批量迁移 —— 跨文章版本的批注锚点迁移（预览 + 逐项确认）。

N032 的正文变体（上游交付明显缩水 → 保留「上次完整版本」）与 N031
的修订会让块文本漂移，旧版本上做的批注锚点随之失效。这里把 N071
的单条修复扩展为按文章批量的预检：

- 版本词表：``current``（上游当前交付，FreshRSS 适配器实时取）与
  ``last_known_full``（N032 保留的上次完整版本，本地变体表）；
- 预览（零写入）：每条批注的存量引文对目标版本正文块重检（与 N071
  同一匹配口径：exact/prefix/fuzzy ≥0.8），产出候选块 + 分数；
- 应用（逐项确认）：选中项走与 N071 repair 完全相同的 rebind 机制
  （anchor + anchor_hash 更新，旧锚点进 annotation_repair_log ——
  撤销能力由该历史承载，不另建第二套日志）；
- 冲突不覆盖：修复后的锚点与另一条既有批注重复 → 该项 skip（reason
  = target_conflict），绝不改写他条；
- 跨用户拒绝：批注与变体都在 per-user 库，他人文章物理不可见——
  不存在的 entryRef/批注 → 422/404 诚实失败，绝不静默迁移。

分数是相似度证据，不是内容缓存：本模块不落任何派生文本。
"""

from dataclasses import dataclass
from typing import Any

from lumirss.adapters.freshrss import html_to_text
from lumirss.annotation_repair import repair_candidates, split_blocks

VERSIONS = ("current", "last_known_full")

# 候选门槛与 N071 同源（repair_candidates 内部 FUZZY_THRESHOLD=0.8）：
# 低于门槛的候选不进预览——诚实：找不到就说找不到。


class UnknownVersion(ValueError):
    """fromVersion/toVersion 不是支持的版本词。"""


@dataclass(frozen=True)
class VersionContent:
    """一个版本的正文块序列（split_blocks 口径：contentText 按行即块）。"""

    version: str
    blocks: list[str]


def validate_version(value: object) -> str:
    if value not in VERSIONS:
        raise UnknownVersion(f"version 必须是 {' 或 '.join(VERSIONS)}。")
    return str(value)


def blocks_from_variant_html(variant_html: str | None) -> list[str]:
    """N032 保留的 HTML 变体 → 正文块（与适配器 contentText 同一转换）。"""
    return split_blocks(html_to_text(variant_html or ""))


def preview_items(
    annotations: list[dict[str, Any]],
    target: VersionContent,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """对每条批注在目标版本中找最优候选（零写入，纯函数可单测）。

    返回 (matched, unmatched)：
    - matched: [{annotationId, candidateBlockIndex, score, excerpt}]，
      按批注传入顺序（稳定，UI 逐项确认）；
    - unmatched: [{annotationId, reason}]，reason ∈ no_quote（无引文
      可检索）| no_match（目标版本中没有 ≥0.8 的候选）。
    """
    matched: list[dict[str, Any]] = []
    unmatched: list[dict[str, str]] = []
    for annotation in annotations:
        anchor = annotation.get("anchor") if isinstance(annotation.get("anchor"), dict) else {}
        anchor = anchor or {}
        quote = str(annotation.get("excerpt") or anchor.get("exact") or "").strip()
        if quote == "":
            unmatched.append({"annotationId": str(annotation["id"]), "reason": "no_quote"})
            continue
        candidates = repair_candidates(quote, target.blocks, prefix=str(anchor.get("prefix") or ""))
        if not candidates:
            unmatched.append({"annotationId": str(annotation["id"]), "reason": "no_match"})
            continue
        best = candidates[0]
        matched.append(
            {
                "annotationId": str(annotation["id"]),
                "candidateBlockIndex": int(best["blockIndex"]),  # type: ignore[arg-type]
                "score": float(best["score"]),  # type: ignore[arg-type]
                "excerpt": str(best["excerpt"]),
            }
        )
    return matched, unmatched
