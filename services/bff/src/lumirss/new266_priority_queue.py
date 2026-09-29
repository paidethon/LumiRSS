"""NEW-266 分段翻译优先队列 —— 用户指定的先行翻译顺序。

用户为某篇登记块优先级（当前章节/选段先行，之后可追加其他段）：

- enqueue 保序去重（重复追加是 no-op，不移动已有位置）；每篇上限
  QUEUE_CAP 条（与 MAX_BLOCKS 同界）；
- 执行是显式 run：队列里的索引先于其余块发 provider —— 具体做法是
  从用户提交的块集合中按队列顺序筛出子集，交给
  SegmentTranslationService.generate。缓存语义全部由生成路径保证：
  已有成功缓存行 / N086 标记 / F062 修订保留段都不会再发 provider，
  即「已有结果不重复收费」是缓存身份的自然结果，不是第二次计费；
- 队列里出现当前块集合没有的索引 → 如实上报 skippedMissingText
  （源文更新后旧队列可能失效），不臆造文本。

全部 SQL 为内联字面量 + 绑定参数。
"""

import uuid
from dataclasses import dataclass
from typing import Any

from lumirss.ai_translation_segments import SegmentInput
from lumirss.util import utc_now

QUEUE_CAP = 64

_ENQUEUE_SQL = """INSERT INTO translation_priority_queue
(id, entry_ref, block_index, seq, added_at) VALUES (?, ?, ?, ?, ?)"""

_LIST_SQL = """SELECT block_index, added_at FROM translation_priority_queue
WHERE entry_ref = ? ORDER BY seq ASC"""

_COUNT_SQL = "SELECT COUNT(*) AS total FROM translation_priority_queue WHERE entry_ref = ?"

_NEXT_SEQ_SQL = """SELECT COALESCE(MAX(seq), 0) + 1 AS next FROM translation_priority_queue
WHERE entry_ref = ?"""


class QueueCapExceeded(Exception):
    """队列超出每篇上限 → 422。"""


class QueueIndexInvalid(Exception):
    """索引越界/非法 → 422。"""


@dataclass(frozen=True)
class QueueEntry:
    index: int
    added_at: str


def _validate_index(block_index: int) -> int:
    if not isinstance(block_index, int) or not 0 <= block_index < QUEUE_CAP:
        raise QueueIndexInvalid("block_index 必须在 0..63 之间。")
    return block_index


async def enqueue(db: Any, entry_ref: str, indexes: list[int]) -> list[QueueEntry]:
    """按给出顺序追加（重复索引 no-op 保位）；超上限整体拒绝。"""
    await db.migrate()
    clean: list[int] = []
    for raw in indexes:
        index = _validate_index(raw)
        if index not in clean:
            clean.append(index)
    existing = {entry.index for entry in await list_queue(db, entry_ref)}
    fresh = [index for index in clean if index not in existing]
    if fresh:
        row = await db.fetch_one(_COUNT_SQL, (entry_ref,))
        current = int(row["total"]) if row is not None else 0
        if current + len(fresh) > QUEUE_CAP:
            raise QueueCapExceeded(
                f"At most {QUEUE_CAP} queued blocks per entry."
            )
        seq_row = await db.fetch_one(_NEXT_SEQ_SQL, (entry_ref,))
        base_seq = int(seq_row["next"]) if seq_row is not None else 1
        now = utc_now()
        for offset, index in enumerate(fresh):
            await db.execute(
                _ENQUEUE_SQL,
                (
                    f"tpq-{uuid.uuid4().hex[:16]}",
                    entry_ref,
                    index,
                    base_seq + offset,
                    now,
                ),
            )
    return await list_queue(db, entry_ref)


async def list_queue(db: Any, entry_ref: str) -> list[QueueEntry]:
    """当前队列（登记顺序）。"""
    await db.migrate()
    rows = await db.fetch_all(_LIST_SQL, (entry_ref,))
    return [
        QueueEntry(int(row["block_index"]), str(row["added_at"] or ""))
        for row in rows
    ]


async def remove(db: Any, entry_ref: str, block_index: int) -> bool:
    """显式移出一块；未知 → False。"""
    await db.migrate()
    _validate_index(block_index)
    row = await db.fetch_one(
        "SELECT id FROM translation_priority_queue WHERE entry_ref = ? AND block_index = ?",
        (entry_ref, block_index),
    )
    if row is None:
        return False
    await db.execute(
        "DELETE FROM translation_priority_queue WHERE id = ?", (row["id"],)
    )
    return True


async def clear_queue(db: Any, entry_ref: str) -> int:
    """清空某篇队列，返回移除条数。"""
    await db.migrate()
    row = await db.fetch_one(_COUNT_SQL, (entry_ref,))
    await db.execute(
        "DELETE FROM translation_priority_queue WHERE entry_ref = ?", (entry_ref,)
    )
    return int(row["total"]) if row is not None else 0


async def run_queue(
    db: Any,
    service: Any,
    entry_ref: str,
    blocks: list[SegmentInput],
) -> dict[str, Any]:
    """显式执行：按队列顺序只翻「队列 ∩ 提交块集合」，缓存规则沿用
    生成路径（已有结果/标记/修订段零 provider 调用）。

    返回 queuedStates（按队列顺序）+ skippedMissingText（队列里有、
    当前块集合没有的索引）。执行后队列原样保留（可反复补翻其余段）。"""
    await db.migrate()
    queue = await list_queue(db, entry_ref)
    by_index = {block.index: block for block in blocks}
    ordered: list[SegmentInput] = []
    skipped: list[int] = []
    for entry in queue:
        block = by_index.get(entry.index)
        if block is None:
            skipped.append(entry.index)
        elif block not in ordered:
            ordered.append(block)
    states = (
        await service.generate(entry_ref, ordered) if ordered else []
    )
    return {
        "queuedStates": states,
        "skippedMissingText": skipped,
        "queuedCount": len(ordered),
    }
