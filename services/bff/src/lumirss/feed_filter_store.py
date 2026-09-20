"""F045 服务端屏蔽规则 —— feed_filter_rules CRUD + SQL 谓词编译。

规则按 feed 维度存储；entries 列表在 BFF 层应用（每条被屏蔽项可携带
命中的规则）。SQL 谓词编译供计数与试跑复用：多规则 OR 连接，
value 中 ``%``/``_``/``\\`` 转义（escape '\\'），contains → LIKE，
equals → ``=``。只影响 Lumi 时间线视图，FreshRSS 已读/收藏不动。

约束（应用层限额）：每来源 ≤20 条、value ≤200 字符。
"""

import sqlite3
import uuid as _uuid
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

MAX_RULES_PER_FEED = 20
MAX_VALUE_LENGTH = 200
_FIELDS = ("title", "author")
_OPS = ("contains", "equals")


class FilterRuleInvalid(ValueError):
    """规则负载未通过校验。"""


class FilterRuleLimit(Exception):
    """每来源规则数超上限（路由层映射 422）。"""


def validate_rule_payload(*, field: Any, op: Any, value: Any) -> tuple[str, str, str]:
    if field not in _FIELDS:
        raise FilterRuleInvalid("field 必须是 title 或 author。")
    if op not in _OPS:
        raise FilterRuleInvalid("op 必须是 contains 或 equals。")
    if not isinstance(value, str) or not value.strip():
        raise FilterRuleInvalid("value 不能为空。")
    clean = value.strip()
    if len(clean) > MAX_VALUE_LENGTH:
        raise FilterRuleInvalid(f"value 过长（≤{MAX_VALUE_LENGTH} 字符）。")
    return field, op, clean


def compile_rules_to_sql(rules: list[dict[str, Any]]) -> tuple[str, list[str]]:
    """多规则 OR 连接的 SQL 谓词 + 绑定参数（value 已转义 ``%``/``_``/``\\``）。

    title 列与 author 列由调用方绑定（列名通过占位符注入参数化查询，
    防注入面收敛到 value 本身）。"""
    clauses: list[str] = []
    params: list[str] = []
    for rule in rules:
        if not rule.get("enabled"):
            continue
        escaped = (
            str(rule["value"])
            .replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        column = "title" if rule["field"] == "title" else "author"
        if rule["op"] == "contains":
            clauses.append(f"({column} LIKE ? ESCAPE '\\' )")
            params.append(f"%{escaped}%")
        else:
            clauses.append(f"({column} = ?)")
            params.append(str(rule["value"]))
    predicate = " OR ".join(clauses) if clauses else "0"
    return predicate, params


def first_matching_rule(
    rules: list[dict[str, Any]], *, title: str | None, author: str | None
) -> dict[str, Any] | None:
    """首条命中规则（创建顺序即优先级；enabled 才参与）。"""
    for rule in rules:
        if not rule.get("enabled"):
            continue
        value = str(rule["value"])
        target = title if rule["field"] == "title" else author
        target_text = str(target) if target is not None else ""
        if rule["op"] == "contains":
            if value in target_text:
                return rule
        elif target_text == value:
            return rule
    return None


class FeedFilterRuleStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def list_rules(self, feed_url: str | None = None) -> list[dict[str, Any]]:
        await self._db.migrate()
        if feed_url is None:
            rows = await self._db.fetch_all(
                "SELECT id, feed_url, field, op, value, enabled, created_at FROM feed_filter_rules ORDER BY created_at ASC, rowid ASC"
            )
        else:
            rows = await self._db.fetch_all(
                "SELECT id, feed_url, field, op, value, enabled, created_at FROM feed_filter_rules WHERE feed_url = ? ORDER BY created_at ASC, rowid ASC",
                (feed_url,),
            )
        return [_row_to_dict(row) for row in rows]

    async def create_rule(
        self, *, feed_url: str, field: str, op: str, value: str, enabled: bool = True
    ) -> dict[str, Any]:
        await self._db.migrate()
        field, op, value = validate_rule_payload(field=field, op=op, value=value)
        if not isinstance(feed_url, str) or not feed_url.strip():
            raise FilterRuleInvalid("feedUrl 不能为空。")
        feed_url = feed_url.strip()
        rules = await self.list_rules(feed_url)
        if len(rules) >= MAX_RULES_PER_FEED:
            raise FilterRuleLimit(f"每来源最多 {MAX_RULES_PER_FEED} 条规则。")
        rule_id = str(_uuid.uuid4())
        await self._db.execute(
            "INSERT INTO feed_filter_rules (id, feed_url, field, op, value, enabled, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (rule_id, feed_url, field, op, value, 1 if enabled else 0, utc_now()),
        )
        return (await self.get_rule(rule_id))  # type: ignore[return-value]

    async def get_rule(self, rule_id: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, feed_url, field, op, value, enabled, created_at FROM feed_filter_rules WHERE id = ?",
            (rule_id,),
        )
        return _row_to_dict(row) if row is not None else None

    async def update_rule(
        self, rule_id: str, *, enabled: bool | None = None
    ) -> dict[str, Any] | None:
        await self._db.migrate()
        current = await self.get_rule(rule_id)
        if current is None:
            return None
        await self._db.execute(
            "UPDATE feed_filter_rules SET enabled = ? WHERE id = ?",
            (current["enabled"] if enabled is None else enabled, rule_id),
        )
        return await self.get_rule(rule_id)

    async def delete_rule(self, rule_id: str) -> bool:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id FROM feed_filter_rules WHERE id = ?", (rule_id,)
        )
        if row is None:
            return False
        await self._db.execute("DELETE FROM feed_filter_rules WHERE id = ?", (rule_id,))
        return True


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "feedUrl": str(row["feed_url"]),
        "field": str(row["field"]),
        "op": str(row["op"]),
        "value": str(row["value"]),
        "enabled": bool(row["enabled"]),
        "createdAt": str(row["created_at"]),
    }
