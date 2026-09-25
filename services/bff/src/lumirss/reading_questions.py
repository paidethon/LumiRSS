"""N074 阅读问题清单 — per-user 问题 CRUD + 按文章/批注检索。

- 问题先记下、来源后补：entry_ref / annotation_id / workspace_id 都是
  可选链接，创建时不强制；
- status 只在 open | done 之间切换（完成 / 重新打开都走同一 PATCH）；
- 原文删除不删问题（只影响展示层定位），本模块不做任何内容缓存；
- SQL 全部内联字面量 + 绑定参数（仓库约定）。
"""

import uuid as _uuid
from typing import Any

from lumirss.util import utc_now

MAX_QUESTION = 500
STATUSES = ("open", "done")
_LIST_LIMIT = 200


class QuestionInvalid(ValueError):
    """问题负载未通过校验。"""


def _clean_question(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise QuestionInvalid("question 不能为空。")
    if len(value) > MAX_QUESTION:
        raise QuestionInvalid(f"question 过长（≤{MAX_QUESTION} 字符）。")
    return value.strip()


_COLUMNS = (
    "id, question, status, entry_ref, annotation_id, workspace_id, created_at, updated_at"
)


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "question": str(row["question"]),
        "status": str(row["status"]),
        "entryRef": row["entry_ref"] if row["entry_ref"] is None else str(row["entry_ref"]),
        "annotationId": (
            row["annotation_id"] if row["annotation_id"] is None else str(row["annotation_id"])
        ),
        "workspaceId": (
            row["workspace_id"] if row["workspace_id"] is None else str(row["workspace_id"])
        ),
        "createdAt": str(row["created_at"]),
        "updatedAt": str(row["updated_at"]),
    }


async def create(
    db: Any,
    *,
    question: str,
    entry_ref: str | None = None,
    annotation_id: str | None = None,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    await db.migrate()
    clean = _clean_question(question)
    now = utc_now()
    question_id = str(_uuid.uuid4())
    await db.execute(
        f"INSERT INTO reading_questions ({_COLUMNS}) VALUES (?, ?, 'open', ?, ?, ?, ?, ?)",
        (question_id, clean, entry_ref, annotation_id, workspace_id, now, now),
    )
    return await get(db, question_id)  # type: ignore[return-value]


async def get(db: Any, question_id: str) -> dict[str, Any] | None:
    await db.migrate()
    row = await db.fetch_one(
        f"SELECT {_COLUMNS} FROM reading_questions WHERE id = ?", (question_id,)
    )
    return _row_to_dict(row) if row is not None else None


async def list_questions(
    db: Any,
    *,
    status: str | None = None,
    entry_ref: str | None = None,
    annotation_id: str | None = None,
) -> list[dict[str, Any]]:
    """按 status / entryRef / annotationId 过滤（全部可选，创建时间升序）。
    status 缺省 = 全部（open 与 done 都返回，诚实呈现清单全貌）。"""
    await db.migrate()
    where = "WHERE 1=1"
    params: list[Any] = []
    if status is not None:
        if status not in STATUSES:
            raise QuestionInvalid("status 必须是 open、done 或缺省。")
        where += " AND status = ?"
        params.append(status)
    if entry_ref is not None:
        where += " AND entry_ref = ?"
        params.append(entry_ref)
    if annotation_id is not None:
        where += " AND annotation_id = ?"
        params.append(annotation_id)
    rows = await db.fetch_all(
        f"SELECT {_COLUMNS} FROM reading_questions {where} ORDER BY created_at ASC, id ASC LIMIT ?",
        (*params, _LIST_LIMIT),
    )
    return [_row_to_dict(row) for row in rows]


async def update(
    db: Any,
    question_id: str,
    *,
    question: str | None = None,
    status: str | None = None,
) -> dict[str, Any] | None:
    await db.migrate()
    current = await get(db, question_id)
    if current is None:
        return None
    clean = current["question"] if question is None else _clean_question(question)
    new_status = current["status"] if status is None else status
    if new_status not in STATUSES:
        raise QuestionInvalid("status 必须是 open 或 done。")
    await db.execute(
        "UPDATE reading_questions SET question = ?, status = ?, updated_at = ? WHERE id = ?",
        (clean, new_status, utc_now(), question_id),
    )
    return await get(db, question_id)


async def delete(db: Any, question_id: str) -> bool:
    await db.migrate()
    current = await get(db, question_id)
    if current is None:
        return False
    await db.execute("DELETE FROM reading_questions WHERE id = ?", (question_id,))
    return True
