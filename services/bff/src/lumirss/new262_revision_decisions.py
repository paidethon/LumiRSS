"""NEW-262 译文人工修订层 —— 逐段「重新翻译前是否保留修订」的显式决定。

F062 已提供修订保存/历史/全量覆盖。本模块补上逐段粒度的显式放弃：

- discard：用户对单个已修订段选择「放弃本段修订并重翻」。被放弃
  时刻的人工文本与它曾覆盖的机器原稿同时留底（0189 台账只追加，
  overwritten_text / superseded_machine_text）——任何覆盖都不销毁
  历史；随后该段的缓存行被移除，真正回到「未生成」状态，显式重翻
  时才会再发 provider（可立即触发，也可稍后）；
- 其余修订段原样保留（默认 F062 语义不变）；
- list：某篇的决定台账（新→旧），供 UI 回看「放弃了什么」。

全部 SQL 为内联字面量 + 绑定参数。
"""

import uuid
from dataclasses import dataclass
from typing import Any

from lumirss.ai_translation_revisions import clear_revision
from lumirss.util import utc_now


class RevisionDiscardInvalid(Exception):
    """放弃动作非法（该段无缓存行 / 无修订可放弃）→ 422。"""


@dataclass(frozen=True)
class RevisionDecision:
    """一条「修订 → 放弃重翻」的决定（含留存的源段文本，供立即重翻）。"""

    id: str
    index: int
    overwritten_text: str
    superseded_machine_text: str
    source_text: str
    created_at: str


_DISCARD_SQL = """INSERT INTO translation_revision_decisions
(id, entry_ref, block_index, decision, overwritten_text,
 superseded_machine_text, created_at)
VALUES (?, ?, ?, 'discarded', ?, ?, ?)"""

_LIST_SQL = """SELECT id, block_index, overwritten_text,
superseded_machine_text, created_at
FROM translation_revision_decisions
WHERE entry_ref = ? ORDER BY created_at DESC, id DESC"""

_DELETE_ROWS_SQL = """DELETE FROM ai_translation_segments
WHERE entry_ref = ? AND block_index = ?"""


async def discard_revision(db: Any, entry_ref: str, block_index: int) -> RevisionDecision:
    """放弃一段的人工修订：留底（人工文本 + 机器原稿）+ 撤销修订 +
    移除该段缓存行（回到未生成；显式重翻才再发 provider）。

    该段没有任何缓存行 / 无修订可放弃 → RevisionDiscardInvalid。"""
    await db.migrate()
    row = await db.fetch_one(
        """SELECT user_revision, translated_text, source_text
        FROM ai_translation_segments
        WHERE entry_ref = ? AND block_index = ?
        ORDER BY updated_at DESC, id DESC LIMIT 1""",
        (entry_ref, block_index),
    )
    if row is None:
        raise RevisionDiscardInvalid(
            f"No cached translation segment {block_index} for this entry."
        )
    overwritten = row["user_revision"]
    if not overwritten:
        raise RevisionDiscardInvalid(
            f"Segment {block_index} has no user revision to discard."
        )
    machine = str(row["translated_text"] or "")
    source_text = str(row["source_text"] or "")
    now = utc_now()
    decision_id = f"trd-{uuid.uuid4().hex[:16]}"
    await db.execute(
        _DISCARD_SQL,
        (decision_id, entry_ref, block_index, str(overwritten), machine, now),
    )
    await clear_revision(db, entry_ref, block_index)
    # 该段回到真正的未生成态：移除全部缓存变体行（机器原稿已在台账
    # 留底；N085 修订历史表不受影响）。
    await db.execute(_DELETE_ROWS_SQL, (entry_ref, block_index))
    return RevisionDecision(
        id=decision_id,
        index=block_index,
        overwritten_text=str(overwritten),
        superseded_machine_text=machine,
        source_text=source_text,
        created_at=now,
    )


async def list_decisions(db: Any, entry_ref: str) -> list[dict[str, Any]]:
    """某篇的决定台账（新→旧）。"""
    await db.migrate()
    rows = await db.fetch_all(_LIST_SQL, (entry_ref,))
    return [
        {
            "id": str(row["id"]),
            "blockIndex": int(row["block_index"]),
            "overwrittenText": str(row["overwritten_text"]),
            "supersededMachineText": str(row["superseded_machine_text"] or ""),
            "createdAt": str(row["created_at"] or ""),
        }
        for row in rows
    ]
