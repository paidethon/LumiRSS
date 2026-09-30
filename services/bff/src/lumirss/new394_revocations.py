"""NEW-394 通知动作撤销登记 —— 「原事件已撤销/权限失效」的事实层。

边界（硬规则）：

- 撤销登记是**显式动作**：上游撤销流程（共享链接收回、任务配置删除、
  权限回收等）在收尾时调用 ``register_revocation``；绝不因时间流逝、
  行为推断或任何定时器自动产生；
- 每条通知至多一条登记（UNIQUE notification_id）；重复登记 = 最新事实
  覆盖（原因 + 时间更新），符合「现状如此」而不是「历史堆叠」；
- 生效在**读取时联判**（0314 列表 / 0326 聚合视图均经 391 的
  ``_revocation_map`` 联查）：命中即 actionable 强制为假 + 返回失效
  原因——前端不再渲染任何按钮，绝不提供不可执行按钮；
- 本人才能登记/查看本人通知的撤销；他人 id 一律 404 同形。
"""

from typing import Any

from lumirss.new391_notifications import NotificationNotFound, _owned_row
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_REASON = 300


class RevocationInvalid(ValueError):
    """撤销载荷非法（422）。"""


def clean_reason(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RevocationInvalid("失效原因不能为空。")
    clean = value.strip()
    if len(clean) > _MAX_REASON:
        raise RevocationInvalid(f"失效原因最长 {_MAX_REASON} 字符。")
    return clean


async def register_revocation(
    db: Database,
    *,
    notification_id: str,
    user_id: str,
    reason: str,
) -> dict[str, Any]:
    """登记一条撤销事实（upsert：最新事实覆盖旧原因）。"""
    clean = clean_reason(reason)
    await db.migrate()
    row = await _owned_row(db, user_id, notification_id)
    now = utc_now()
    existing = await db.fetch_one(
        "SELECT notification_id FROM notification_action_revocations"
        " WHERE notification_id = ?",
        (int(row["id"]),),
    )
    if existing is None:
        await db.execute(
            "INSERT INTO notification_action_revocations"
            " (notification_id, user_id, reason, revoked_at) VALUES (?, ?, ?, ?)",
            (int(row["id"]), user_id, clean, now),
        )
    else:
        await db.execute(
            "UPDATE notification_action_revocations SET reason = ?, revoked_at = ?"
            " WHERE notification_id = ?",
            (clean, now, int(row["id"])),
        )
    return {
        "notificationId": str(row["id"]),
        "invalidReason": clean,
        "revokedAt": now,
    }


async def get_revocation(
    db: Database, *, notification_id: str, user_id: str
) -> dict[str, Any] | None:
    await db.migrate()
    try:
        row = await _owned_row(db, user_id, notification_id)
    except NotificationNotFound:
        return None
    found = await db.fetch_one(
        "SELECT notification_id, reason, revoked_at FROM"
        " notification_action_revocations WHERE notification_id = ? AND user_id = ?",
        (int(row["id"]), user_id),
    )
    if found is None:
        return None
    return {
        "notificationId": str(row["id"]),
        "invalidReason": str(found["reason"]),
        "revokedAt": str(found["revoked_at"]),
    }
