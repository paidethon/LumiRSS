"""NEW-368 相近拼写搜索提示 —— 零命中时的可选拼写候选。

语义（负向契约同样新）：
- 只有当同一过滤链的真实命中为 0 时才给候选（hasHits=true 时候选必
  为空表——绝不干扰有结果的搜索）；
- 词表来自本人投影的标题词条（最近 400 行，有界），候选 = 编辑距离
  ≤(1 或 2) 的最近词，按距离升序 + 出现次数降序，每词条 ≤3 个；
- 只建议、不自动替换：候选随响应返回，替换永远是用户显式点击；
- 纯算法（受限 Damerau-Levenshtein），无模型调用、无网络。

per-user：词表来自 per-user 投影，A 的候选词表对 B 不可见。
"""

from typing import Any

from lumirss.search_index import split_terms

_VOCAB_ROWS = 400
_VOCAB_CAP = 2000
_MAX_SUGGESTIONS_PER_TERM = 3
_MIN_TOKEN = 2
_MAX_TOKEN = 24


def edit_distance_within(a: str, b: str, max_distance: int) -> int | None:
    """受限 Damerau-Levenshtein 距离；超过 max_distance 提前剪枝。

    返回实际距离（≤max_distance）或 None。带转置（相邻交换）——
    「teh→the」类拼写滑移与中文近形词都按一次编辑计。"""
    la, lb = len(a), len(b)
    if abs(la - lb) > max_distance:
        return None
    previous_two: list[int] | None = None
    previous = list(range(lb + 1))
    for i in range(1, la + 1):
        current = [i] + [0] * lb
        row_min = current[0]
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            current[j] = min(
                previous[j] + 1,  # 删除
                current[j - 1] + 1,  # 插入
                previous[j - 1] + cost,  # 替换
            )
            if (
                previous_two is not None
                and i > 1
                and j > 1
                and a[i - 1] == b[j - 2]
                and a[i - 2] == b[j - 1]
            ):
                current[j] = min(current[j], previous_two[j - 2] + 1)  # 转置
            row_min = min(row_min, current[j])
        if row_min > max_distance:
            return None  # 整行剪枝：后续不可能回到阈值内
        previous_two = previous
        previous = current
    distance = previous[lb]
    return distance if distance <= max_distance else None


def build_vocabulary(rows: list[Any]) -> dict[str, int]:
    """标题词条 → 出现次数（有界：token 长度 2..24）。"""
    vocab: dict[str, int] = {}
    for row in rows:
        title = str(row["title"] or "")
        for token in title.split():
            clean = token.strip(".,;:!?'\"()[]{}<>—–|/\\").casefold()
            if _MIN_TOKEN <= len(clean) <= _MAX_TOKEN:
                vocab[clean] = vocab.get(clean, 0) + 1
        if len(vocab) >= _VOCAB_CAP:
            break
    return dict(list(vocab.items())[:_VOCAB_CAP])


def suggestions_for_terms(
    vocab: dict[str, int], terms: list[str]
) -> list[dict[str, Any]]:
    """每个查询词条给 ≤3 个可选拼写候选（0 命中前提由调用方保证）。"""
    results: list[dict[str, Any]] = []
    for term in terms[:4]:
        folded = term.casefold()
        if folded in vocab:
            continue  # 词条本身在词表里 → 无需拼写候选
        max_distance = 1 if len(folded) <= 3 else 2
        scored: list[tuple[int, int, str]] = []
        for word, count in vocab.items():
            if word == folded:
                continue
            distance = edit_distance_within(folded, word, max_distance)
            if distance is not None:
                scored.append((distance, -count, word))
        scored.sort()
        suggestions = [
            {
                "term": term,
                "suggestion": word,
                "distance": distance,
                "occurrences": -negative_count,
            }
            for distance, negative_count, word in scored[
                :_MAX_SUGGESTIONS_PER_TERM
            ]
        ]
        results.extend(suggestions)
    return results


async def spell_suggestions(
    store: Any,
    *,
    query: str,
    feed_url: str | None = None,
    category_id: str | None = None,
    unread_only: bool = False,
    starred_only: bool = False,
) -> dict[str, Any]:
    """零命中 → 拼写候选；有命中 → 候选恒为空（hasHits=true）。"""
    await store.ensure_migrated()
    terms = split_terms(query)
    total = await store.distribution_total(
        terms=terms,
        feed_url=feed_url,
        category_id=category_id,
        unread_only=unread_only,
        starred_only=starred_only,
    )
    if total > 0:
        return {
            "hasHits": True,
            "total": total,
            "candidates": [],
            "note": "查询已有真实命中；拼写提示只在零命中时出现。",
        }
    rows = await store.recent_titles(limit=_VOCAB_ROWS)
    vocab = build_vocabulary(rows)
    candidates = suggestions_for_terms(vocab, terms)
    return {
        "hasHits": False,
        "total": 0,
        "candidates": candidates,
        "vocabSize": len(vocab),
        "note": "候选来自本人索引标题词表（编辑距离 ≤2）；仅供参考，绝不自动替换查询。",
    }
