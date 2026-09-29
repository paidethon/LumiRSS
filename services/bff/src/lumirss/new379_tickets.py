"""NEW-379 用户问题工单 —— 提交、指派、回复、关闭。

边界（本模块存在的理由）：

- 工单正文只来自用户**显式提交**的 subject/body；系统绝不自动附带
  该用户的文章/资料库/会话正文——admin 端点没有任何路径去读取工单
  之外的成员内容（本模块对 per-user 库零查询）；
- 普通用户只能看到/回复自己的工单（member 路由固定以会话身份为
  主语；他人 id 直接 404，不泄露存在性）；
- 指派目标必须是 owner/admin（不能把成员指派成处理人）；
- 状态机：open → assigned → answered → closed；closed 是终态
  （成员与管理员都不能再回复）；重复关闭 → 409（状态陈旧信号）。
"""

import uuid
from typing import Any

from lumirss.db_tx import transaction
from lumirss.util import utc_now

MAX_SUBJECT = 120
MAX_BODY = 2000

_TICKET_STATUSES = ("open", "assigned", "answered", "closed")


class TicketInvalid(ValueError):
    """载荷非法（422）。"""


class TicketNotFound(Exception):
    """工单不存在或不可见（404）。"""


class TicketStateInvalid(Exception):
    """状态不允许该操作（409）。"""


def clean_ticket_fields(subject: Any, body: Any) -> tuple[str, str]:
    if not isinstance(subject, str) or not subject.strip():
        raise TicketInvalid("subject 必须是非空字符串。")
    if not isinstance(body, str) or not body.strip():
        raise TicketInvalid("body 必须是非空字符串。")
    subject = subject.strip()
    body = body.strip()
    if len(subject) > MAX_SUBJECT:
        raise TicketInvalid(f"subject 最长 {MAX_SUBJECT} 字。")
    if len(body) > MAX_BODY:
        raise TicketInvalid(f"body 最长 {MAX_BODY} 字。")
    return subject, body


def clean_reply(body: Any) -> str:
    if not isinstance(body, str) or not body.strip():
        raise TicketInvalid("回复内容必须是非空字符串。")
    cleaned = body.strip()
    if len(cleaned) > MAX_BODY:
        raise TicketInvalid(f"回复内容最长 {MAX_BODY} 字。")
    return cleaned


def _ticket_json(row: Any, *, include_body: bool) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": str(row["id"]),
        "subject": str(row["subject"]),
        "status": str(row["status"]),
        "assignedTo": row["assigned_to"],
        "createdAt": str(row["created_at"]),
        "updatedAt": str(row["updated_at"]),
    }
    if include_body:
        payload["body"] = str(row["body"])
        payload["submittedBy"] = str(row["submitted_by"])
    return payload


async def create_ticket(
    control_db: Any, *, submitted_by: str, subject: str, body: str
) -> dict[str, Any]:
    subject, body = clean_ticket_fields(subject, body)
    await control_db.migrate()
    ticket_id = uuid.uuid4().hex
    now = utc_now()
    await control_db.execute(
        "INSERT INTO admin_tickets (id, subject, body, submitted_by, status, assigned_to, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, 'open', NULL, ?, ?)",
        (ticket_id, subject, body, submitted_by, now, now),
    )
    return {"id": ticket_id, "subject": subject, "status": "open", "createdAt": now}


async def list_tickets(
    control_db: Any, *, submitted_by: str | None = None, status: str | None = None, limit: int = 50
) -> list[dict[str, Any]]:
    if status is not None and status not in _TICKET_STATUSES:
        raise TicketInvalid(f"status 只能是 {'/'.join(_TICKET_STATUSES)}。")
    await control_db.migrate()
    clauses: list[str] = []
    params: list[Any] = []
    if submitted_by is not None:
        clauses.append("submitted_by = ?")
        params.append(submitted_by)
    if status is not None:
        clauses.append("status = ?")
        params.append(status)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(max(1, min(limit, 100)))
    rows = await control_db.fetch_all(
        f"SELECT * FROM admin_tickets{where} ORDER BY created_at DESC, id DESC LIMIT ?",
        tuple(params),
    )
    return [_ticket_json(row, include_body=False) for row in rows]


async def get_ticket(
    control_db: Any, *, ticket_id: str, submitted_by: str | None = None
) -> dict[str, Any] | None:
    """工单 + 回复线；submitted_by 非空 = 成员视角（只能看自己的）。"""
    await control_db.migrate()
    row = await control_db.fetch_one(
        "SELECT * FROM admin_tickets WHERE id = ?", (ticket_id,)
    )
    if row is None:
        return None
    if submitted_by is not None and str(row["submitted_by"]) != submitted_by:
        return None  # 他人工单按不存在处理（不泄露存在性）
    replies = await control_db.fetch_all(
        "SELECT author_id, author_role, body, created_at FROM admin_ticket_replies"
        " WHERE ticket_id = ? ORDER BY id ASC",
        (ticket_id,),
    )
    payload = _ticket_json(row, include_body=True)
    payload["replies"] = [
        {
            "authorId": str(r["author_id"]),
            "authorRole": str(r["author_role"]),
            "body": str(r["body"]),
            "createdAt": str(r["created_at"]),
        }
        for r in replies
    ]
    return payload


async def assign_ticket(
    control_db: Any, *, ticket_id: str, assignee_id: str, by: str
) -> dict[str, Any]:
    """指派给管理员；open/assigned/answered 均可改派（closed 终态拒绝）。"""
    await control_db.migrate()

    def _write(conn: Any) -> dict[str, Any]:
        row = conn.execute(
            "SELECT status FROM admin_tickets WHERE id = ?", (ticket_id,)
        ).fetchone()
        if row is None:
            raise TicketNotFound(ticket_id)
        if str(row["status"]) == "closed":
            raise TicketStateInvalid(ticket_id)
        conn.execute(
            "UPDATE admin_tickets SET status = 'assigned', assigned_to = ?, updated_at = ? WHERE id = ?",
            (assignee_id, utc_now(), ticket_id),
        )
        return {"id": ticket_id, "status": "assigned", "assignedTo": assignee_id, "by": by}

    return await transaction(control_db, _write)


async def reply_ticket(
    control_db: Any, *, ticket_id: str, author_id: str, author_role: str, body: str,
    as_submitter: str | None = None,
) -> dict[str, Any]:
    """回复并推进状态：管理员回复 → answered；提交人回复保持现状。
    closed 终态拒绝双方。"""
    body = clean_reply(body)
    await control_db.migrate()

    def _write(conn: Any) -> dict[str, Any]:
        row = conn.execute(
            "SELECT status, submitted_by FROM admin_tickets WHERE id = ?", (ticket_id,)
        ).fetchone()
        if row is None:
            raise TicketNotFound(ticket_id)
        if as_submitter is not None and str(row["submitted_by"]) != as_submitter:
            raise TicketNotFound(ticket_id)
        if str(row["status"]) == "closed":
            raise TicketStateInvalid(ticket_id)
        new_status = "answered" if author_role in ("owner", "admin") else str(row["status"])
        conn.execute(
            "INSERT INTO admin_ticket_replies (ticket_id, author_id, author_role, body, created_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (ticket_id, author_id, author_role, body, utc_now()),
        )
        conn.execute(
            "UPDATE admin_tickets SET status = ?, updated_at = ? WHERE id = ?",
            (new_status, utc_now(), ticket_id),
        )
        return {"id": ticket_id, "status": new_status}

    return await transaction(control_db, _write)


async def close_ticket(control_db: Any, *, ticket_id: str, by: str) -> dict[str, Any]:
    await control_db.migrate()

    def _write(conn: Any) -> dict[str, Any]:
        row = conn.execute(
            "SELECT status FROM admin_tickets WHERE id = ?", (ticket_id,)
        ).fetchone()
        if row is None:
            raise TicketNotFound(ticket_id)
        if str(row["status"]) == "closed":
            raise TicketStateInvalid(ticket_id)
        conn.execute(
            "UPDATE admin_tickets SET status = 'closed', updated_at = ? WHERE id = ?",
            (utc_now(), ticket_id),
        )
        return {"id": ticket_id, "status": "closed", "by": by}

    return await transaction(control_db, _write)


async def ticket_counts(control_db: Any) -> dict[str, int]:
    await control_db.migrate()
    rows = await control_db.fetch_all(
        "SELECT status, COUNT(*) AS n FROM admin_tickets GROUP BY status", ()
    )
    counts = {status: 0 for status in _TICKET_STATUSES}
    for row in rows:
        counts[str(row["status"])] = int(row["n"])
    return counts
