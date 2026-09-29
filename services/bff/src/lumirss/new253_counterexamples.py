"""NEW-253 反例收集视图 —— 与现有结论冲突的原文证据，单独立项收集。

- 收集：excerpt（原文摘录）必填；item_ref 出处可选（先记证据、出处后补）；
- 处理：resolve 是显式动作——用户必须回答「结论是否调整」
  （conclusionAdjusted）并留 resolution_note；unhandled → handled；
- 边界：本表只记账反例与其处理说明；真正的结论调整走 NEW-259
  结论变更记录——本模块绝不代用户改结论。
"""

import uuid as _uuid
from typing import Any

from lumirss.new251_research import (
    ResearchInvalid,
    _clean,
    clean_item_ref,
    require_project,
)
from lumirss.util import utc_now

MAX_EXCERPT = 4000


class CounterexampleNotFound(Exception):
    """反例不存在（映射 404）。"""


class CounterexampleStore:
    def __init__(self, db: Any) -> None:
        self._db = db

    async def _row(self, counterexample_id: str) -> dict[str, Any]:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT * FROM research_counterexamples WHERE id = ?", (counterexample_id,)
        )
        if row is None:
            raise CounterexampleNotFound(counterexample_id)
        return dict(row)

    @staticmethod
    def _view(row: dict[str, Any]) -> dict[str, Any]:
        adjusted = row["conclusion_adjusted"]
        return {
            "id": str(row["id"]),
            "projectId": str(row["project_id"]),
            "excerpt": str(row["excerpt"]),
            "itemRef": row["item_ref"] if row["item_ref"] is None else str(row["item_ref"]),
            "note": row["note"] if row["note"] is None else str(row["note"]),
            "status": str(row["status"]),
            "resolutionNote": (
                row["resolution_note"] if row["resolution_note"] is None else str(row["resolution_note"])
            ),
            "conclusionAdjusted": None if adjusted is None else bool(adjusted),
            "resolvedAt": row["resolved_at"] if row["resolved_at"] is None else str(row["resolved_at"]),
            "createdAt": str(row["created_at"]),
        }

    async def create(
        self, project_id: str, *, excerpt: Any, item_ref: Any = None, note: Any = None
    ) -> dict[str, Any]:
        await require_project(self._db, project_id)
        clean_excerpt = _clean(excerpt, label="excerpt", max_len=MAX_EXCERPT)
        assert clean_excerpt is not None
        ref = clean_item_ref(item_ref)
        clean_note = _clean(note, label="note", max_len=1000, required=False)
        row_id = str(_uuid.uuid4())
        await self._db.execute(
            "INSERT INTO research_counterexamples (id, project_id, excerpt, item_ref, note, "
            "status, created_at) VALUES (?, ?, ?, ?, ?, 'unhandled', ?)",
            (row_id, project_id, clean_excerpt, ref, clean_note, utc_now()),
        )
        return self._view(await self._row(row_id))

    async def list(self, project_id: str, *, status: str | None = None) -> dict[str, Any]:
        await require_project(self._db, project_id)
        if status is not None and status not in ("unhandled", "handled"):
            raise ResearchInvalid("status 只能是 unhandled 或 handled。")
        if status is None:
            rows = await self._db.fetch_all(
                "SELECT id FROM research_counterexamples WHERE project_id = ? "
                "ORDER BY created_at DESC, rowid DESC",
                (project_id,),
            )
        else:
            rows = await self._db.fetch_all(
                "SELECT id FROM research_counterexamples WHERE project_id = ? AND status = ? "
                "ORDER BY created_at DESC, rowid DESC",
                (project_id, status),
            )
        items = [self._view(await self._row(str(row["id"]))) for row in rows]
        unhandled = sum(1 for item in items if item["status"] == "unhandled")
        return {
            "projectId": project_id,
            "unhandledCount": unhandled,
            "handledCount": len(items) - unhandled,
            "items": items,
        }

    async def resolve(
        self,
        counterexample_id: str,
        *,
        conclusion_adjusted: Any,
        resolution_note: Any,
    ) -> dict[str, Any]:
        row = await self._row(counterexample_id)
        if row["status"] == "handled":
            raise ResearchInvalid("该反例已处理过（handled 不能重复 resolve）。")
        if not isinstance(conclusion_adjusted, bool):
            raise ResearchInvalid("conclusionAdjusted 必须是布尔值（结论是否调整）。")
        clean_note = _clean(resolution_note, label="resolutionNote", max_len=2000)
        assert clean_note is not None
        now = utc_now()
        await self._db.execute(
            "UPDATE research_counterexamples SET status = 'handled', conclusion_adjusted = ?, "
            "resolution_note = ?, resolved_at = ? WHERE id = ?",
            (1 if conclusion_adjusted else 0, clean_note, now, counterexample_id),
        )
        return self._view(await self._row(counterexample_id))

    async def attach_source(self, counterexample_id: str, *, item_ref: Any) -> dict[str, Any]:
        """出处后补（创建时没有的，找到原文后挂上）。"""
        await self._row(counterexample_id)
        ref = clean_item_ref(item_ref)
        if ref is None:
            raise ResearchInvalid("itemRef 不能为空。")
        await self._db.execute(
            "UPDATE research_counterexamples SET item_ref = ? WHERE id = ?",
            (ref, counterexample_id),
        )
        return self._view(await self._row(counterexample_id))

    async def delete(self, counterexample_id: str) -> None:
        await self._row(counterexample_id)
        await self._db.execute(
            "DELETE FROM research_counterexamples WHERE id = ?", (counterexample_id,)
        )
