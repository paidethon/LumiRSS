"""NEW-362 相似标题候选审阅 —— 基于可解释的文字相似度列出候选重复稿。

语义（诚实边界）：
- 相似度完全可解释：标题规范化（NFKC + casefold + 去标点/空白）后切
  字符二元组（与 web 端 N148 同一算法口径），Jaccard 相似度 + 共有
  二元组计数 + 共有片段样例随候选一起返回——绝无黑盒分数；
- 只列候选，绝不自动加入任何组：只有用户对具体一对显式 confirm 后
  才写入 item_relations（duplicate = 重复组；reprint = 转载关系，
  kind='manual' + 「转载」前缀备注，与既有关系类型 honest 映射）；
- 候选扫描有界：本人投影最近 500 行内两两比较，触界如实标注
  scannedCapped。

per-user：search_entries / item_relations 都在 per-user 库，A 的候选
与确认动作对 B 不可见。
"""

import re
import unicodedata
from typing import Any

from lumirss.storage import Database

_CANDIDATE_SCAN_ROWS = 500
_RELATED_SCAN_LIMIT = 200
_CANDIDATE_MIN_SCORE = 60  # Jaccard≥0.60 才算「候选重复稿」供审阅


def title_tokens(title: str) -> set[str]:
    """规范化标题的字符二元组集合（与 web lib/similar-titles 同口径）。"""
    normalized = unicodedata.normalize("NFKC", title).casefold()
    # 去空白/标点/符号；保留字母数字与 CJK（\w 的 Unicode 语义）。
    normalized = re.sub(r"[\s\W_]+", "", normalized, flags=re.UNICODE)
    tokens: set[str] = set()
    if len(normalized) < 2:
        if normalized:
            tokens.add(normalized)
        return tokens
    for i in range(len(normalized) - 1):
        tokens.add(normalized[i : i + 2])
    return tokens


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    intersection = len(a & b)
    union = len(a | b)
    return intersection / union


def shared_sample(a: set[str], b: set[str], limit: int = 4) -> str:
    """共有二元组样例（解释用；按交集原序取前 limit 个拼接）。"""
    ordered = [token for token in sorted(a & b)]
    return "".join(ordered[:limit])


def explain_similarity(a_title: str, b_title: str) -> dict[str, Any] | None:
    """可解释相似度：score(0-100) + 共有二元组数 + 片段样例。

    低于候选阈值 → None（不是候选）。"""
    tokens_a = title_tokens(a_title)
    tokens_b = title_tokens(b_title)
    score = int(round(_jaccard(tokens_a, tokens_b) * 100))
    if score < _CANDIDATE_MIN_SCORE:
        return None
    shared = tokens_a & tokens_b
    return {
        "score": score,
        "sharedBigrams": len(shared),
        "sharedSample": shared_sample(tokens_a, tokens_b),
        "totalBigrams": {"a": len(tokens_a), "b": len(tokens_b)},
    }


async def scan_candidates(
    db: Database,
    *,
    entry_ref: str,
    limit: int = 8,
) -> dict[str, Any] | None:
    """本人投影内为本篇找候选重复稿（有界：最近 500 行）。

    entryRef 不在本账户投影 → None（调用方映射 404，不泄露他人条目
    存在性）。候选含关系现状（已在重复/转载组中的如实标注）。"""
    await db.migrate()
    anchor = await db.fetch_one(
        "SELECT entry_ref, title, feed_url, feed_title, published_at"
        " FROM search_entries WHERE entry_ref = ?",
        (entry_ref,),
    )
    if anchor is None:
        return None
    rows = await db.fetch_all(
        "SELECT entry_ref, title, feed_url, feed_title, published_at"
        " FROM search_entries WHERE entry_ref != ?"
        " ORDER BY published_at DESC, item_id DESC LIMIT ?",
        (entry_ref, _CANDIDATE_SCAN_ROWS + 1),
    )
    scanned_capped = len(rows) > _CANDIDATE_SCAN_ROWS
    rows = rows[:_CANDIDATE_SCAN_ROWS]
    anchor_tokens = title_tokens(str(anchor["title"]))
    relations = await db.fetch_all(
        "SELECT src_ref, dst_ref, kind, note FROM item_relations"
        " WHERE src_ref = ? OR dst_ref = ? ORDER BY id ASC LIMIT ?",
        (relation_ref(entry_ref), relation_ref(entry_ref), _RELATED_SCAN_LIMIT),
    )
    related: dict[str, dict[str, str]] = {}
    for relation in relations:
        other = (
            str(relation["dst_ref"])
            if str(relation["src_ref"]) == relation_ref(entry_ref)
            else str(relation["src_ref"])
        )
        related[projection_ref(other)] = {
            "kind": str(relation["kind"] or "manual"),
            "note": str(relation["note"] or ""),
        }
    candidates: list[dict[str, Any]] = []
    for row in rows:
        explanation = explain_similarity_tokens(
            anchor_tokens, str(row["title"])
        )
        if explanation is None:
            continue
        relation = related.get(str(row["entry_ref"]))
        candidates.append(
            {
                "entryRef": str(row["entry_ref"]),
                "title": str(row["title"]),
                "feedTitle": str(row["feed_title"]),
                "feedUrl": str(row["feed_url"]),
                "publishedAt": str(row["published_at"]),
                "sameSource": str(row["feed_url"]) == str(anchor["feed_url"]),
                "inGroup": relation["kind"] if relation else None,
                "inGroupNote": relation["note"] if relation else None,
                **explanation,
            }
        )
    candidates.sort(key=lambda item: (-item["score"], item["entryRef"]))
    return {
        "entry": {
            "entryRef": entry_ref,
            "title": str(anchor["title"]),
            "feedTitle": str(anchor["feed_title"]),
            "publishedAt": str(anchor["published_at"]),
        },
        "candidates": candidates[: max(1, min(int(limit), 20))],
        "scanned": len(rows),
        "scannedCapped": scanned_capped,
    }


def explain_similarity_tokens(
    anchor_tokens: set[str], other_title: str
) -> dict[str, Any] | None:
    """以预切好的锚点 token 计算相似度（避免循环内重复规范化）。"""
    tokens_b = title_tokens(other_title)
    score = int(round(_jaccard(anchor_tokens, tokens_b) * 100))
    if score < _CANDIDATE_MIN_SCORE:
        return None
    shared = anchor_tokens & tokens_b
    return {
        "score": score,
        "sharedBigrams": len(shared),
        "sharedSample": shared_sample(anchor_tokens, tokens_b),
        "totalBigrams": {"a": len(anchor_tokens), "b": len(tokens_b)},
    }


REPRINT_NOTE_PREFIX = "转载："
DUPLICATE_NOTE_PREFIX = "疑似重复（相似标题确认）："
_MAX_NOTE = 200


def relation_ref(entry_ref: str) -> str:
    """投影 ref（``e1.``）→ item_relations 的 ItemRef（``rss:e1.``）。"""
    return entry_ref if entry_ref.startswith("rss:") else f"rss:{entry_ref}"


def projection_ref(item_ref: str) -> str:
    """item_relations 的 ItemRef → 投影 ref（去掉 ``rss:`` 前缀）。"""
    return item_ref.removeprefix("rss:")


async def confirm_candidate(
    db: Database,
    *,
    a_ref: str,
    b_ref: str,
    relation: str,
    note: str | None = None,
) -> dict[str, Any]:
    """用户显式确认后写入 item_relations（唯一写路径）。

    relation='duplicate' → kind='duplicate'；relation='reprint' →
    kind='manual' + 「转载：」前缀备注（item_relations 无第三种 kind，
    honest 映射而非伪造）。两侧 ref 都必须在本账户投影内可解析。"""
    from lumirss.item_relations import ItemRelationStore

    clean_note = (note or "").strip()
    if len(clean_note) > _MAX_NOTE:
        clean_note = clean_note[:_MAX_NOTE]
    if relation == "duplicate":
        prefix = DUPLICATE_NOTE_PREFIX
        kind = "duplicate"
    elif relation == "reprint":
        prefix = REPRINT_NOTE_PREFIX
        kind = "manual"
    else:
        raise ValueError("relation 只支持 duplicate 或 reprint。")
    # 双侧 own-scope 校验：任一侧不在投影 → ValueError（调用方 404）。
    for ref in (a_ref, b_ref):
        row = await db.fetch_one(
            "SELECT 1 FROM search_entries WHERE entry_ref = ?", (ref,)
        )
        if row is None:
            raise KeyError(ref)
    store = ItemRelationStore(db)
    full_note = prefix + (clean_note or "用户确认")
    row = await store.create(
        relation_ref(a_ref), relation_ref(b_ref), full_note, kind=kind
    )
    # store.create 返回 camelCase 视图（_row_to_dict）。
    return {
        "relation": {
            "id": row["id"],
            "srcRef": projection_ref(str(row["srcRef"])),
            "dstRef": projection_ref(str(row["dstRef"])),
            "kind": row["kind"],
            "note": row["note"],
            "createdAt": row["createdAt"],
        },
        "explained": "关联仅在本次显式确认后创建；相似度从未自动入组。",
    }
