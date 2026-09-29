"""NEW-268 译文引用导出 —— 人工确认译文的导出台账。

导出某一段的译文时同时附 原文 / 来源 / 机器或人工标记：

- 译文取段缓存行：有人工修订（F062）→ 人工文本 + human_revised=1；
  否则机器文本 + human_revised=0。任何路径都不改写缓存；
- 来源取 search_entries 本地投影的 feed_url/feed_title（尽力而为，
  无投影行 → 空串，不臆造）；
- 用户必须显式 confirmed=true 才可导出 —— 机器未确认的译文不给
  「确认译文」的引用形态；无成功缓存行 → 诚实 422（不导出空引用）；
- format：markdown（引用块 + 出处行）或 text（纯文本行）；
- 每篇上限 QUOTE_EXPORT_CAP 条（超出淘汰最旧）。

全部 SQL 为内联字面量 + 绑定参数。
"""

import uuid
from typing import Any

from lumirss.ai_settings import (
    KEY_TRANSLATION_ENGINE,
    KEY_TRANSLATION_LANGUAGE,
)
from lumirss.ai_translation_segments import (
    SEGMENTS_PROMPT_VERSION,
    block_hash,
    engine_identity,
    normalize_block_text,
)
from lumirss.glossary import get_glossary_version
from lumirss.util import utc_now

QUOTE_EXPORT_CAP = 50

_FETCH_ROW_SQL = """SELECT * FROM ai_translation_segments
WHERE entry_ref = ? AND block_index = ? AND block_hash = ?
AND provider = ? AND model = ? AND prompt_version = ?
AND target_language = ? AND glossary_version = ?
ORDER BY updated_at DESC, id DESC LIMIT 1"""

_PROVENANCE_SQL = """SELECT feed_url, feed_title FROM search_entries
WHERE entry_ref = ? LIMIT 1"""

_INSERT_SQL = """INSERT INTO translation_quote_exports
(id, entry_ref, block_index, source_text, translated_text, human_revised,
 source_url, feed_title, format, created_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""

_LIST_SQL = """SELECT * FROM translation_quote_exports
WHERE entry_ref = ? ORDER BY created_at DESC, id DESC LIMIT ?"""

_PRUNE_SQL = """DELETE FROM translation_quote_exports WHERE entry_ref = ?
AND id NOT IN (
SELECT id FROM translation_quote_exports WHERE entry_ref = ?
ORDER BY created_at DESC, id DESC LIMIT ?)"""


class QuoteNotConfirmed(Exception):
    """未显式确认 → 422（不给「确认译文」的引用形态）。"""


class QuoteUnavailable(Exception):
    """该段没有成功缓存译文 → 422（诚实拒绝，不导出空引用）。"""


async def export_quote(
    db: Any,
    service: Any,
    entry_ref: str,
    block_index: int,
    block_text: str,
    fmt: str = "markdown",
    confirmed: bool = False,
) -> dict[str, Any]:
    """显式导出一段译文（附原文/来源/机器人工标记）并留档。"""
    await db.migrate()
    if not confirmed:
        raise QuoteNotConfirmed("请先确认该译文，再导出引用。")
    if fmt not in ("markdown", "text"):
        raise QuoteUnavailable("format 必须是 markdown 或 text。")
    normalized = normalize_block_text(block_text)
    if not normalized:
        raise QuoteUnavailable("该段没有可导出的原文文本。")
    settings = await service._resolve_settings()
    provider, model = engine_identity(settings[KEY_TRANSLATION_ENGINE], settings)
    row = await db.fetch_one(
        _FETCH_ROW_SQL,
        (
            entry_ref,
            block_index,
            block_hash(normalized),
            provider,
            model,
            SEGMENTS_PROMPT_VERSION,
            settings[KEY_TRANSLATION_LANGUAGE],
            await get_glossary_version(db),
        ),
    )
    if row is None or row["status"] != "success" or not row["translated_text"]:
        raise QuoteUnavailable(
            f"Segment {block_index} has no successful cached translation."
        )
    revised = bool(row["user_revision"])
    translated = str(row["user_revision"] or row["translated_text"])
    source_text = str(row["source_text"] or normalized)
    provenance = await db.fetch_one(_PROVENANCE_SQL, (entry_ref,))
    source_url = str(provenance["feed_url"]) if provenance is not None else ""
    feed_title = (
        str(provenance["feed_title"] or "") if provenance is not None else ""
    )
    attribution = feed_title or source_url or "未知来源"
    marker = "人工修订" if revised else "机器翻译"
    if fmt == "markdown":
        rendered = (
            "> " + translated.replace("\n", "\n> ")
            + "\n>\n> —— 原文：" + source_text
            + "\n> 来源：" + attribution
            + "（" + marker + "）"
        )
    else:
        rendered = (
            translated
            + "\n\n原文: " + source_text
            + "\n来源: " + attribution
            + "\n标记: " + marker
        )
    now = utc_now()
    export_id = f"tqe-{uuid.uuid4().hex[:16]}"
    await db.execute(
        _INSERT_SQL,
        (
            export_id,
            entry_ref,
            block_index,
            source_text,
            translated,
            1 if revised else 0,
            source_url,
            feed_title,
            fmt,
            now,
        ),
    )
    await db.execute(_PRUNE_SQL, (entry_ref, entry_ref, QUOTE_EXPORT_CAP))
    return {
        "id": export_id,
        "entryRef": entry_ref,
        "blockIndex": block_index,
        "sourceText": source_text,
        "translatedText": translated,
        "humanRevised": revised,
        "sourceUrl": source_url,
        "feedTitle": feed_title,
        "format": fmt,
        "rendered": rendered,
        "createdAt": now,
    }


def _view(row: Any) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "entryRef": str(row["entry_ref"]),
        "blockIndex": int(row["block_index"]),
        "sourceText": str(row["source_text"] or ""),
        "translatedText": str(row["translated_text"] or ""),
        "humanRevised": bool(row["human_revised"]),
        "sourceUrl": str(row["source_url"] or ""),
        "feedTitle": str(row["feed_title"] or ""),
        "format": str(row["format"]),
        "createdAt": str(row["created_at"] or ""),
    }


async def list_exports(db: Any, entry_ref: str, limit: int = 20) -> list[dict[str, Any]]:
    """某篇的导出台账（新→旧）。"""
    await db.migrate()
    rows = await db.fetch_all(
        _LIST_SQL, (entry_ref, max(1, min(limit, QUOTE_EXPORT_CAP)))
    )
    return [_view(row) for row in rows]
