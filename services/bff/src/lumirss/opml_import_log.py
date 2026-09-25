"""N018 OPML 树对照导入 —— 撤销台账（cap 5；SQL 唯一入口）。

每次树对照 apply 记一行：新建的分类 label + 被移动的 feed
（原分类 → 新分类，含上游 stream id）。undo 按 id 读取一行执行
反向操作；每行至多撤销一次（undone_at 非 NULL 后拒绝）。

表保持 ≤5 行：插入后删除最旧的旧行（有界台账，不是历史审计）。
存 JSON 数组（分类名 / feed 移动记录），损坏 JSON 诚实降级为空
（undo 报告「无可撤销项」，绝不臆造移动目标）。
"""

import json
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

_LOG_CAP = 5


class OpmlImportLogNotFound(Exception):
    """台账行不存在——404 opml_import_log_not_found。"""


class OpmlImportLogUndone(Exception):
    """该行已撤销过——409 opml_import_already_undone（set 语义：不二次撤销）。"""


class OpmlImportLogStore:
    """CRUD over opml_import_log（bounded table：≤5 行）。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def record(
        self,
        *,
        created_category_labels: list[str],
        moved_feeds: list[dict[str, Any]],
    ) -> int:
        """追加一行并裁剪到 cap；返回新行 id。"""
        await self._db.migrate()
        created_payload = json.dumps(created_category_labels, ensure_ascii=False)
        moved_payload = json.dumps(moved_feeds, ensure_ascii=False)
        await self._db.execute(
            "INSERT INTO opml_import_log (imported_at, created_category_labels, moved_feeds) VALUES (?, ?, ?)",
            (utc_now(), created_payload, moved_payload),
        )
        row = await self._db.fetch_one("SELECT id FROM opml_import_log ORDER BY id DESC LIMIT 1")
        await self._db.execute(
            "DELETE FROM opml_import_log WHERE id NOT IN (SELECT id FROM opml_import_log ORDER BY id DESC LIMIT 5)"
        )
        return int(row["id"]) if row is not None else 0

    async def get(self, log_id: int) -> dict[str, Any]:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, imported_at, created_category_labels, moved_feeds, undone_at FROM opml_import_log WHERE id = ?",
            (log_id,),
        )
        if row is None:
            raise OpmlImportLogNotFound(f"OPML import log {log_id} not found.")
        return self._row_view(row)

    async def list_recent(self, limit: int = 5) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, imported_at, created_category_labels, moved_feeds, undone_at FROM opml_import_log ORDER BY id DESC LIMIT ?",
            (max(1, min(limit, _LOG_CAP)),),
        )
        return [self._row_view(row) for row in rows]

    async def mark_undone(self, log_id: int) -> None:
        """标记已撤销（set 语义；已撤销 → OpmlImportLogUndone）。"""
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT undone_at FROM opml_import_log WHERE id = ?",
            (log_id,),
        )
        if row is None:
            raise OpmlImportLogNotFound(f"OPML import log {log_id} not found.")
        if row["undone_at"]:
            raise OpmlImportLogUndone(f"OPML import log {log_id} is already undone.")
        await self._db.execute(
            "UPDATE opml_import_log SET undone_at = ? WHERE id = ?",
            (utc_now(), log_id),
        )

    @staticmethod
    def _row_view(row: Any) -> dict[str, Any]:
        def _load(raw: Any, fallback: Any) -> Any:
            try:
                parsed = json.loads(str(raw))
            except (ValueError, TypeError):
                return fallback
            return parsed if isinstance(parsed, list) else fallback

        return {
            "id": int(row["id"]),
            "importedAt": str(row["imported_at"] or ""),
            "createdCategoryLabels": _load(row["created_category_labels"], []),
            "movedFeeds": _load(row["moved_feeds"], []),
            "undoneAt": str(row["undone_at"]) if row["undone_at"] else None,
        }
