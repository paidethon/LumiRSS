"""NEW-259 结论变更记录 —— 修改项目结论时保留原结论、触发材料与新表述。

- 当前结论：research_conclusions（每项目一行）；
- 变更台账：research_conclusion_history 只追加——每次修改整行记录
  old_text（原结论）/ new_text（新表述）/ trigger_refs（触发材料
  ItemRef JSON 数组）/ reason；没有 UPDATE / DELETE 路径，历史永不
  被覆盖（本组诚实边界的核心要求）；
- 首次登记结论也进台账：old_text = NULL 诚实表示「此前未登记过结论」，
  绝不伪造一条「空结论 → 新结论」的假变更。
"""

import json
import uuid as _uuid
from typing import Any

from lumirss.new251_research import (
    ResearchInvalid,
    _clean,
    clean_item_ref,
    require_project,
)
from lumirss.util import utc_now

MAX_CONCLUSION = 4000
MAX_REASON = 1000
MAX_TRIGGER_REFS = 50


class ConclusionStore:
    def __init__(self, db: Any) -> None:
        self._db = db

    async def _current_row(self, project_id: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT project_id, text, updated_at FROM research_conclusions WHERE project_id = ?",
            (project_id,),
        )
        return None if row is None else dict(row)

    @staticmethod
    def _history_view(row: dict[str, Any]) -> dict[str, Any]:
        raw_refs = str(row["trigger_refs"] or "[]")
        try:
            trigger_refs = json.loads(raw_refs)
            if not isinstance(trigger_refs, list):
                trigger_refs = []
        except ValueError:
            trigger_refs = []
        return {
            "id": str(row["id"]),
            "projectId": str(row["project_id"]),
            "oldText": row["old_text"] if row["old_text"] is None else str(row["old_text"]),
            "newText": str(row["new_text"]),
            "triggerRefs": [str(ref) for ref in trigger_refs],
            "reason": row["reason"] if row["reason"] is None else str(row["reason"]),
            "changedAt": str(row["changed_at"]),
        }

    async def get(self, project_id: str) -> dict[str, Any]:
        await require_project(self._db, project_id)
        current = await self._current_row(project_id)
        count_row = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM research_conclusion_history WHERE project_id = ?",
            (project_id,),
        )
        return {
            "projectId": project_id,
            "text": None if current is None else str(current["text"]),
            "updatedAt": None if current is None else str(current["updated_at"]),
            "historyCount": int(count_row["n"]) if count_row else 0,
        }

    async def set_conclusion(
        self,
        project_id: str,
        *,
        text: Any,
        trigger_refs: Any = None,
        reason: Any = None,
    ) -> dict[str, Any]:
        """登记新结论：永远先写台账（含首次登记 old_text=NULL），再更新当前行。"""
        await require_project(self._db, project_id)
        clean_text = _clean(text, label="text", max_len=MAX_CONCLUSION)
        assert clean_text is not None
        clean_reason = _clean(reason, label="reason", max_len=MAX_REASON, required=False)
        refs: list[str] = []
        if trigger_refs is not None:
            if not isinstance(trigger_refs, list):
                raise ResearchInvalid("triggerRefs 必须是数组。")
            if len(trigger_refs) > MAX_TRIGGER_REFS:
                raise ResearchInvalid(f"triggerRefs 最多 {MAX_TRIGGER_REFS} 条。")
            for raw in trigger_refs:
                ref = clean_item_ref(raw)
                if ref is None:
                    raise ResearchInvalid("triggerRefs 里不能有空项。")
                if ref not in refs:
                    refs.append(ref)
        now = utc_now()
        previous = await self._current_row(project_id)
        old_text = None if previous is None else str(previous["text"])

        from lumirss.db_tx import transaction

        def _tx(conn: Any) -> None:
            conn.execute(
                "INSERT INTO research_conclusion_history (id, project_id, old_text, new_text, "
                "trigger_refs, reason, changed_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    str(_uuid.uuid4()),
                    project_id,
                    old_text,
                    clean_text,
                    json.dumps(refs, ensure_ascii=False),
                    clean_reason,
                    now,
                ),
            )
            conn.execute(
                "INSERT INTO research_conclusions (project_id, text, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(project_id) DO UPDATE SET text = excluded.text, "
                "updated_at = excluded.updated_at",
                (project_id, clean_text, now),
            )

        await transaction(self._db, _tx)
        history = await self.history(project_id)
        return {
            "projectId": project_id,
            "text": clean_text,
            "updatedAt": now,
            "previousText": old_text,
            "historyCount": history["historyCount"],
            "latestChange": history["items"][0],
        }

    async def history(self, project_id: str) -> dict[str, Any]:
        """完整变更台账（旧→新可由 changedAt 判断；列表新→旧返回）。"""
        await require_project(self._db, project_id)
        rows = await self._db.fetch_all(
            "SELECT * FROM research_conclusion_history WHERE project_id = ? "
            "ORDER BY changed_at DESC, rowid DESC LIMIT 500",
            (project_id,),
        )
        items = [self._history_view(row) for row in rows]
        return {"projectId": project_id, "historyCount": len(items), "items": items}
