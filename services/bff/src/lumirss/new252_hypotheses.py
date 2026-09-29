"""NEW-252 假设登记册 —— 待检验假设 + 可支持/可反驳条件 + 材料分配。

- 登记：statement + support_condition + refute_condition 三栏必填
  （可反驳性是登记门槛——没有「什么证据能推翻它」就不发登记）；
- 状态：proposed（待检验）→ supported / refuted / retired 全部由用户
  显式裁决（PATCH），服务端没有任何自动判定；
- 材料分配：阅读材料（ItemRef）挂到 support / refute 相应侧；
  同一材料可同时挂两侧（用户自己判断），同一侧不重复。
"""

import uuid as _uuid
from typing import Any

from lumirss.new251_research import (
    ProjectNotFound,
    ResearchInvalid,
    _clean,
    clean_item_ref,
    require_project,
)
from lumirss.util import utc_now

SIDES = ("support", "refute")
STATUSES = ("proposed", "supported", "refuted", "retired")
MAX_STATEMENT = 1000
_MAX_CONDITION = 1000


class HypothesisNotFound(Exception):
    """假设不存在（映射 404）。"""


def _condition(value: Any, label: str) -> str:
    cleaned = _clean(value, label=label, max_len=_MAX_CONDITION)
    assert cleaned is not None  # required=True
    return cleaned


class HypothesisStore:
    def __init__(self, db: Any) -> None:
        self._db = db

    async def _row(self, hypothesis_id: str) -> dict[str, Any]:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT * FROM research_hypotheses WHERE id = ?", (hypothesis_id,)
        )
        if row is None:
            raise HypothesisNotFound(hypothesis_id)
        return dict(row)

    def _view(self, row: dict[str, Any], materials: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "projectId": str(row["project_id"]),
            "statement": str(row["statement"]),
            "supportCondition": str(row["support_condition"]),
            "refuteCondition": str(row["refute_condition"]),
            "status": str(row["status"]),
            "materials": materials,
            "createdAt": str(row["created_at"]),
            "updatedAt": str(row["updated_at"]),
        }

    async def _materials(self, hypothesis_id: str) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT id, item_ref, side, note, added_at FROM research_hypothesis_materials "
            "WHERE hypothesis_id = ? ORDER BY side ASC, added_at ASC, rowid ASC",
            (hypothesis_id,),
        )
        return [
            {
                "id": str(row["id"]),
                "itemRef": str(row["item_ref"]),
                "side": str(row["side"]),
                "note": row["note"] if row["note"] is None else str(row["note"]),
                "addedAt": str(row["added_at"]),
            }
            for row in rows
        ]

    async def create(
        self,
        project_id: str,
        *,
        statement: Any,
        support_condition: Any,
        refute_condition: Any,
    ) -> dict[str, Any]:
        await require_project(self._db, project_id)
        clean_statement = _clean(statement, label="statement", max_len=MAX_STATEMENT)
        assert clean_statement is not None
        hypothesis_id = str(_uuid.uuid4())
        now = utc_now()
        await self._db.execute(
            "INSERT INTO research_hypotheses (id, project_id, statement, support_condition, "
            "refute_condition, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'proposed', ?, ?)",
            (
                hypothesis_id,
                project_id,
                clean_statement,
                _condition(support_condition, "supportCondition"),
                _condition(refute_condition, "refuteCondition"),
                now,
                now,
            ),
        )
        row = await self._row(hypothesis_id)
        return self._view(row, [])

    async def list(self, project_id: str) -> dict[str, Any]:
        await require_project(self._db, project_id)
        rows = await self._db.fetch_all(
            "SELECT id FROM research_hypotheses WHERE project_id = ? "
            "ORDER BY created_at ASC, rowid ASC",
            (project_id,),
        )
        items = []
        for row in rows:
            hyp = await self._row(str(row["id"]))
            items.append(self._view(hyp, await self._materials(str(row["id"]))))
        return {"projectId": project_id, "items": items}

    async def update(
        self,
        hypothesis_id: str,
        *,
        statement: Any = None,
        support_condition: Any = None,
        refute_condition: Any = None,
        status: Any = None,
    ) -> dict[str, Any]:
        row = await self._row(hypothesis_id)
        clean_statement = (
            _clean(statement, label="statement", max_len=MAX_STATEMENT)
            if statement is not None
            else str(row["statement"])
        )
        assert clean_statement is not None
        clean_support = (
            _condition(support_condition, "supportCondition")
            if support_condition is not None
            else str(row["support_condition"])
        )
        clean_refute = (
            _condition(refute_condition, "refuteCondition")
            if refute_condition is not None
            else str(row["refute_condition"])
        )
        clean_status = str(row["status"])
        if status is not None:
            if status not in STATUSES:
                raise ResearchInvalid(
                    "status 只能是 proposed / supported / refuted / retired。"
                )
            clean_status = status
        await self._db.execute(
            "UPDATE research_hypotheses SET statement = ?, support_condition = ?, "
            "refute_condition = ?, status = ?, updated_at = ? WHERE id = ?",
            (clean_statement, clean_support, clean_refute, clean_status, utc_now(), hypothesis_id),
        )
        updated = await self._row(hypothesis_id)
        return self._view(updated, await self._materials(hypothesis_id))

    async def delete(self, hypothesis_id: str) -> None:
        await self._row(hypothesis_id)

        def _tx(conn: Any) -> None:
            conn.execute(
                "DELETE FROM research_hypothesis_materials WHERE hypothesis_id = ?",
                (hypothesis_id,),
            )
            conn.execute("DELETE FROM research_hypotheses WHERE id = ?", (hypothesis_id,))

        from lumirss.db_tx import transaction

        await transaction(self._db, _tx)

    async def add_material(
        self, hypothesis_id: str, *, item_ref: Any, side: Any, note: Any = None
    ) -> dict[str, Any]:
        await self._row(hypothesis_id)
        if side not in SIDES:
            raise ResearchInvalid("side 只能是 support 或 refute。")
        ref = clean_item_ref(item_ref)
        if ref is None:
            raise ResearchInvalid("itemRef 不能为空。")
        clean_note = _clean(note, label="note", max_len=500, required=False)
        existing = await self._db.fetch_one(
            "SELECT id FROM research_hypothesis_materials "
            "WHERE hypothesis_id = ? AND item_ref = ? AND side = ?",
            (hypothesis_id, ref, side),
        )
        now = utc_now()
        if existing is not None:
            return {
                "id": str(existing["id"]),
                "hypothesisId": hypothesis_id,
                "itemRef": ref,
                "side": side,
                "note": clean_note,
                "addedAt": now,
                "outcome": "duplicate",
            }
        material_id = str(_uuid.uuid4())
        await self._db.execute(
            "INSERT INTO research_hypothesis_materials (id, hypothesis_id, item_ref, side, note, added_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (material_id, hypothesis_id, ref, side, clean_note, now),
        )
        return {
            "id": material_id,
            "hypothesisId": hypothesis_id,
            "itemRef": ref,
            "side": side,
            "note": clean_note,
            "addedAt": now,
            "outcome": "created",
        }

    async def remove_material(self, material_id: str) -> None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id FROM research_hypothesis_materials WHERE id = ?", (material_id,)
        )
        if row is None:
            raise HypothesisNotFound(material_id)
        await self._db.execute(
            "DELETE FROM research_hypothesis_materials WHERE id = ?", (material_id,)
        )


class HypothesisInvalid(ResearchInvalid):
    """假设负载非法（422 的具名别名，路由层引用）。"""


__all__ = [
    "HypothesisInvalid",
    "HypothesisNotFound",
    "HypothesisStore",
    "ProjectNotFound",
    "ResearchInvalid",
]
