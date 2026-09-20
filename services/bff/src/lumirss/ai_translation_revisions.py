"""F062 译文手工修订 — per (entry_ref, block_index) 的用户修订存储。

修订写入 ai_translation_segments 该段的全部缓存变体行（不同源文 hash /
引擎 / 模型 / 语言各成一行的缓存身份共享同一修订）：

- save：user_revision = 用户文本、revised_at = now、source_hash =
  保存时当前行的 block_hash（修订锚定的源段）；
- stale 判定在读取侧：revision.source_hash != 当前源段 block_hash →
  源文已更新（修订保留、只标记，不误删）；
- clear：撤销修订（全部变体一起清）。

全部 SQL 为内联字面量 + 绑定参数；写站点共 2 处（save/clear 各一）。
"""

from dataclasses import dataclass
from typing import Any

from lumirss.util import utc_now

MAX_REVISION_CHARS = 10000

_SAVE_SQL = """UPDATE ai_translation_segments
SET user_revision = ?, revised_at = ?, source_hash = block_hash, updated_at = ?
WHERE entry_ref = ? AND block_index = ?"""

_CLEAR_SQL = """UPDATE ai_translation_segments
SET user_revision = NULL, revised_at = NULL, source_hash = NULL, updated_at = ?
WHERE entry_ref = ? AND block_index = ?"""


@dataclass(frozen=True)
class SegmentRevision:
    """一条已保存的修订（按 block_index 关联任一变体行）。"""

    index: int
    text: str
    revised_at: str
    source_hash: str


class SegmentRevisionNotFound(Exception):
    """该段没有任何缓存行/修订（映射 404）。"""


async def revision_map(db: Any, entry_ref: str) -> dict[int, SegmentRevision]:
    """entry 的全部修订（index → 修订；取 revised_at 最新的一行）。"""
    await db.migrate()
    rows = await db.fetch_all(
        """SELECT block_index, user_revision, revised_at, source_hash
        FROM ai_translation_segments
        WHERE entry_ref = ? AND user_revision IS NOT NULL
        ORDER BY revised_at ASC""",
        (entry_ref,),
    )
    result: dict[int, SegmentRevision] = {}
    for row in rows:
        result[int(row["block_index"])] = SegmentRevision(
            index=int(row["block_index"]),
            text=str(row["user_revision"]),
            revised_at=str(row["revised_at"] or ""),
            source_hash=str(row["source_hash"] or ""),
        )
    return result


async def save_revision(
    db: Any, entry_ref: str, block_index: int, text: str
) -> SegmentRevision:
    """保存/替换修订；该段没有任何缓存行 → SegmentRevisionNotFound。

    source_hash 取该段当前变体行的 block_hash（同段各变体共享同一源
    文本 hash；修订锚定源段而非缓存变体）。"""
    await db.migrate()
    row = await db.fetch_one(
        """SELECT block_hash FROM ai_translation_segments
        WHERE entry_ref = ? AND block_index = ?
        ORDER BY updated_at DESC, id DESC LIMIT 1""",
        (entry_ref, block_index),
    )
    if row is None:
        raise SegmentRevisionNotFound(
            f"No cached translation segment {block_index} for this entry."
        )
    now = utc_now()
    await db.execute(_SAVE_SQL, (text, now, now, entry_ref, block_index))
    return SegmentRevision(
        index=block_index, text=text, revised_at=now, source_hash=str(row["block_hash"])
    )


async def clear_revision(db: Any, entry_ref: str, block_index: int) -> None:
    """撤销修订（幂等：无修订时为 no-op；无任何行 → NotFound）。"""
    await db.migrate()
    row = await db.fetch_one(
        "SELECT id FROM ai_translation_segments WHERE entry_ref = ? AND block_index = ? LIMIT 1",
        (entry_ref, block_index),
    )
    if row is None:
        raise SegmentRevisionNotFound(
            f"No cached translation segment {block_index} for this entry."
        )
    await db.execute(_CLEAR_SQL, (utc_now(), entry_ref, block_index))
