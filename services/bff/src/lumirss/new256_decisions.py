"""NEW-256 研究决策记录 —— 基于哪些材料作了哪项个人决策。

- 登记：decision（决策内容）+ basis（决策依据说明）+ 依据材料
  （ItemRef 列表，只引用不复制）；
- 追加：followups —— kind='outcome' 结果 / kind='revision' 修正原因。
  只追加：没有 UPDATE/DELETE 路径，决策演变全程可回看；
- 决策行本身不可改写：登记后 decision/basis 不提供修改（错了就追加
  revision 说明——诚实边界）。
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

MAX_DECISION = 2000
KINDS = ("outcome", "revision")


class DecisionNotFound(Exception):
    """决策记录不存在（映射 404）。"""


class DecisionStore:
    def __init__(self, db: Any) -> None:
        self._db = db

    async def _row(self, decision_id: str) -> dict[str, Any]:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT * FROM research_decisions WHERE id = ?", (decision_id,)
        )
        if row is None:
            raise DecisionNotFound(decision_id)
        return dict(row)

    async def _view(self, decision_id: str) -> dict[str, Any]:
        row = await self._row(decision_id)
        materials = await self._db.fetch_all(
            "SELECT id, item_ref, added_at FROM research_decision_materials "
            "WHERE decision_id = ? ORDER BY added_at ASC, rowid ASC",
            (decision_id,),
        )
        followups = await self._db.fetch_all(
            "SELECT id, kind, text, created_at FROM research_decision_followups "
            "WHERE decision_id = ? ORDER BY created_at ASC, rowid ASC",
            (decision_id,),
        )
        return {
            "id": str(row["id"]),
            "projectId": str(row["project_id"]),
            "decision": str(row["decision"]),
            "basis": row["basis"] if row["basis"] is None else str(row["basis"]),
            "materials": [
                {
                    "id": str(m["id"]),
                    "itemRef": str(m["item_ref"]),
                    "addedAt": str(m["added_at"]),
                }
                for m in materials
            ],
            "followUps": [
                {
                    "id": str(f["id"]),
                    "kind": str(f["kind"]),
                    "text": str(f["text"]),
                    "createdAt": str(f["created_at"]),
                }
                for f in followups
            ],
            "createdAt": str(row["created_at"]),
        }

    async def create(
        self, project_id: str, *, decision: Any, basis: Any = None, item_refs: Any = None
    ) -> dict[str, Any]:
        await require_project(self._db, project_id)
        clean_decision = _clean(decision, label="decision", max_len=MAX_DECISION)
        assert clean_decision is not None
        clean_basis = _clean(basis, label="basis", max_len=4000, required=False)
        refs: list[str] = []
        if item_refs is not None:
            if not isinstance(item_refs, list):
                raise ResearchInvalid("itemRefs 必须是数组。")
            for raw in item_refs:
                ref = clean_item_ref(raw)
                if ref is None:
                    raise ResearchInvalid("itemRefs 里不能有空项。")
                if ref not in refs:
                    refs.append(ref)
        decision_id = str(_uuid.uuid4())
        now = utc_now()

        from lumirss.db_tx import transaction

        def _tx(conn: Any) -> None:
            conn.execute(
                "INSERT INTO research_decisions (id, project_id, decision, basis, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (decision_id, project_id, clean_decision, clean_basis, now),
            )
            for ref in refs:
                conn.execute(
                    "INSERT INTO research_decision_materials (id, decision_id, item_ref, added_at) "
                    "VALUES (?, ?, ?, ?)",
                    (str(_uuid.uuid4()), decision_id, ref, now),
                )

        await transaction(self._db, _tx)
        return await self._view(decision_id)

    async def list(self, project_id: str) -> dict[str, Any]:
        await require_project(self._db, project_id)
        rows = await self._db.fetch_all(
            "SELECT id FROM research_decisions WHERE project_id = ? "
            "ORDER BY created_at DESC, rowid DESC",
            (project_id,),
        )
        return {
            "projectId": project_id,
            "items": [await self._view(str(row["id"])) for row in rows],
        }

    async def add_followup(self, decision_id: str, *, kind: Any, text: Any) -> dict[str, Any]:
        await self._row(decision_id)
        if kind not in KINDS:
            raise ResearchInvalid("kind 只能是 outcome 或 revision。")
        clean_text = _clean(text, label="text", max_len=2000)
        assert clean_text is not None
        followup_id = str(_uuid.uuid4())
        now = utc_now()
        await self._db.execute(
            "INSERT INTO research_decision_followups (id, decision_id, kind, text, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (followup_id, decision_id, kind, clean_text, now),
        )
        return {
            "id": followup_id,
            "decisionId": decision_id,
            "kind": kind,
            "text": clean_text,
            "createdAt": now,
        }

    async def add_material(self, decision_id: str, *, item_ref: Any) -> dict[str, Any]:
        await self._row(decision_id)
        ref = clean_item_ref(item_ref)
        if ref is None:
            raise ResearchInvalid("itemRef 不能为空。")
        existing = await self._db.fetch_one(
            "SELECT id FROM research_decision_materials WHERE decision_id = ? AND item_ref = ?",
            (decision_id, ref),
        )
        if existing is not None:
            return {"id": str(existing["id"]), "itemRef": ref, "outcome": "duplicate"}
        material_id = str(_uuid.uuid4())
        await self._db.execute(
            "INSERT INTO research_decision_materials (id, decision_id, item_ref, added_at) "
            "VALUES (?, ?, ?, ?)",
            (material_id, decision_id, ref, utc_now()),
        )
        return {"id": material_id, "itemRef": ref, "outcome": "created"}
