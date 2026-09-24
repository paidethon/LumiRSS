"""F080 Obsidian 反链/断链 — 反向索引与解析扩展。

- 解析：[[target|alias#heading]] → target/alias/heading；别名与标题
  锚点保留；路径穿越（../、绝对路径逃逸 vault）→ broken
  reason=path_escaped_vault（拒绝解析）；
- 反向索引：投影 rescan 后重建（DELETE 全量 + INSERT；数据源为
  obsidian_notes 的 wikilinks 索引，解析目标 = 其余笔记的
  rel_path/标题）；
- 查询：backlinks（谁链接到我）与 broken-links（未解析出站）。

N134 块级回跳：rebuild_block_refs 从投影正文提取 ``^lumi-<paraId>``
块 id（导出批注的内嵌回跳锚点）→ obsidian_block_refs；block_refs_for
反查「哪些笔记引用了这个段落」。数据纯派生，rescan 时全量重建。

写站点 2 处（rebuild 的 DELETE + 批量 INSERT 走 execute_many）。
"""

import json as _json
import re as _re
from dataclasses import dataclass
from typing import Any

from lumirss.util import utc_now as _utc_now

_CLEAR_SQL = "DELETE FROM obsidian_backlinks"

# N134：与 obsidian_handoff.BLOCK_ID_RE 同一形状（避免循环导入在此
# 本地编译；测试断言两侧行为一致）。
_LUMI_BLOCK_ID_RE = _re.compile(r"\^lumi-([A-Za-z0-9_-]+)")


@dataclass(frozen=True)
class ParsedWikilink:
    raw: str
    target: str
    alias: str | None
    heading: str | None
    escaped_vault: bool


def parse_wikilink(raw: str) -> ParsedWikilink:
    """[[path|alias#heading]] 解析（顺序：先别名后锚点，与 Obsidian 一致
    为 [[target|alias]] 与 [[target#heading]] 两种习惯均支持）。"""
    body = raw.strip()
    alias = None
    heading = None
    target = body
    if "|" in body:
        target, alias = body.split("|", 1)
        alias = alias.strip() or None
        if "#" in target:
            target, heading = target.split("#", 1)
    elif "#" in body:
        target, heading = body.split("#", 1)
    target = target.strip()
    heading = (heading or None) if heading is None else heading.strip() or None
    alias = alias if alias is None else alias.strip() or None
    escaped = (
        ".." in target
        or target.startswith("/")
        or target.startswith("\\")
        or (len(target) >= 2 and target[1] == ":")
    )
    return ParsedWikilink(raw=body, target=target, alias=alias, heading=heading, escaped_vault=escaped)


def _normalize_key(rel_path: str) -> str:
    return rel_path.strip().lower().removesuffix(".md")


async def rebuild_backlinks(db: Any) -> int:
    """按 obsidian_notes 的 wikilinks 索引重建反向链接表。

    解析目标：其余笔记的 rel_path（忽略 .md/大小写）或标题。穿越/未
    解析 → broken 行。返回重建后的总行数。"""
    await db.migrate()
    notes = await db.fetch_all(
        "SELECT item_uuid, rel_path, title, wikilinks, wikilink_raws FROM obsidian_notes LIMIT 5000"
    )
    by_key: dict[str, str] = {}
    titles: dict[str, str] = {}
    for note in notes:
        uuid_ = str(note["item_uuid"])
        rel_path = str(note["rel_path"])
        by_key[_normalize_key(rel_path)] = uuid_
        # basename（无目录前缀、无 .md）也可解析——Obsidian 同名短链习惯
        stem = _normalize_key(rel_path).rsplit("/", 1)[-1]
        by_key.setdefault(stem, uuid_)
        title = str(note["title"] or "").strip()
        if title:
            titles[title] = uuid_
    pairs: list[tuple] = []
    for note in notes:
        from_uuid = str(note["item_uuid"])
        try:
            raws = _json.loads(str(note["wikilink_raws"] or "[]"))
            raw_links = raws if isinstance(raws, list) and raws else _json.loads(
                str(note["wikilinks"] or "[]")
            )
        except _json.JSONDecodeError:
            raw_links = []
        for raw in raw_links if isinstance(raw_links, list) else []:
            parsed = parse_wikilink(str(raw))
            if parsed.escaped_vault:
                pairs.append((from_uuid, None, parsed.target.lower(), parsed.raw, parsed.alias, parsed.heading, 1, "path_escaped_vault"))
                continue
            target_uuid = by_key.get(_normalize_key(parsed.target)) or titles.get(parsed.target)
            if target_uuid is None:
                pairs.append((from_uuid, None, parsed.target.lower(), parsed.raw, parsed.alias, parsed.heading, 1, "unresolved"))
                continue
            pairs.append((from_uuid, target_uuid, parsed.target.lower(), parsed.raw, parsed.alias, parsed.heading, 0, None))
    await db.execute(_CLEAR_SQL)
    if pairs:
        await db.execute_many(
            "INSERT OR IGNORE INTO obsidian_backlinks (from_uuid, target_uuid, resolved_key, raw, alias, heading, broken, reason) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            pairs,
        )
    return len(pairs)


async def backlinks_for(db: Any, note_uuid: str) -> list[dict[str, Any]]:
    await db.migrate()
    rows = await db.fetch_all(
        """SELECT ob.from_uuid, ob.alias, n.title, n.rel_path
        FROM obsidian_backlinks ob
        LEFT JOIN obsidian_notes n ON n.item_uuid = ob.from_uuid
        WHERE ob.target_uuid = ? AND ob.broken = 0
        ORDER BY ob.from_uuid ASC LIMIT 500""",
        (note_uuid,),
    )
    return [
        {
            "fromUuid": str(row["from_uuid"]),
            "title": row["title"] or row["rel_path"] or str(row["from_uuid"]),
            "alias": row["alias"],
        }
        for row in rows
    ]


async def broken_links_for(db: Any, note_uuid: str) -> list[dict[str, Any]]:
    await db.migrate()
    rows = await db.fetch_all(
        """SELECT raw, reason FROM obsidian_backlinks
        WHERE from_uuid = ? AND broken = 1 ORDER BY raw ASC LIMIT 500""",
        (note_uuid,),
    )
    return [{"raw": str(row["raw"]), "reason": str(row["reason"] or "unresolved")} for row in rows]


# ---------------------------------------------------------------------------
# N134 块级回跳：^lumi- 块 id 索引（纯派生，rescan 时全量重建）。
# ---------------------------------------------------------------------------

_CLEAR_BLOCK_REFS_SQL = "DELETE FROM obsidian_block_refs"


async def rebuild_block_refs(db: Any) -> int:
    """从投影正文提取 ``^lumi-<paraId>`` → obsidian_block_refs 全量重建。

    返回重建后的行数（不是笔记数：一篇笔记可含多个块 id）。失败由
    调用方（rescan）尽力而为地吞掉，不影响扫描结果。"""
    await db.migrate()
    notes = await db.fetch_all(
        "SELECT item_uuid, body_text FROM obsidian_notes LIMIT 5000"
    )
    now = _utc_now()
    pairs: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for note in notes:
        note_uuid = str(note["item_uuid"])
        for match in _LUMI_BLOCK_ID_RE.finditer(str(note["body_text"] or "")):
            para_id = match.group(1)
            key = (para_id, note_uuid)
            if key in seen:
                continue
            seen.add(key)
            pairs.append((para_id, note_uuid, now))
    await db.execute(_CLEAR_BLOCK_REFS_SQL)
    if pairs:
        await db.execute_many(
            "INSERT OR IGNORE INTO obsidian_block_refs (para_id, note_uuid, indexed_at) VALUES (?, ?, ?)",
            pairs,
        )
    return len(pairs)


async def block_refs_for(db: Any, para_id: str) -> list[dict[str, Any]]:
    """反查：哪些投影笔记内嵌了 ``^lumi-<para_id>`` 块 id（round-trip）。

    ``para_id`` 可带或不带 ``lumi-`` 前缀（UI 从 anchor.paraId 直接来，
    手工查询常带前缀——两种形状都接受）。"""
    await db.migrate()
    clean = str(para_id or "").strip().lstrip("^")
    if clean.startswith("lumi-"):
        clean = clean[len("lumi-") :]
    if not clean:
        return []
    rows = await db.fetch_all(
        """SELECT obr.para_id, n.item_uuid, n.title, n.rel_path, obr.indexed_at
        FROM obsidian_block_refs obr
        JOIN obsidian_notes n ON n.item_uuid = obr.note_uuid
        WHERE obr.para_id = ?
        ORDER BY n.rel_path ASC LIMIT 200""",
        (clean,),
    )
    return [
        {
            "paraId": str(row["para_id"]),
            "noteUuid": str(row["item_uuid"]),
            "title": str(row["title"] or ""),
            "relPath": str(row["rel_path"] or ""),
            "indexedAt": str(row["indexed_at"] or ""),
        }
        for row in rows
    ]
