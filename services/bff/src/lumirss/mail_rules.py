"""F105 邮件桥接接收规则 —— SQL 唯一入口。

每列表一组规则：首条命中决定 allow/deny（无规则 = allow）。
- contains：casefold 子串（大小写不敏感、Unicode 友好）；
- equals：精确比较（区分大小写——规则书写者显式要求）；
- 空 value → ValueError（路由映射 422）；
- 顺序 = priority（升序），move_rule 上下交换。

写站点 3 处（INSERT / UPDATE / DELETE）+ move 交换共用 UPDATE；
deny 计数在 mail_bridge_lists.skipped_count（bridge 侧写入）。
"""

from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

_FIELDS = ("from", "subject")
_OPS = ("contains", "equals")
_ACTIONS = ("allow", "deny")
_MAX_VALUE = 200
_MAX_RULES_PER_LIST = 50

_RULE_SELECT = "SELECT id, list_uuid, field, op, value, action, priority, enabled, created_at FROM mail_rules"


def rule_matches(rule: dict[str, Any], *, sender: str, subject: str) -> bool:
    """单条规则命中判定：contains casefold / equals 精确。"""
    field = str(rule["field"])
    sample = sender if field == "from" else subject
    value = str(rule["value"])
    if str(rule["op"]) == "equals":
        return sample == value
    return value.casefold() in sample.casefold()


def first_matching_rule(
    rules: list[dict[str, Any]], *, sender: str, subject: str
) -> dict[str, Any] | None:
    """首条命中（列表已按 priority 排序）；无命中 → None（= allow）。"""
    for rule in rules:
        if rule.get("enabled", 1) and rule_matches(
            rule, sender=sender, subject=subject
        ):
            return rule
    return None


class MailRuleStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def list_rules(
        self, list_uuid: str, *, enabled_only: bool = False
    ) -> list[dict[str, Any]]:
        await self._db.migrate()
        where = "WHERE list_uuid = ?" + (" AND enabled = 1" if enabled_only else "")
        rows = await self._db.fetch_all(
            f"{_RULE_SELECT} {where} ORDER BY priority ASC, id ASC",
            (list_uuid,),
        )
        return [self._row(r) for r in rows]

    async def all_rules(self) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(f"{_RULE_SELECT} ORDER BY list_uuid, priority ASC, id ASC", ())
        return [self._row(r) for r in rows]

    async def create_rule(
        self,
        *,
        list_uuid: str,
        field: str,
        op: str,
        value: str,
        action: str,
        enabled: bool = True,
    ) -> dict[str, Any]:
        await self._db.migrate()
        if field not in _FIELDS:
            raise ValueError("field 必须是 from 或 subject。")
        if op not in _OPS:
            raise ValueError("op 必须是 contains 或 equals。")
        if action not in _ACTIONS:
            raise ValueError("action 必须是 allow 或 deny。")
        clean = str(value).strip()
        if not clean:
            raise ValueError("value 不能为空。")
        clean = clean[:_MAX_VALUE]
        count = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM mail_rules WHERE list_uuid = ?",
            (list_uuid,),
        )
        if count is not None and int(count["n"]) >= _MAX_RULES_PER_LIST:
            raise ValueError(f"规则数量已达上限（{_MAX_RULES_PER_LIST}）。")
        priority = int(count["n"]) if count is not None else 0
        row_id = await self._db.execute(
            "INSERT INTO mail_rules (list_uuid, field, op, value, action, priority, enabled, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                list_uuid,
                field,
                op,
                clean,
                action,
                priority,
                1 if enabled else 0,
                utc_now(),
            ),
        )
        rule = await self.get_rule(int(row_id) if row_id else 0)
        assert rule is not None
        return rule

    async def get_rule(self, rule_id: int) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            f"{_RULE_SELECT} WHERE id = ?", (rule_id,)
        )
        return self._row(row) if row is not None else None

    async def update_rule(self, rule_id: int, patch: dict[str, Any]) -> dict[str, Any] | None:
        current = await self.get_rule(rule_id)
        if current is None:
            return None
        field = patch.get("field", current["field"])
        if field not in _FIELDS:
            raise ValueError("field 必须是 from 或 subject。")
        op = patch.get("op", current["op"])
        if op not in _OPS:
            raise ValueError("op 必须是 contains 或 equals。")
        action = patch.get("action", current["action"])
        if action not in _ACTIONS:
            raise ValueError("action 必须是 allow 或 deny。")
        value = str(patch.get("value", current["value"])).strip()
        if not value:
            raise ValueError("value 不能为空。")
        value = value[:_MAX_VALUE]
        enabled = 1 if patch.get("enabled", current["enabled"]) else 0
        await self._db.execute(
            "UPDATE mail_rules SET field = ?, op = ?, value = ?, action = ?, enabled = ? WHERE id = ?",
            (field, op, value, action, enabled, rule_id),
        )
        return await self.get_rule(rule_id)

    async def delete_rule(self, rule_id: int) -> bool:
        await self._db.migrate()
        if await self.get_rule(rule_id) is None:
            return False
        await self._db.execute("DELETE FROM mail_rules WHERE id = ?", (rule_id,))
        return True

    async def move_rule(self, rule_id: int, direction: str) -> dict[str, Any] | None:
        """与相邻规则交换 priority（应用顺序 = 列表顺序）。"""
        rule = await self.get_rule(rule_id)
        if rule is None:
            return None
        siblings = await self.list_rules(str(rule["listUuid"]))
        ids = [int(r["id"]) for r in siblings]
        index = ids.index(rule_id)
        swap_with = index - 1 if direction == "up" else index + 1
        if swap_with < 0 or swap_with >= len(ids):
            return rule  # 已在边界：原样返回
        other_id = ids[swap_with]
        await self._db.execute_many(
            "UPDATE mail_rules SET priority = ? WHERE id = ?",
            [(swap_with, rule_id), (index, other_id)],
        )
        return await self.get_rule(rule_id)

    def _row(self, row: Any) -> dict[str, Any]:
        return {
            "id": int(row["id"]),
            "listUuid": str(row["list_uuid"]),
            "field": str(row["field"]),
            "op": str(row["op"]),
            "value": str(row["value"]),
            "action": str(row["action"]),
            "priority": int(row["priority"]),
            "enabled": bool(row["enabled"]),
            "createdAt": str(row["created_at"] or ""),
        }
