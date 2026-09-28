"""NEW-237 引用卡片组装 —— 从自己的几段引文组一张带来源索引的文字卡。

- 卡 = 有序引文集合（每条 = 摘录 + 可选批注 + 来源索引号 [n]）+
  文末来源索引（[n] 文章引用 + 段落锚 deep link + 标题/来源/日期，
  缺失项「不详」——与 N075 同一诚实口径，只用既有元数据）。
- 预览与导出同一构建函数：preview 返回 JSON（不落盘、不下载）；
  export 加 Content-Disposition。是否包含批注由 includeNotes 选择。
- 边界：只能引用自己的批注（per-user 库）；未知 id honest skipped；
  1..50 条；重复 id 去重（保首次序）。绝不改写引文文本。
"""

from typing import Any

from lumirss.util import utc_now

MAX_CARD_ITEMS = 50


class QuoteCardInvalid(ValueError):
    """卡片负载非法，映射 422。"""


def dedupe(ids: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in ids:
        value = str(raw)
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _md_escape(text: str) -> str:
    """Markdown 结构转义（与批注导出同口径：行首 #/>/- 与行内反引号）。"""
    cleaned = text.replace("`", "\\`").replace("\r", "")
    lines = []
    for line in cleaned.split("\n"):
        if line.startswith(("#", ">", "-", "1.")):
            line = "\\" + line
        lines.append(line)
    return "\n".join(lines)


async def _entry_meta(db: Any, entry_ref: str) -> dict[str, str | None]:
    row = await db.fetch_one(
        "SELECT title, feed_title, published_at FROM search_entries WHERE entry_ref = ?",
        (entry_ref,),
    )
    if row is None:
        return {"title": None, "source": None, "date": None}
    published = str(row["published_at"] or "").strip()
    date = (
        published[:10]
        if len(published) >= 10 and published[4] == "-" and published[7] == "-"
        else None
    )
    return {
        "title": str(row["title"] or ""),
        "source": str(row["feed_title"] or ""),
        "date": date,
    }


async def build_quote_card(
    db: Any,
    annotations: list[dict[str, Any]],
    *,
    include_notes: bool,
    title: str | None,
) -> dict[str, Any]:
    """组装文字卡。annotations = 按用户给定顺序解析出的本人批注。
    返回 {markdown, sources, quoteCount}（sources = 来源索引）。"""
    if not annotations:
        raise QuoteCardInvalid("卡片至少需要一条引文。")
    if len(annotations) > MAX_CARD_ITEMS:
        raise QuoteCardInvalid(f"一张卡最多 {MAX_CARD_ITEMS} 条引文。")

    source_refs: list[str] = []
    source_index: dict[str, int] = {}
    for item in annotations:
        ref = str(item["entryRef"])
        if ref not in source_index:
            source_index[ref] = len(source_refs) + 1
            source_refs.append(ref)

    card_title = (title or "").strip() or "引用卡片"
    lines: list[str] = [f"# {card_title}", "", f"组装于 {utc_now()}", ""]
    for item in annotations:
        index = source_index[str(item["entryRef"])]
        lines += [f"> {_md_escape(str(item['excerpt']) or '（无摘录）')} [{index}]", ""]
        if include_notes:
            note = str(item["note"] or "")
            if note:
                lines += [f"我的批注：{_md_escape(note)}", ""]
    lines += ["---", "", "来源索引", ""]
    sources: list[dict[str, Any]] = []
    unknown = "不详"
    for ref in source_refs:
        number = source_index[ref]
        meta = await _entry_meta(db, ref)
        anchor = next(
            (i["anchor"] for i in annotations if str(i["entryRef"]) == ref),
            {},
        )
        para = ""
        if isinstance(anchor, dict):
            para = str(anchor.get("paraId") or "")
        deep_link = f"/reader?entry={ref}" + (f"&para={para}" if para else "")
        title_text = (meta["title"] or "").strip() or unknown
        source_text = (meta["source"] or "").strip() or unknown
        date_text = (meta["date"] or "").strip() or unknown
        sources.append(
            {
                "index": number,
                "entryRef": ref,
                "title": title_text,
                "source": source_text,
                "date": date_text,
                "backHref": deep_link,
            }
        )
        lines += [
            f"[{number}] {title_text} — {source_text}, {date_text}",
            f"  打开原文：{deep_link}",
            "",
        ]
    return {
        "title": card_title,
        "markdown": "\n".join(lines),
        "sources": sources,
        "quoteCount": len(annotations),
    }
