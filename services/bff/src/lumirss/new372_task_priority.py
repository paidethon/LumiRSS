"""NEW-372 任务优先级调整 —— 后台逐账户清扫顺序的显式优先级。

Lumi 的实例级后台面（搜索投影同步等）按账户逐个执行；当多账户同
 tick 待执行时，执行顺序此前是账户列举顺序。本模块把顺序变成显式
治理对象：

- 每账户一行优先级（1 低 / 2 普通 / 3 高；无行 = 普通），行在
  control 库、主语只能是「该账户自己的后台清扫槽位」；
- **已运行任务不被无条件打断**：执行点在 main.py 的清扫循环——
  每轮 tick 开始取一次顺序快照（:func:`background_sweep_order` 返回
  新列表），本轮内不再读取；优先级变更只影响下一轮。本模块没有、
  也绝不添加任何取消/抢占代码路径；
- **普通用户仅能操作自己的任务**：member 路由固定以会话身份为主语
  （不存在带 user_id 的 member 写入口）；管理员可调整任何账户。

全部 SQL 内联字面量 + 绑定参数；写站点集中（set_priority /
clear_priority 两处，事务内 SELECT-then-INSERT/UPDATE）。
"""

from typing import Any

from lumirss.db_tx import transaction
from lumirss.util import utc_now

PRIORITY_LEVELS: dict[str, int] = {"low": 1, "normal": 2, "high": 3}
LEVEL_LABELS: dict[int, str] = {1: "低", 2: "普通", 3: "高"}
_DEFAULT_PRIORITY = 2


class PriorityInvalid(ValueError):
    """优先级载荷非法（422）。"""


class PriorityTargetUnknown(Exception):
    """目标账户不存在（404）。"""


def clean_level(raw: Any) -> int:
    if isinstance(raw, str):
        level = PRIORITY_LEVELS.get(raw.strip().lower())
    elif isinstance(raw, int) and not isinstance(raw, bool):
        level = raw
    else:
        level = None
    if level not in PRIORITY_LEVELS.values():
        raise PriorityInvalid("priority 必须是 low/normal/high（或 1..3）。")
    return int(level)


async def set_priority(
    control_db: Any, *, user_id: str, level: Any, updated_by: str
) -> dict[str, Any]:
    value = clean_level(level)
    await control_db.migrate()

    def _write(conn: Any) -> dict[str, Any]:
        row = conn.execute(
            "SELECT priority FROM admin_task_priorities WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO admin_task_priorities (user_id, priority, updated_by, updated_at)"
                " VALUES (?, ?, ?, ?)",
                (user_id, value, updated_by, utc_now()),
            )
        else:
            conn.execute(
                "UPDATE admin_task_priorities SET priority = ?, updated_by = ?, updated_at = ?"
                " WHERE user_id = ?",
                (value, updated_by, utc_now(), user_id),
            )
        return {
            "userId": user_id,
            "priority": value,
            "priorityLabel": LEVEL_LABELS[value],
            "appliesAt": "next_sweep",
            "preemption": False,
        }

    return await transaction(control_db, _write)


async def clear_priority(control_db: Any, *, user_id: str, updated_by: str) -> bool:
    await control_db.migrate()

    def _write(conn: Any) -> bool:
        row = conn.execute(
            "SELECT priority FROM admin_task_priorities WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            return False
        conn.execute("DELETE FROM admin_task_priorities WHERE user_id = ?", (user_id,))
        return True

    return bool(await transaction(control_db, _write))


async def get_priority(control_db: Any, user_id: str) -> dict[str, Any]:
    await control_db.migrate()
    row = await control_db.fetch_one(
        "SELECT priority, updated_at, updated_by FROM admin_task_priorities WHERE user_id = ?",
        (user_id,),
    )
    if row is None:
        return {
            "userId": user_id,
            "priority": _DEFAULT_PRIORITY,
            "priorityLabel": LEVEL_LABELS[_DEFAULT_PRIORITY],
            "updatedAt": None,
            "updatedBy": None,
            "default": True,
        }
    value = int(row["priority"])
    return {
        "userId": user_id,
        "priority": value,
        "priorityLabel": LEVEL_LABELS.get(value, str(value)),
        "updatedAt": row["updated_at"],
        "updatedBy": row["updated_by"],
        "default": False,
    }


async def background_sweep_order(control_db: Any, active_ids: list[str]) -> list[str]:
    """main.py 清扫循环的顺序快照（新列表；循环内不再读取注册表）。

    优先级降序优先，同层与未登记账户保持原有列举顺序（稳定排序）。
    control 库读失败时按原序返回——治理面故障绝不能弄停后台清扫。"""
    if not active_ids:
        return []
    try:
        await control_db.migrate()
        rows = await control_db.fetch_all(
            "SELECT user_id, priority FROM admin_task_priorities", ()
        )
    except Exception:  # noqa: BLE001 — 顺序是优化，不是正确性依赖
        return list(active_ids)
    weights = {str(row["user_id"]): int(row["priority"]) for row in rows}
    return sorted(
        active_ids,
        key=lambda uid: -weights.get(uid, _DEFAULT_PRIORITY),
    )


async def list_priorities(control_db: Any) -> list[dict[str, Any]]:
    await control_db.migrate()
    rows = await control_db.fetch_all(
        "SELECT p.user_id, p.priority, p.updated_at, p.updated_by, u.username"
        " FROM admin_task_priorities p LEFT JOIN users u ON u.id = p.user_id"
        " ORDER BY p.priority DESC, p.updated_at DESC",
        (),
    )
    return [
        {
            "userId": str(row["user_id"]),
            "username": str(row["username"]) if row["username"] else None,
            "priority": int(row["priority"]),
            "priorityLabel": LEVEL_LABELS.get(int(row["priority"]), str(row["priority"])),
            "updatedAt": row["updated_at"],
            "updatedBy": row["updated_by"],
        }
        for row in rows
    ]
