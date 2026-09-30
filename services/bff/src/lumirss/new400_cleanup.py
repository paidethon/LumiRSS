"""NEW-400 个人功能使用清理 —— 显式关闭 + 数据去留，绝不行为推断。

边界（硬规则）：

- 「启用中」的事实永远来自各功能自己的表（实时计数，不是快照）；
- 关闭只能是**本人显式动作**（POST close），本模块没有任何定时器、
  阈值或行为推断路径——自动关闭在本面不存在，这是契约不是疏忽；
- 数据去留由用户选择：
  * keep   —— 关开关（禁用/停用），数据保留，可随时回来重新启用；
  * delete —— 一并清除本人该模块的数据；
- 关闭动作落留痕表（谁、何时、选了什么），清单位置给用户与审计一个
  诚实回看点。
"""

from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

RETENTIONS = ("keep", "delete")


class ModuleUnknown(LookupError):
    """模块不在注册表里（404 同形）。"""


class CleanupInvalid(ValueError):
    """载荷非法（422）。"""


async def _enabled_count(db: Database, user_id: str, module_id: str) -> int:
    """实时计数：启用中的事实来自各功能自己的表。"""
    if module_id == "notification_aggregation":
        row = await db.fetch_one(
            "SELECT COUNT(*) AS n FROM notification_aggregation_rules"
            " WHERE user_id = ? AND enabled = 1",
            (user_id,),
        )
    elif module_id == "notification_quiet_hours":
        row = await db.fetch_one(
            "SELECT COUNT(*) AS n FROM notification_quiet_hours"
            " WHERE user_id = ? AND enabled = 1",
            (user_id,),
        )
    elif module_id == "interaction_modes":
        row = await db.fetch_one(
            "SELECT COUNT(*) AS n FROM interaction_mode_prefs WHERE user_id = ?",
            (user_id,),
        )
    elif module_id == "error_runbooks":
        row = await db.fetch_one(
            "SELECT COUNT(*) AS n FROM error_runbook_sessions"
            " WHERE user_id = ? AND status = 'open'",
            (user_id,),
        )
    else:
        raise ModuleUnknown("模块不存在。")
    return int(row["n"])


MODULE_SPECS = {
    "notification_aggregation": {
        "label": "通知聚合规则",
        "description": "同来源通知合并摘要；关闭后回到平铺视图。",
    },
    "notification_quiet_hours": {
        "label": "提醒静默时段",
        "description": "静默窗口与结束汇总；关闭后提醒随时呈现。",
    },
    "interaction_modes": {
        "label": "新功能回退偏好",
        "description": "新旧交互二选一的临时偏好；关闭即全部回到新交互。",
    },
    "error_runbooks": {
        "label": "错误自助处理单",
        "description": "逐步执行记录与求助材料；关闭并清除即删除处理单历史。",
    },
}


async def module_cleanup(db: Database, user_id: str) -> dict[str, Any]:
    await db.migrate()
    closures = {
        str(row["module_id"]): row
        for row in await db.fetch_all(
            "SELECT * FROM advanced_module_closures WHERE user_id = ?"
            " ORDER BY closed_at DESC, id DESC",
            (user_id,),
        )
    }
    modules: list[dict[str, Any]] = []
    for module_id, spec in MODULE_SPECS.items():
        count = await _enabled_count(db, user_id, module_id)
        closure_row = closures.get(module_id)
        modules.append(
            {
                "key": module_id,
                "label": str(spec["label"]),
                "description": str(spec["description"]),
                "enabledCount": count,
                "closure": (
                    {
                        "retention": str(closure_row["retention"]),
                        "detail": str(closure_row["detail"]),
                        "closedAt": str(closure_row["closed_at"]),
                    }
                    if closure_row is not None
                    else None
                ),
            }
        )
    return {
        "modules": modules,
        "note": "清理只由你本人关闭，绝不根据行为推断自动关闭；启用中的计数实时来自各功能自己的数据。",
    }


async def close_module(
    db: Database, user_id: str, *, module_id: str, retention: str
) -> dict[str, Any]:
    if module_id not in MODULE_SPECS:
        raise ModuleUnknown("模块不存在。")
    if retention not in RETENTIONS:
        raise CleanupInvalid("retention 必须是 keep 或 delete。")
    await db.migrate()
    detail = ""
    if module_id == "notification_aggregation":
        if retention == "keep":
            await db.execute(
                "UPDATE notification_aggregation_rules SET enabled = 0"
                " WHERE user_id = ?",
                (user_id,),
            )
            detail = "规则已停用，数据保留。"
        else:
            await db.execute(
                "DELETE FROM notification_aggregation_rules WHERE user_id = ?",
                (user_id,),
            )
            detail = "聚合规则已删除。"
    elif module_id == "notification_quiet_hours":
        if retention == "keep":
            await db.execute(
                "UPDATE notification_quiet_hours SET enabled = 0 WHERE user_id = ?",
                (user_id,),
            )
            detail = "静默时段已停用，设置保留。"
        else:
            await db.execute(
                "DELETE FROM notification_quiet_hours WHERE user_id = ?", (user_id,)
            )
            detail = "静默设置已删除。"
    elif module_id == "interaction_modes":
        if retention == "delete":
            await db.execute(
                "DELETE FROM interaction_mode_prefs WHERE user_id = ?", (user_id,)
            )
            detail = "回退偏好已删除，全部回到新交互。"
        else:
            detail = "偏好保留，可随时重新设置。"
    elif module_id == "error_runbooks":
        if retention == "delete":
            rows = await db.fetch_all(
                "SELECT id FROM error_runbook_sessions WHERE user_id = ?", (user_id,)
            )
            for row in rows:
                await db.execute(
                    "DELETE FROM error_runbook_steps WHERE session_id = ?",
                    (int(row["id"]),),
                )
            await db.execute(
                "DELETE FROM error_runbook_sessions WHERE user_id = ?", (user_id,)
            )
            detail = "处理单历史已删除。"
        else:
            detail = "处理单历史保留。"
    now = utc_now()
    new_id = await db.execute(
        "INSERT INTO advanced_module_closures (user_id, module_id, retention,"
        " detail, closed_at) VALUES (?, ?, ?, ?, ?)",
        (user_id, module_id, retention, detail, now),
    )
    return {
        "moduleId": module_id,
        "retention": retention,
        "detail": detail,
        "closedAt": now,
        "closureId": str(new_id),
    }
