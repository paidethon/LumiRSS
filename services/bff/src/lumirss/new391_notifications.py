"""NEW-391 应用内通知收件箱 —— 真实事件集中展示（control 库）。

边界（硬规则）：

- **通知只来自真实事件**：唯一写入口 ``record_event``，由发生事件的
  域在收尾时调用（本组内：NEW-399 管理员修订回复 → help_answered；
  任务完成/失败、共享变化由对应域登记）。没有事件就没有通知行，
  本模块绝不猜测、绝不定时造事件；
- 私人事件只给本人：全部读/写路径 WHERE user_id = 会话身份；
  他人 id 一律 404 同形（不泄露存在性）；
- 处理与保留：按类型过滤 + 全部已读（集合语义，非 toggle）+ 逐条
  dismiss（本人主动清理）；
- 动作有效性在**读取时**联判 NEW-394 撤销登记：已撤销事件
  actionable 强制为假并带失效原因——绝不提供不可执行按钮；
- ref 只存不透明引用串，绝不内嵌正文/凭据/会话密钥。
"""

from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

KINDS = ("task_completed", "task_failed", "share_event", "help_answered")
MAX_TITLE = 200
MAX_BODY = 1000
MAX_REF = 200
MAX_SOURCE = 120
_LIST_LIMIT = 100


class NotificationInvalid(ValueError):
    """载荷非法（422）。"""


class NotificationNotFound(Exception):
    """通知不存在或不属于调用者（404 同形）。"""


def _clean(value: Any, field: str, limit: int, *, required: bool = True) -> str:
    if value is None:
        if required:
            raise NotificationInvalid(f"{field} 不能为空。")
        return ""
    if not isinstance(value, str):
        raise NotificationInvalid(f"{field} 必须是字符串。")
    clean = value.strip()
    if required and not clean:
        raise NotificationInvalid(f"{field} 不能为空。")
    if len(clean) > limit:
        raise NotificationInvalid(f"{field} 最长 {limit} 字符。")
    return clean


async def record_event(
    db: Database,
    *,
    user_id: str,
    kind: str,
    source: str,
    title: str,
    body: str = "",
    ref: str = "",
    actionable: bool = False,
    occurred_at: str | None = None,
) -> dict[str, Any]:
    """登记一条真实事件（各域收尾调用；不是用户面入口）。"""
    if kind not in KINDS:
        raise NotificationInvalid(f"未知通知类型：{kind}。")
    clean_source = _clean(source, "来源", MAX_SOURCE)
    clean_title = _clean(title, "标题", MAX_TITLE)
    clean_body = _clean(body, "正文", MAX_BODY, required=False)
    clean_ref = _clean(ref, "引用", MAX_REF, required=False)
    await db.migrate()
    now = utc_now()
    occurred = _clean(occurred_at, "发生时间", 40, required=False) if occurred_at else now
    new_id = await db.execute(
        "INSERT INTO user_notifications (user_id, kind, source, title, body, ref,"
        " actionable, occurred_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            user_id,
            kind,
            clean_source,
            clean_title,
            clean_body,
            clean_ref,
            1 if actionable else 0,
            occurred,
            now,
        ),
    )
    return {"id": str(new_id), "kind": kind, "createdAt": now}


async def _revocation_map(db: Database, user_id: str) -> dict[int, dict[str, Any]]:
    rows = await db.fetch_all(
        "SELECT notification_id, reason, revoked_at FROM notification_action_revocations"
        " WHERE user_id = ?",
        (user_id,),
    )
    return {
        int(row["notification_id"]): {
            "reason": str(row["reason"]),
            "revokedAt": str(row["revoked_at"]),
        }
        for row in rows
    }


def _to_dto(row: Any, revocation: dict[str, Any] | None) -> dict[str, Any]:
    revoked = revocation is not None
    return {
        "id": str(row["id"]),
        "kind": str(row["kind"]),
        "source": str(row["source"]),
        "title": str(row["title"]),
        "body": str(row["body"]),
        "ref": str(row["ref"]),
        "actionable": bool(row["actionable"]) and not revoked,
        "invalidReason": revocation["reason"] if revoked else None,
        "revokedAt": revocation["revokedAt"] if revoked else None,
        "occurredAt": str(row["occurred_at"]),
        "createdAt": str(row["created_at"]),
        "readAt": str(row["read_at"]) if row["read_at"] is not None else None,
    }


async def list_notifications(
    db: Database,
    user_id: str,
    *,
    kind: str | None = None,
    unread_only: bool = False,
    limit: int = 50,
) -> dict[str, Any]:
    if kind is not None and kind not in KINDS:
        raise NotificationInvalid(f"未知通知类型：{kind}。")
    bounded = max(1, min(int(limit), _LIST_LIMIT))
    await db.migrate()
    where = "WHERE user_id = ?"
    params: list[Any] = [user_id]
    if kind is not None:
        where += " AND kind = ?"
        params.append(kind)
    if unread_only:
        where += " AND read_at IS NULL"
    rows = await db.fetch_all(
        f"SELECT * FROM user_notifications {where}"
        f" ORDER BY occurred_at DESC, id DESC LIMIT {int(bounded)}",
        tuple(params),
    )
    revocations = await _revocation_map(db, user_id)
    items = [_to_dto(row, revocations.get(int(row["id"]))) for row in rows]
    all_rows = await db.fetch_all(
        "SELECT kind, read_at FROM user_notifications WHERE user_id = ?", (user_id,)
    )
    counts: dict[str, int] = {name: 0 for name in KINDS}
    unread_total = 0
    for row in all_rows:
        counts[str(row["kind"])] = counts.get(str(row["kind"]), 0) + 1
        if row["read_at"] is None:
            unread_total += 1
    return {"items": items, "counts": counts, "unread": unread_total}


async def mark_read(db: Database, user_id: str, notification_id: str) -> dict[str, Any] | None:
    """标记已读（幂等集合语义）；非本人/不存在 → None（404 同形）。"""
    await db.migrate()
    row = await _owned_row(db, user_id, notification_id)
    if row is None:
        return None
    if row["read_at"] is None:
        await db.execute(
            "UPDATE user_notifications SET read_at = ? WHERE id = ? AND user_id = ?",
            (utc_now(), row["id"], user_id),
        )
    fresh = await _owned_row(db, user_id, notification_id)
    revocations = await _revocation_map(db, user_id)
    assert fresh is not None
    return _to_dto(fresh, revocations.get(int(fresh["id"])))


async def mark_all_read(
    db: Database, user_id: str, *, kind: str | None = None
) -> dict[str, Any]:
    if kind is not None and kind not in KINDS:
        raise NotificationInvalid(f"未知通知类型：{kind}。")
    await db.migrate()
    where = "WHERE user_id = ? AND read_at IS NULL"
    params: list[Any] = [user_id]
    if kind is not None:
        where += " AND kind = ?"
        params.append(kind)
    updated = await db.execute(
        f"UPDATE user_notifications SET read_at = ? {where}",
        (utc_now(), *params),
    )
    return {"marked": int(updated or 0)}


async def dismiss(db: Database, user_id: str, notification_id: str) -> bool:
    """本人删除一条通知（保留策略的用户侧动作）；非本人 → False。"""
    await db.migrate()
    row = await _owned_row(db, user_id, notification_id)
    if row is None:
        return False
    await db.execute("DELETE FROM user_notifications WHERE id = ?", (row["id"],))
    await db.execute(
        "DELETE FROM notification_action_revocations WHERE notification_id = ?",
        (row["id"],),
    )
    return True


async def _owned_row(db: Database, user_id: str, notification_id: str) -> Any:
    try:
        numeric = int(str(notification_id))
    except ValueError as exc:
        raise NotificationNotFound("没有这条通知。") from exc
    row = await db.fetch_one(
        "SELECT * FROM user_notifications WHERE id = ? AND user_id = ?",
        (numeric, user_id),
    )
    if row is None:
        raise NotificationNotFound("没有这条通知。")
    return row
