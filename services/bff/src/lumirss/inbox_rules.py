"""F022 收件箱归类规则 —— inbox_rules 的 SQL 唯一入口。

语义边界：

- 顺序 = priority 升序（同 priority 按 id），应用「第一条命中」；
- 只对新条目生效：ingest 返回 ``created`` 才应用（``exists`` = 重复
  投递同 GUID，不重复触发副作用）；不回溯改旧条目；
- dry-run 纯读，不落库；
- value 长度上限 200（畸形输入 422 由模型层 + 这里双重兜底）。
"""

from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_VALUE_CHARS = 200


class InboxRuleNotFound(Exception):
    """规则不存在（404）。"""


class InboxRuleInvalid(ValueError):
    """规则字段非法（422）。"""


def rule_matches(rule: dict[str, Any], *, field: str, value: str, source: str | None) -> bool:
    """一条规则是否命中给定样本（纯函数，dry-run 与 ingest 共用）。"""
    if not rule.get("enabled", True):
        return False
    if str(rule["field"]) != field:
        return False
    haystack = value if field == "title" else (source or value)
    target = str(rule["value"])
    operator = str(rule["operator"])
    if operator == "equals":
        return haystack == target
    return target.lower() in haystack.lower()


def first_matching_rule(
    rules: list[dict[str, Any]], *, field: str, value: str, source: str | None
) -> dict[str, Any] | None:
    """规则列表中第一条命中的（列表已按 priority 排序）。"""
    for rule in rules:
        if rule_matches(rule, field=field, value=value, source=source):
            return rule
    return None


def _validate_value(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise InboxRuleInvalid("value 不能为空。")
    clean = value.strip()
    if len(clean) > _MAX_VALUE_CHARS:
        raise InboxRuleInvalid(f"value 过长（最多 {_MAX_VALUE_CHARS} 字）。")
    return clean


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "priority": int(row["priority"]),
        "field": str(row["field"]),
        "operator": str(row["operator"]),
        "value": str(row["value"]),
        "targetWorkspaceId": str(row["target_workspace_id"]),
        "enabled": bool(row["enabled"]),
        "createdAt": str(row["created_at"]),
    }


_COLUMNS = "id, priority, field, operator, value, target_workspace_id, enabled, created_at"


class InboxRuleStore:
    """CRUD + 有序读取（内联 SQL + 绑定参数；写站点 ≤4）。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def list_rules(self) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            f"SELECT {_COLUMNS} FROM inbox_rules ORDER BY priority ASC, id ASC",
            (),
        )
        return [_row_to_dict(row) for row in rows]

    async def create_rule(
        self,
        *,
        field: str,
        operator: str,
        value: Any,
        target_workspace_id: str,
        enabled: bool,
        priority: int | None,
    ) -> dict[str, Any]:
        clean_value = _validate_value(value)
        await self._db.migrate()
        if priority is None:
            row = await self._db.fetch_one(
                "SELECT COALESCE(MAX(priority), -1) + 1 AS p FROM inbox_rules", ()
            )
            priority = int(row["p"]) if row is not None else 0
        new_id = await self._db.execute(
            "INSERT INTO inbox_rules (priority, field, operator, value, target_workspace_id, enabled, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                int(priority),
                field,
                operator,
                clean_value,
                target_workspace_id,
                1 if enabled else 0,
                utc_now(),
            ),
        )
        assert new_id is not None
        row = await self._db.fetch_one(
            f"SELECT {_COLUMNS} FROM inbox_rules WHERE id = ?", (new_id,)
        )
        assert row is not None
        return _row_to_dict(row)

    async def get_rule(self, priority: int) -> dict[str, Any] | None:
        """按 priority 精确取（create 的回读路径；同 priority 取最早）。"""
        await self._db.migrate()
        row = await self._db.fetch_one(
            f"SELECT {_COLUMNS} FROM inbox_rules WHERE priority = ? ORDER BY id ASC LIMIT 1",
            (priority,),
        )
        return _row_to_dict(row) if row is not None else None

    async def update_rule(self, rule_id: int, patch: dict[str, Any]) -> dict[str, Any] | None:
        exists = await self._db.fetch_one(
            "SELECT id FROM inbox_rules WHERE id = ?", (rule_id,)
        )
        if exists is None:
            return None
        assignments: list[str] = []
        params: list[Any] = []
        if "field" in patch and patch["field"] is not None:
            assignments.append("field = ?")
            params.append(str(patch["field"]))
        if "operator" in patch and patch["operator"] is not None:
            assignments.append("operator = ?")
            params.append(str(patch["operator"]))
        if "value" in patch and patch["value"] is not None:
            assignments.append("value = ?")
            params.append(_validate_value(patch["value"]))
        if "target_workspace_id" in patch and patch["target_workspace_id"] is not None:
            assignments.append("target_workspace_id = ?")
            params.append(str(patch["target_workspace_id"]))
        if "enabled" in patch and patch["enabled"] is not None:
            assignments.append("enabled = ?")
            params.append(1 if patch["enabled"] else 0)
        if assignments:
            params.append(rule_id)
            await self._db.execute(
                f"UPDATE inbox_rules SET {', '.join(assignments)} WHERE id = ?",
                tuple(params),
            )
        row = await self._db.fetch_one(
            f"SELECT {_COLUMNS} FROM inbox_rules WHERE id = ?", (rule_id,)
        )
        return _row_to_dict(row) if row is not None else None

    async def delete_rule(self, rule_id: int) -> bool:
        await self._db.migrate()
        exists = await self._db.fetch_one(
            "SELECT id FROM inbox_rules WHERE id = ?", (rule_id,)
        )
        if exists is None:
            return False
        await self._db.execute("DELETE FROM inbox_rules WHERE id = ?", (rule_id,))
        return True

    async def move_rule(self, rule_id: int, direction: str) -> dict[str, Any] | None:
        """上移/下移：与相邻规则交换 priority（排序 = 应用顺序）。"""
        rules = await self.list_rules()
        index = next(
            (i for i, rule in enumerate(rules) if rule["id"] == rule_id), None
        )
        if index is None:
            return None
        swap_index = index - 1 if direction == "up" else index + 1
        if swap_index < 0 or swap_index >= len(rules):
            return rules[index]
        await self._db.execute(
            "UPDATE inbox_rules SET priority = ? WHERE id = ?",
            (rules[swap_index]["priority"], rule_id),
        )
        await self._db.execute(
            "UPDATE inbox_rules SET priority = ? WHERE id = ?",
            (rules[index]["priority"], rules[swap_index]["id"]),
        )
        return await self.get_rule(rules[swap_index]["priority"])
