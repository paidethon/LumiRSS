"""NEW-233 标注汇总阅读页 —— 按文章结构汇总本人标注与必要上下文。

- 汇总口径：单篇内按锚点位置（paraId 的块序号）排序——即「按文章
  结构」阅读自己的标注；跨篇时按最近更新排文章，每篇内同样按位置。
- 必要上下文 = 摘录（引文）+ 批注 + 颜色 + 段落锚点 deep link
  （/reader?entry=…&para=…，点击即回原段）。**绝不携带正文**——
  不生成第二份不可追溯正文，回原文只靠 entryRef+paraId。
- 元数据（标题/来源）来自 search_entries 投影（本就随同步维护的
  可重建投影；离线可用，不触上游）；缺失诚实留空。
- 有界：文章数硬上限 100（超出 truncated=true 诚实标注）。

per-user 库——汇总是且只是本人的标注。
"""

import re
from typing import Any

from lumirss.storage import Database

MAX_SUMMARY_ENTRIES = 100

_PARA_NUMBER = re.compile(r"^(?:block|para|p)-(\d+)$")


def position_key(anchor: dict[str, Any], annotation_id: str) -> tuple[int, str]:
    """锚点位置排序键：paraId 形如 block-N/para-N/p-N → (N, id)；
    无法解析的锚点排到最后（诚实靠后，不假装有位置）。"""
    para_id = ""
    if isinstance(anchor, dict):
        para_id = str(anchor.get("paraId") or "")
    match = _PARA_NUMBER.match(para_id.strip())
    if match is None:
        return (10**9, annotation_id)
    return (int(match.group(1)), annotation_id)


def annotation_summary_item(item: dict[str, Any]) -> dict[str, Any]:
    """单条标注的汇总视图（必要上下文 + 回原文定位）。"""
    anchor = item["anchor"] if isinstance(item["anchor"], dict) else {}
    para_id = str(anchor.get("paraId") or "")
    stale = bool(anchor.get("stale"))
    deep_link = f"/reader?entry={item['entryRef']}" + (f"&para={para_id}" if para_id else "")
    return {
        "id": item["id"],
        "excerpt": item["excerpt"],
        "note": item["note"],
        "color": item["color"],
        "paraId": para_id,
        "stale": stale,
        "backHref": deep_link,
        "createdAt": item["createdAt"],
        "updatedAt": item["updatedAt"],
    }


async def entry_meta(db: Database, entry_ref: str) -> dict[str, str]:
    """标题/来源（search_entries 投影；缺失 → 空字符串，诚实留白）。"""
    row = await db.fetch_one(
        "SELECT title, feed_title FROM search_entries WHERE entry_ref = ?",
        (entry_ref,),
    )
    if row is None:
        return {"title": "", "source": ""}
    return {
        "title": str(row["title"] or ""),
        "source": str(row["feed_title"] or ""),
    }


async def build_summary(
    db: Database,
    annotations: list[dict[str, Any]],
) -> dict[str, Any]:
    """把本人标注列表组建成按文章结构的汇总（纯组装 + 投影元数据）。"""
    by_entry: dict[str, list[dict[str, Any]]] = {}
    for item in annotations:
        by_entry.setdefault(str(item["entryRef"]), []).append(item)

    entries: list[dict[str, Any]] = []
    truncated = False
    # 文章按「该篇最近更新的标注」新→旧排（阅读页的合理入口序），
    # 单篇内按锚点位置排（文章结构序）。
    ordered_refs = sorted(
        by_entry,
        key=lambda ref: max(str(i["updatedAt"]) for i in by_entry[ref]),
        reverse=True,
    )
    for index, entry_ref in enumerate(ordered_refs):
        if index >= MAX_SUMMARY_ENTRIES:
            truncated = True
            break
        items = sorted(
            by_entry[entry_ref],
            key=lambda i: position_key(i["anchor"], str(i["id"])),
        )
        meta = await entry_meta(db, entry_ref)
        entries.append(
            {
                "entryRef": entry_ref,
                "title": meta["title"],
                "source": meta["source"],
                "annotationCount": len(items),
                "annotations": [annotation_summary_item(i) for i in items],
            }
        )
    return {
        "entries": entries,
        "entryCount": len(entries),
        "totalAnnotations": len(annotations),
        "truncated": truncated,
    }
