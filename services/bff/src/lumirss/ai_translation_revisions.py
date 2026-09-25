"""F062 译文手工修订 — per (entry_ref, block_index) 的用户修订存储。

修订写入 ai_translation_segments 该段的全部缓存变体行（不同源文 hash /
引擎 / 模型 / 语言各成一行的缓存身份共享同一修订）：

- save：user_revision = 用户文本、revised_at = now、source_hash =
  保存时当前行的 block_hash（修订锚定的源段）；
- stale 判定在读取侧：revision.source_hash != 当前源段 block_hash →
  源文已更新（修订保留、只标记，不误删）；
- clear：撤销修订（全部变体一起清）。

N085 修订历史：save 覆盖已有修订时，把上一版推入
ai_translation_revision_history（每段上限 REVISION_HISTORY_CAP 条，
超出淘汰最旧）；restore 弹出最新一条历史作为当前修订（当前文本不
回推历史——「恢复上一版」是逐版回退的单向栈）。

全部 SQL 为内联字面量 + 绑定参数；写站点：save/clear/历史推入与
淘汰/restore 各一处。
"""

from dataclasses import dataclass
from typing import Any

from lumirss.util import utc_now

MAX_REVISION_CHARS = 10000

# N085：每段修订历史条数上限（超出淘汰最旧）。
REVISION_HISTORY_CAP = 5

_SAVE_SQL = """UPDATE ai_translation_segments
SET user_revision = ?, revised_at = ?, source_hash = block_hash, updated_at = ?
WHERE entry_ref = ? AND block_index = ?"""

_CLEAR_SQL = """UPDATE ai_translation_segments
SET user_revision = NULL, revised_at = NULL, source_hash = NULL, updated_at = ?
WHERE entry_ref = ? AND block_index = ?"""

# N085：覆盖前把上一版修订推入历史（上一版为空 = 首次修订，无历史）。
_PUSH_HISTORY_SQL = """INSERT INTO ai_translation_revision_history
(entry_ref, block_index, old_text, replaced_at)
SELECT entry_ref, block_index, user_revision, ?
FROM ai_translation_segments
WHERE entry_ref = ? AND block_index = ? AND user_revision IS NOT NULL
AND id = (
    SELECT id FROM ai_translation_segments
    WHERE entry_ref = ? AND block_index = ?
    ORDER BY updated_at DESC, id DESC LIMIT 1
)"""

# N085：淘汰超出容量的最旧历史（保留最新 CAP 条）。
_PRUNE_HISTORY_SQL = """DELETE FROM ai_translation_revision_history
WHERE entry_ref = ? AND block_index = ? AND id NOT IN (
    SELECT id FROM ai_translation_revision_history
    WHERE entry_ref = ? AND block_index = ?
    ORDER BY replaced_at DESC, id DESC LIMIT ?
)"""


@dataclass(frozen=True)
class SegmentRevision:
    """一条已保存的修订（按 block_index 关联任一变体行）。"""

    index: int
    text: str
    revised_at: str
    source_hash: str


@dataclass(frozen=True)
class RevisionHistoryEntry:
    """N085：一条被替换下来的历史修订（最新在前由调用方排序）。"""

    old_text: str
    replaced_at: str


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
    文本 hash；修订锚定源段而非缓存变体）。N085：覆盖已有修订时先把
    上一版推入历史（cap REVISION_HISTORY_CAP，超出淘汰最旧）。"""
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
    # N085：覆盖前留底（上一版为 NULL 时该 INSERT 影响 0 行——首次修订
    # 无历史，如实）。
    await db.execute(_PUSH_HISTORY_SQL, (now, entry_ref, block_index, entry_ref, block_index))
    await db.execute(_PRUNE_HISTORY_SQL, (entry_ref, block_index, entry_ref, block_index, REVISION_HISTORY_CAP))
    await db.execute(_SAVE_SQL, (text, now, now, entry_ref, block_index))
    return SegmentRevision(
        index=block_index, text=text, revised_at=now, source_hash=str(row["block_hash"])
    )


async def revision_history(
    db: Any, entry_ref: str, block_index: int
) -> list[RevisionHistoryEntry]:
    """N085：一段的修订历史（最新在前；无缓存行 → NotFound）。"""
    await db.migrate()
    row = await db.fetch_one(
        "SELECT id FROM ai_translation_segments WHERE entry_ref = ? AND block_index = ? LIMIT 1",
        (entry_ref, block_index),
    )
    if row is None:
        raise SegmentRevisionNotFound(
            f"No cached translation segment {block_index} for this entry."
        )
    rows = await db.fetch_all(
        """SELECT old_text, replaced_at FROM ai_translation_revision_history
        WHERE entry_ref = ? AND block_index = ?
        ORDER BY replaced_at DESC, id DESC""",
        (entry_ref, block_index),
    )
    return [
        RevisionHistoryEntry(old_text=str(r["old_text"]), replaced_at=str(r["replaced_at"] or ""))
        for r in rows
    ]


async def restore_revision(
    db: Any, entry_ref: str, block_index: int
) -> SegmentRevision:
    """N085：恢复上一版修订——弹出最新历史条目作为当前修订。

    当前修订文本不回推历史（单向回退栈，逐次点击逐版回退）；
    无历史 / 无缓存行 → SegmentRevisionNotFound。"""
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
    latest = await db.fetch_one(
        """SELECT id, old_text FROM ai_translation_revision_history
        WHERE entry_ref = ? AND block_index = ?
        ORDER BY replaced_at DESC, id DESC LIMIT 1""",
        (entry_ref, block_index),
    )
    if latest is None:
        raise SegmentRevisionNotFound(
            f"No revision history for segment {block_index} of this entry."
        )
    now = utc_now()
    await db.execute(
        "DELETE FROM ai_translation_revision_history WHERE id = ?",
        (int(latest["id"]),),
    )
    await db.execute(_SAVE_SQL, (str(latest["old_text"]), now, now, entry_ref, block_index))
    return SegmentRevision(
        index=block_index,
        text=str(latest["old_text"]),
        revised_at=now,
        source_hash=str(row["block_hash"]),
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
