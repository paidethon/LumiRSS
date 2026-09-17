"""F33 设置变更历史 —— 记录/查看/取单条（SQL 唯一入口）。

- 只记录 portable 设置（设计上不含任何密钥，见 app_settings 模型）；
- diff 只含实际变化的键：{"key": {"before": x, "after": y}}；
- 容量上限：只保留最近 20 条（插入时裁剪旧行）；
- 回退在路由层实现（复用既有校验 + 冲突跳过），本模块只管存取。
"""

import json
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

_HISTORY_LIMIT = 20


def compute_diff(
    before: dict[str, Any], after: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    """只含实际变化键的差异（schemaVersion 永不参与）。"""
    diff: dict[str, dict[str, Any]] = {}
    for key in after:
        if key == "schemaVersion":
            continue
        if key not in before or before[key] != after[key]:
            diff[key] = {"before": before.get(key), "after": after[key]}
    return diff


class SettingsHistoryStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def record(self, action: str, diff: dict[str, dict[str, Any]]) -> int | None:
        """记录一次变更（空 diff 不记录）；返回行 id 或 None。"""
        if not diff:
            return None
        await self._db.migrate()
        result = await self._db.execute(
            "INSERT INTO settings_history (changed_at, action, diff_json) VALUES (?, ?, ?)",
            (utc_now(), action, json.dumps(diff, ensure_ascii=False)),
        )
        await self._db.execute(
            "DELETE FROM settings_history WHERE id NOT IN (SELECT id FROM settings_history ORDER BY id DESC LIMIT 20)"
        )
        return result

    async def list_history(self, limit: int = 10) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, changed_at, action, diff_json FROM settings_history ORDER BY id DESC LIMIT ?",
            (max(1, min(limit, 20)),),
        )
        items: list[dict[str, Any]] = []
        for row in rows:
            try:
                diff = json.loads(str(row["diff_json"] or "{}"))
            except ValueError:
                diff = {}
            items.append(
                {
                    "id": int(row["id"]),
                    "changedAt": str(row["changed_at"]),
                    "action": str(row["action"]),
                    "diff": diff,
                }
            )
        return items

    async def get_entry(self, history_id: int) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, changed_at, action, diff_json FROM settings_history WHERE id = ?",
            (history_id,),
        )
        if row is None:
            return None
        try:
            diff = json.loads(str(row["diff_json"] or "{}"))
        except ValueError:
            diff = {}
        return {
            "id": int(row["id"]),
            "changedAt": str(row["changed_at"]),
            "action": str(row["action"]),
            "diff": diff,
        }
