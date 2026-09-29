"""NEW-263 译文质量反馈 —— 对具体段落标记漏译/误译/格式问题。

每条反馈锚定 (entry_ref, block_index)：创建时刻从段缓存行快照
源段文本 / 机器译文 / 人工修订（关联原文；源文后续更新不移动已建
反馈）。问题类型限定 omission（漏译）/ mistranslation（误译）/
format（格式问题）。

- status='open' 的条目构成「本人的待复核队列」——per-user 库天然
  隔离，队列只含本人反馈；
- resolve / delete 是显式出队动作；重复 resolve / 未知 id → 404。

全部 SQL 为内联字面量 + 绑定参数。
"""

import uuid
from typing import Any

from lumirss.util import utc_now

ISSUE_KINDS = ("omission", "mistranslation", "format")
MAX_NOTE = 500


class FeedbackInvalid(Exception):
    """反馈负载非法（未知段 / 未知问题类型 / 空注释）→ 422。"""


class FeedbackNotFound(Exception):
    """未知反馈 id / 已出队 → 404。"""


_CREATE_SQL = """INSERT INTO translation_quality_feedback
(id, entry_ref, block_index, issue_kind, note, source_excerpt,
 machine_excerpt, revised_excerpt, status, created_at, resolved_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'open', ?, NULL)"""


async def create_feedback(
    db: Any,
    entry_ref: str,
    block_index: int,
    issue_kind: str,
    note: str = "",
) -> dict[str, Any]:
    """创建一条段级质量反馈（创建时刻快照三段文本）。"""
    await db.migrate()
    clean_kind = str(issue_kind or "").strip()
    if clean_kind not in ISSUE_KINDS:
        raise FeedbackInvalid(
            "issueKind 必须是 omission / mistranslation / format 之一。"
        )
    clean_note = str(note or "").strip()
    if len(clean_note) > MAX_NOTE:
        raise FeedbackInvalid(f"note 最长 {MAX_NOTE} 字。")
    row = await db.fetch_one(
        """SELECT source_text, translated_text, user_revision
        FROM ai_translation_segments
        WHERE entry_ref = ? AND block_index = ?
        ORDER BY updated_at DESC, id DESC LIMIT 1""",
        (entry_ref, block_index),
    )
    if row is None:
        raise FeedbackInvalid(
            f"No cached translation segment {block_index} for this entry."
        )
    feedback_id = f"tqf-{uuid.uuid4().hex[:16]}"
    now = utc_now()
    await db.execute(
        _CREATE_SQL,
        (
            feedback_id,
            entry_ref,
            block_index,
            clean_kind,
            clean_note,
            row["source_text"],
            row["translated_text"],
            row["user_revision"],
            now,
        ),
    )
    return await get_feedback(db, feedback_id)


async def get_feedback(db: Any, feedback_id: str) -> dict[str, Any]:
    row = await db.fetch_one(
        "SELECT * FROM translation_quality_feedback WHERE id = ?", (feedback_id,)
    )
    if row is None:
        raise FeedbackNotFound("反馈不存在。")
    return _view(row)


def _view(row: Any) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "entryRef": str(row["entry_ref"]),
        "blockIndex": int(row["block_index"]),
        "issueKind": str(row["issue_kind"]),
        "note": str(row["note"] or ""),
        "sourceExcerpt": row["source_excerpt"],
        "machineExcerpt": row["machine_excerpt"],
        "revisedExcerpt": row["revised_excerpt"],
        "status": str(row["status"]),
        "createdAt": str(row["created_at"] or ""),
        "resolvedAt": row["resolved_at"],
    }


async def list_feedback(db: Any, entry_ref: str) -> list[dict[str, Any]]:
    """某篇的反馈（新→旧）。"""
    await db.migrate()
    rows = await db.fetch_all(
        """SELECT * FROM translation_quality_feedback
        WHERE entry_ref = ? ORDER BY created_at DESC, id DESC""",
        (entry_ref,),
    )
    return [_view(row) for row in rows]


async def queue(db: Any, limit: int = 100) -> list[dict[str, Any]]:
    """本人待复核队列（全部 open，跨条目；新→旧）。"""
    await db.migrate()
    rows = await db.fetch_all(
        """SELECT * FROM translation_quality_feedback
        WHERE status = 'open' ORDER BY created_at DESC, id DESC LIMIT ?""",
        (max(1, min(limit, 200)),),
    )
    return [_view(row) for row in rows]


async def resolve_feedback(db: Any, feedback_id: str) -> dict[str, Any]:
    """复核完成 → resolved（显式出队）。未知 / 已解决 → FeedbackNotFound。"""
    await db.migrate()
    row = await db.fetch_one(
        "SELECT status FROM translation_quality_feedback WHERE id = ?",
        (feedback_id,),
    )
    if row is None or str(row["status"]) != "open":
        raise FeedbackNotFound("反馈不存在或已出队。")
    now = utc_now()
    await db.execute(
        "UPDATE translation_quality_feedback SET status = 'resolved', resolved_at = ? "
        "WHERE id = ?",
        (now, feedback_id),
    )
    return await get_feedback(db, feedback_id)


async def delete_feedback(db: Any, feedback_id: str) -> bool:
    """删除一条反馈（显式出队）。未知 → False。"""
    await db.migrate()
    row = await db.fetch_one(
        "SELECT id FROM translation_quality_feedback WHERE id = ?", (feedback_id,)
    )
    if row is None:
        return False
    await db.execute(
        "DELETE FROM translation_quality_feedback WHERE id = ?", (feedback_id,)
    )
    return True
