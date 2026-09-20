"""F005 来源备注与维护记录 —— Lumi 自有元数据（SQL 唯一入口）。

三字段均为自由文本：note（备注）、reason（订阅理由）、maintenance_log
（维护记录）。存原文（不消毒），渲染转义是 Web 层职责（React 默认
转义）；来源删除时级联删除（见 0037 迁移注释与 delete 路由）。
"""

from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

_UNSET = object()

_FIELDS = ("note", "reason", "maintenance_log")


class SourceNotesStore:
    """CRUD over source_notes（bounded table：每订阅至多一行）。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def get_notes(self, subscription_ref: str) -> dict[str, Any]:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT subscription_ref, note, reason, maintenance_log, updated_at FROM source_notes WHERE subscription_ref = ?",
            (subscription_ref,),
        )
        if row is None:
            return {
                "subscriptionRef": subscription_ref,
                "note": None,
                "reason": None,
                "maintenanceLog": None,
                "updatedAt": None,
            }
        return {
            "subscriptionRef": str(row["subscription_ref"]),
            "note": row["note"],
            "reason": row["reason"],
            "maintenanceLog": row["maintenance_log"],
            "updatedAt": str(row["updated_at"] or ""),
        }

    async def update_notes(
        self,
        subscription_ref: str,
        *,
        note: Any = _UNSET,
        reason: Any = _UNSET,
        maintenance_log: Any = _UNSET,
    ) -> dict[str, Any]:
        """sentinel 语义：缺席 = 不修改；None = 清空；字符串 = 覆盖原文。"""
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT note, reason, maintenance_log FROM source_notes WHERE subscription_ref = ?",
            (subscription_ref,),
        )
        current_note = row["note"] if row is not None else None
        current_reason = row["reason"] if row is not None else None
        current_log = row["maintenance_log"] if row is not None else None
        await self._db.execute(
            "INSERT INTO source_notes (subscription_ref, note, reason, maintenance_log, updated_at) VALUES (?, ?, ?, ?, ?) ON CONFLICT(subscription_ref) DO UPDATE SET note = excluded.note, reason = excluded.reason, maintenance_log = excluded.maintenance_log, updated_at = excluded.updated_at",
            (
                subscription_ref,
                current_note if note is _UNSET else _text_or_none(note),
                current_reason if reason is _UNSET else _text_or_none(reason),
                current_log if maintenance_log is _UNSET else _text_or_none(maintenance_log),
                utc_now(),
            ),
        )
        return await self.get_notes(subscription_ref)

    async def search_notes(self, needle: str | None = None) -> list[dict[str, Any]]:
        """列表（可选关键词过滤；LIKE 转义由参数化承担，语义为子串匹配）。"""
        await self._db.migrate()
        if needle is None or needle.strip() == "":
            rows = await self._db.fetch_all(
                "SELECT subscription_ref, note, reason, maintenance_log, updated_at FROM source_notes ORDER BY updated_at DESC"
            )
        else:
            pattern = f"%{needle.strip()}%"
            rows = await self._db.fetch_all(
                "SELECT subscription_ref, note, reason, maintenance_log, updated_at FROM source_notes WHERE note LIKE ? OR reason LIKE ? OR maintenance_log LIKE ? ORDER BY updated_at DESC",
                (pattern, pattern, pattern),
            )
        return [
            {
                "subscriptionRef": str(row["subscription_ref"]),
                "note": row["note"],
                "reason": row["reason"],
                "maintenanceLog": row["maintenance_log"],
                "updatedAt": str(row["updated_at"] or ""),
            }
            for row in rows
        ]

    async def delete_notes(self, subscription_ref: str) -> None:
        await self._db.migrate()
        await self._db.execute(
            "DELETE FROM source_notes WHERE subscription_ref = ?",
            (subscription_ref,),
        )


def _text_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text[:20000]  # 有界：超长备注截断（诚实有界，非无限存储）
