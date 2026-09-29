"""NEW-257 资料缺口任务 —— 研究需要但尚未找到的资料。

- 登记：description（缺什么资料）+ material_type（资料类型标签）；
- 关闭：close 是显式动作——必须挂上找到的材料（closedItemRef）；
  已关闭再 close → 422（诚实拒绝，不做幂等假成功）；
- reopen：关闭后发现挂错了可以重开（可留原因），重开后可再次关闭。
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

MAX_DESCRIPTION = 1000
MAX_TYPE = 60


class GapNotFound(Exception):
    """资料缺口不存在（映射 404）。"""


class GapStore:
    def __init__(self, db: Any) -> None:
        self._db = db

    async def _row(self, gap_id: str) -> dict[str, Any]:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT * FROM research_material_gaps WHERE id = ?", (gap_id,)
        )
        if row is None:
            raise GapNotFound(gap_id)
        return dict(row)

    @staticmethod
    def _view(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "projectId": str(row["project_id"]),
            "description": str(row["description"]),
            "materialType": row["material_type"] if row["material_type"] is None else str(row["material_type"]),
            "status": str(row["status"]),
            "closedAt": row["closed_at"] if row["closed_at"] is None else str(row["closed_at"]),
            "closedItemRef": (
                row["closed_item_ref"] if row["closed_item_ref"] is None else str(row["closed_item_ref"])
            ),
            "closeNote": row["close_note"] if row["close_note"] is None else str(row["close_note"]),
            "createdAt": str(row["created_at"]),
            "updatedAt": str(row["updated_at"]),
        }

    async def create(
        self, project_id: str, *, description: Any, material_type: Any = None
    ) -> dict[str, Any]:
        await require_project(self._db, project_id)
        clean_desc = _clean(description, label="description", max_len=MAX_DESCRIPTION)
        assert clean_desc is not None
        clean_type = _clean(material_type, label="materialType", max_len=MAX_TYPE, required=False)
        gap_id = str(_uuid.uuid4())
        now = utc_now()
        await self._db.execute(
            "INSERT INTO research_material_gaps (id, project_id, description, material_type, "
            "status, created_at, updated_at) VALUES (?, ?, ?, ?, 'open', ?, ?)",
            (gap_id, project_id, clean_desc, clean_type, now, now),
        )
        return self._view(await self._row(gap_id))

    async def list(self, project_id: str) -> dict[str, Any]:
        await require_project(self._db, project_id)
        rows = await self._db.fetch_all(
            "SELECT id FROM research_material_gaps WHERE project_id = ? "
            "ORDER BY status ASC, created_at ASC, rowid ASC",
            (project_id,),
        )
        items = [self._view(await self._row(str(row["id"]))) for row in rows]
        open_count = sum(1 for item in items if item["status"] == "open")
        return {
            "projectId": project_id,
            "openCount": open_count,
            "closedCount": len(items) - open_count,
            "items": items,
        }

    async def close(
        self, gap_id: str, *, item_ref: Any, note: Any = None
    ) -> dict[str, Any]:
        row = await self._row(gap_id)
        if row["status"] == "closed":
            raise ResearchInvalid("该缺口已关闭（要改挂材料请先 reopen）。")
        ref = clean_item_ref(item_ref)
        if ref is None:
            raise ResearchInvalid("关闭缺口必须挂上找到的材料（itemRef）。")
        clean_note = _clean(note, label="note", max_len=1000, required=False)
        now = utc_now()
        await self._db.execute(
            "UPDATE research_material_gaps SET status = 'closed', closed_at = ?, "
            "closed_item_ref = ?, close_note = ?, updated_at = ? WHERE id = ?",
            (now, ref, clean_note, now, gap_id),
        )
        return self._view(await self._row(gap_id))

    async def reopen(self, gap_id: str, *, reason: Any = None) -> dict[str, Any]:
        row = await self._row(gap_id)
        if row["status"] == "open":
            raise ResearchInvalid("该缺口本来就是 open。")
        clean_reason = _clean(reason, label="reason", max_len=1000, required=False)
        now = utc_now()
        # reopen 保留上次关闭痕迹到 note（诚实：不抹掉「曾经关过」的事实），
        # closed_item_ref 清空——它已不再代表「当前关在哪个材料上」。
        prior = row["close_note"]
        merged_note = (
            prior if clean_reason is None else (f"{prior}；重开原因：{clean_reason}" if prior else f"重开原因：{clean_reason}")
        )
        await self._db.execute(
            "UPDATE research_material_gaps SET status = 'open', closed_item_ref = NULL, "
            "close_note = ?, updated_at = ? WHERE id = ?",
            (merged_note, now, gap_id),
        )
        return self._view(await self._row(gap_id))

    async def delete(self, gap_id: str) -> None:
        await self._row(gap_id)
        await self._db.execute("DELETE FROM research_material_gaps WHERE id = ?", (gap_id,))
