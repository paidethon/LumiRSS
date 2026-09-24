"""N086 不翻译片段标记 —— per-entry 的块级「不翻译」持久标注。

标记是用户意图，跨引擎/模型/语言/源文变体共享 —— 因此它不是段缓存
行上的标志，而是独立的 (entry_ref, block_index) 主键表（0085）。语义：

- mark：写入标记；每条目上限 200 块（存储有界），超限抛
  NoTranslateCapExceeded（路由映射 422）；
- unmark：撤销标记（幂等，无标记也是 no-op）；
- marked_blocks：generate() 用它把标记块排除在 provider 请求之外 ——
  已有缓存译文照常返回展示；没有则诚实显示原文（not_generated）。

全部 SQL 为内联字面量 + 绑定参数；每个执行站点一条字面量。
"""

from typing import Any

from lumirss.util import utc_now

MAX_NO_TRANSLATE_BLOCKS = 200

_MARKED_SQL = (
    "SELECT block_index FROM entry_no_translate_blocks WHERE entry_ref = ?"
)

_MARK_SQL = (
    "INSERT OR IGNORE INTO entry_no_translate_blocks "
    "(entry_ref, block_index, marked_at) VALUES (?, ?, ?)"
)

_UNMARK_SQL = "DELETE FROM entry_no_translate_blocks WHERE entry_ref = ? AND block_index = ?"

_COUNT_SQL = "SELECT COUNT(*) AS total FROM entry_no_translate_blocks WHERE entry_ref = ?"


class NoTranslateCapExceeded(Exception):
    """每条目的不翻译块数已达上限（路由映射 422）。"""


async def marked_blocks(db: Any, entry_ref: str) -> set[int]:
    """该条目全部被标记为「不翻译」的块索引集合。"""
    await db.migrate()
    rows = await db.fetch_all(_MARKED_SQL, (entry_ref,))
    return {int(row["block_index"]) for row in rows}


async def mark_block(db: Any, entry_ref: str, block_index: int) -> None:
    """标记一块为「不翻译」；超过每条目上限 → NoTranslateCapExceeded。"""
    await db.migrate()
    row = await db.fetch_one(_COUNT_SQL, (entry_ref,))
    if row is not None and int(row["total"]) >= MAX_NO_TRANSLATE_BLOCKS:
        existing = await marked_blocks(db, entry_ref)
        if block_index not in existing:
            raise NoTranslateCapExceeded(
                f"At most {MAX_NO_TRANSLATE_BLOCKS} no-translate blocks per entry."
            )
    await db.execute(_MARK_SQL, (entry_ref, block_index, utc_now()))


async def unmark_block(db: Any, entry_ref: str, block_index: int) -> None:
    """撤销一块的「不翻译」标记（幂等）。"""
    await db.migrate()
    await db.execute(_UNMARK_SQL, (entry_ref, block_index))
