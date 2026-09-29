"""NEW-373 维护通知演练 —— 不进入维护就能预演各角色会看到什么。

状态机（诚实边界写在每个分支里）：

- **演练**（POST drill）：持久化一条 drill，preview 列保存各角色
  （owner / admin / member / visitor）用**与真实窗口完全相同的渲染
  函数**（:func:`render_notice`）得到的通知。演练绝不创建窗口、
  绝不进入维护状态；
- **排程**（POST windows，step-up）：确认后才落一条 scheduled 窗口
  行。行在 [starts_at, ends_at) 区间内被
  GET /api/v1/maintenance/notice 如实呈现给全体用户——这是唯一
  消费点，没有其他模块被改动；
- **收尾**（complete / cancel）：set 语义状态机
  scheduled → completed | cancelled，行永不删除；重复收尾 → 409
  （状态陈旧的信号，如实报告，不是幂等 204）。

时间校验：RFC3339 可解析、start < end；测试一律用
``datetime.now(UTC) -/+ timedelta`` 构造，无固定日历日期。
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from lumirss.db_tx import transaction
from lumirss.util import utc_now

MAX_TITLE = 120
MAX_NOTICE = 1000

ROLES = ("owner", "admin", "member", "visitor")

_ROLE_NOTES: dict[str, str] = {
    "owner": "维护窗口由你（运营者）排程；窗口内你会与成员看到同一横幅。",
    "admin": "管理台在窗口内同样只读维护提示；排程入口属于运营者/管理员。",
    "member": "窗口内阅读通常不受影响（FreshRSS 照常服务）；新写入类操作可能被拒，横幅会如实说明。",
    "visitor": "未登录访客在登录页看到同源横幅（notice 文案原样，无实例内部细节）。",
}


class MaintenanceInvalid(ValueError):
    """载荷非法（422）。"""


class WindowNotFound(Exception):
    """窗口不存在（404）。"""


class WindowAlreadySettled(Exception):
    """窗口已收尾，再次收尾（409）。"""


def parse_utc(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MaintenanceInvalid(f"{field} 必须是 RFC3339 时刻。")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise MaintenanceInvalid(f"{field} 无法解析为时刻。") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat(timespec="seconds")


def clean_window_fields(title: Any, notice: Any, starts_at: Any, ends_at: Any) -> dict[str, str]:
    if not isinstance(title, str) or not title.strip():
        raise MaintenanceInvalid("title 必须是非空字符串。")
    if not isinstance(notice, str) or not notice.strip():
        raise MaintenanceInvalid("notice 必须是非空字符串。")
    title = title.strip()
    notice = notice.strip()
    if len(title) > MAX_TITLE:
        raise MaintenanceInvalid(f"title 最长 {MAX_TITLE} 字。")
    if len(notice) > MAX_NOTICE:
        raise MaintenanceInvalid(f"notice 最长 {MAX_NOTICE} 字。")
    start = parse_utc(starts_at, "startsAt")
    end = parse_utc(ends_at, "endsAt")
    if start >= end:
        raise MaintenanceInvalid("startsAt 必须早于 endsAt。")
    return {"title": title, "notice": notice, "startsAt": start, "endsAt": end}


def render_notice(role: str, *, title: str, notice: str, starts_at: str, ends_at: str) -> dict[str, Any]:
    """演练与真实窗口共用的唯一渲染口径（演练即对现实的预演）。"""
    return {
        "role": role,
        "banner": {"title": title, "notice": notice, "startsAt": starts_at, "endsAt": ends_at},
        "roleNote": _ROLE_NOTES.get(role, _ROLE_NOTES["member"]),
    }


def _window_payload(window: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": window["id"],
        "title": window["title"],
        "notice": window["notice"],
        "startsAt": window["starts_at"],
        "endsAt": window["ends_at"],
        "status": window["status"],
        "createdBy": window["created_by"],
        "createdAt": window["created_at"],
    }


async def create_drill(
    control_db: Any, *, fields: dict[str, str], by: str
) -> dict[str, Any]:
    await control_db.migrate()
    drill_id = uuid.uuid4().hex
    preview = {
        role: render_notice(role, **{
            "title": fields["title"],
            "notice": fields["notice"],
            "starts_at": fields["startsAt"],
            "ends_at": fields["endsAt"],
        })
        for role in ROLES
    }
    import json

    await control_db.execute(
        "INSERT INTO admin_maintenance_drills (id, title, notice, starts_at, ends_at, preview, created_by, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            drill_id,
            fields["title"],
            fields["notice"],
            fields["startsAt"],
            fields["endsAt"],
            json.dumps(preview, ensure_ascii=False),
            by,
            utc_now(),
        ),
    )
    return {
        "drillId": drill_id,
        "scheduled": False,
        "scheduledNote": "这是演练：没有创建维护窗口，实例未进入维护状态。",
        "preview": preview,
    }


async def list_drills(control_db: Any, limit: int = 20) -> list[dict[str, Any]]:
    await control_db.migrate()
    rows = await control_db.fetch_all(
        "SELECT id, title, starts_at, ends_at, created_at FROM admin_maintenance_drills"
        " ORDER BY created_at DESC, id DESC LIMIT ?",
        (max(1, min(limit, 50)),),
    )
    return [
        {
            "drillId": str(row["id"]),
            "title": str(row["title"]),
            "startsAt": str(row["starts_at"]),
            "endsAt": str(row["ends_at"]),
            "createdAt": str(row["created_at"]),
        }
        for row in rows
    ]


async def schedule_window(
    control_db: Any, *, fields: dict[str, str], by: str
) -> dict[str, Any]:
    await control_db.migrate()
    window_id = uuid.uuid4().hex
    await control_db.execute(
        "INSERT INTO admin_maintenance_windows (id, title, notice, starts_at, ends_at, status, created_by, created_at)"
        " VALUES (?, ?, ?, ?, ?, 'scheduled', ?, ?)",
        (window_id, fields["title"], fields["notice"], fields["startsAt"], fields["endsAt"], by, utc_now()),
    )
    row = await control_db.fetch_one(
        "SELECT * FROM admin_maintenance_windows WHERE id = ?", (window_id,)
    )
    return _window_payload(dict(row) if row is not None else {})


async def settle_window(
    control_db: Any, *, window_id: str, status: str, by: str
) -> dict[str, Any]:
    if status not in ("completed", "cancelled"):
        raise MaintenanceInvalid("status 只能是 completed/cancelled。")
    await control_db.migrate()

    def _write(conn: Any) -> dict[str, Any]:
        row = conn.execute(
            "SELECT id, status FROM admin_maintenance_windows WHERE id = ?", (window_id,)
        ).fetchone()
        if row is None:
            raise WindowNotFound(window_id)
        if str(row["status"]) != "scheduled":
            raise WindowAlreadySettled(window_id)
        conn.execute(
            "UPDATE admin_maintenance_windows SET status = ?, settled_at = ?, settled_by = ? WHERE id = ?",
            (status, utc_now(), by, window_id),
        )
        return {"id": window_id, "status": status}

    return await transaction(control_db, _write)


async def list_windows(control_db: Any, limit: int = 20) -> list[dict[str, Any]]:
    await control_db.migrate()
    rows = await control_db.fetch_all(
        "SELECT * FROM admin_maintenance_windows ORDER BY starts_at DESC LIMIT ?",
        (max(1, min(limit, 50)),),
    )
    return [_window_payload(dict(row)) for row in rows]


async def active_window(control_db: Any, *, now: str | None = None) -> dict[str, Any]:
    """GET /api/v1/maintenance/notice 的口径：当前时刻落在区间内的
    scheduled 窗口（`now < ends_at` 且 `starts_at <= now`）；同时返回
    最近的下一场（预告，startsAt 在未来）。"""
    await control_db.migrate()
    moment = now or utc_now()
    row = await control_db.fetch_one(
        "SELECT * FROM admin_maintenance_windows"
        " WHERE status = 'scheduled' AND starts_at <= ? AND ? < ends_at"
        " ORDER BY starts_at ASC LIMIT 1",
        (moment, moment),
    )
    upcoming = await control_db.fetch_one(
        "SELECT * FROM admin_maintenance_windows"
        " WHERE status = 'scheduled' AND starts_at > ?"
        " ORDER BY starts_at ASC LIMIT 1",
        (moment,),
    )
    return {
        "active": row is not None,
        "current": _window_payload(dict(row)) if row is not None else None,
        "upcoming": _window_payload(dict(upcoming)) if upcoming is not None else None,
    }
