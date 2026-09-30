"""NEW-392 通知聚合规则 —— 用户自选的同来源合并摘要。

边界（硬规则）：

- 规则只改变**展示**：每个原始事件（0314）仍完整存在，摘要展开就是
  逐条事件列表（含撤销联判）——聚合绝不合并、隐藏或删除原始行；
- 规则由用户显式创建（kind + source 二元组，同一对至多一条），禁用
  即回到平铺视图，删除同理；没有任何自动聚合；
- source 是登记事件时的来源串（域收尾给定），聚合按精确相等匹配，
  不做模糊猜测。
"""

from typing import Any

from lumirss.new391_notifications import (
    KINDS,
    MAX_SOURCE,
    NotificationInvalid,
    _revocation_map,
    _to_dto,
)
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_RULES = 50
_MAX_LABEL = 120


class RuleConflict(Exception):
    """同 (kind, source) 已有规则（409 同形）。"""


class RuleNotFound(Exception):
    """规则不存在或不属于调用者（404 同形）。"""


async def _owned_rule_row(db: Database, user_id: str, rule_id: str) -> Any:
    try:
        numeric = int(str(rule_id))
    except ValueError as exc:
        raise RuleNotFound("没有这条规则。") from exc
    row = await db.fetch_one(
        "SELECT * FROM notification_aggregation_rules WHERE id = ? AND user_id = ?",
        (numeric, user_id),
    )
    if row is None:
        raise RuleNotFound("没有这条规则。")
    return row


def _clean_text(value: Any, field: str, limit: int, *, required: bool = True) -> str:
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


async def list_rules(db: Database, user_id: str) -> dict[str, Any]:
    await db.migrate()
    rows = await db.fetch_all(
        "SELECT * FROM notification_aggregation_rules WHERE user_id = ?"
        " ORDER BY created_at DESC, id DESC",
        (user_id,),
    )
    return {
        "rules": [
            {
                "id": str(row["id"]),
                "kind": str(row["kind"]),
                "source": str(row["source"]),
                "label": str(row["label"]),
                "enabled": bool(row["enabled"]),
                "createdAt": str(row["created_at"]),
            }
            for row in rows
        ]
    }


async def create_rule(
    db: Database, user_id: str, *, kind: str, source: str, label: str = ""
) -> dict[str, Any]:
    if kind not in KINDS:
        raise NotificationInvalid(f"未知通知类型：{kind}。")
    clean_source = _clean_text(source, "来源", MAX_SOURCE)
    clean_label = _clean_text(label, "标签", _MAX_LABEL, required=False)
    await db.migrate()
    count_row = await db.fetch_one(
        "SELECT COUNT(*) AS n FROM notification_aggregation_rules WHERE user_id = ?",
        (user_id,),
    )
    if int(count_row["n"]) >= _MAX_RULES:
        raise NotificationInvalid(f"聚合规则最多 {_MAX_RULES} 条。")
    dup = await db.fetch_one(
        "SELECT id FROM notification_aggregation_rules"
        " WHERE user_id = ? AND kind = ? AND source = ?",
        (user_id, kind, clean_source),
    )
    if dup is not None:
        raise RuleConflict("同一来源同类型已有规则。")
    now = utc_now()
    new_id = await db.execute(
        "INSERT INTO notification_aggregation_rules"
        " (user_id, kind, source, label, enabled, created_at)"
        " VALUES (?, ?, ?, ?, 1, ?)",
        (user_id, kind, clean_source, clean_label, now),
    )
    return {
        "id": str(new_id),
        "kind": kind,
        "source": clean_source,
        "label": clean_label,
        "enabled": True,
        "createdAt": now,
    }


async def set_rule_enabled(
    db: Database, user_id: str, rule_id: str, *, enabled: bool
) -> dict[str, Any] | None:
    await db.migrate()
    rule = await _owned_rule_row(db, user_id, rule_id)
    if rule is None:
        return None
    await db.execute(
        "UPDATE notification_aggregation_rules SET enabled = ? WHERE id = ?",
        (1 if enabled else 0, rule["id"]),
    )
    return await _rule_dto(db, rule["id"])


async def delete_rule(db: Database, user_id: str, rule_id: str) -> bool:
    await db.migrate()
    rule = await _owned_rule_row(db, user_id, rule_id)
    if rule is None:
        return False
    await db.execute(
        "DELETE FROM notification_aggregation_rules WHERE id = ?", (rule["id"],)
    )
    return True


async def _rule_dto(db: Database, rule_id: int) -> dict[str, Any]:
    row = await db.fetch_one(
        "SELECT * FROM notification_aggregation_rules WHERE id = ?", (rule_id,)
    )
    assert row is not None
    return {
        "id": str(row["id"]),
        "kind": str(row["kind"]),
        "source": str(row["source"]),
        "label": str(row["label"]),
        "enabled": bool(row["enabled"]),
        "createdAt": str(row["created_at"]),
    }


async def grouped_view(db: Database, user_id: str) -> dict[str, Any]:
    """聚合摘要 + 未命中规则的平铺部分；每组可展开逐条原始事件。"""
    await db.migrate()
    rules = await db.fetch_all(
        "SELECT * FROM notification_aggregation_rules"
        " WHERE user_id = ? AND enabled = 1",
        (user_id,),
    )
    revocations = await _revocation_map(db, user_id)
    events = await db.fetch_all(
        "SELECT * FROM user_notifications WHERE user_id = ?"
        " ORDER BY occurred_at DESC, id DESC",
        (user_id,),
    )
    matched_keys = {(str(rule["kind"]), str(rule["source"])) for rule in rules}
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    flat: list[dict[str, Any]] = []
    for row in events:
        dto = _to_dto(row, revocations.get(int(row["id"])))
        key = (str(row["kind"]), str(row["source"]))
        if key in matched_keys:
            group = groups.setdefault(
                key,
                {
                    "kind": key[0],
                    "source": key[1],
                    "total": 0,
                    "unread": 0,
                    "items": [],
                },
            )
            group["total"] += 1
            if row["read_at"] is None:
                group["unread"] += 1
            group["items"].append(dto)
        else:
            flat.append(dto)
    return {
        "groups": sorted(
            groups.values(), key=lambda group: (-group["unread"], -group["total"])
        ),
        "flat": flat,
        "ruleCount": len(rules),
    }
