"""NEW-251 研究问题拆分 —— 研究项目主线 + 父问题/子问题拆解。

- 研究项目（research_projects）是本组（NEW-251..260）共用的分组主线：
  项目只是本人库里的分组锚点，per-user 库天然隔离，没有任何共享面。
- 问题拆分：父问题（research_questions）→ 若干子问题
  （research_subquestions）；每个子问题各自带
  - 关联材料（research_question_materials，ItemRef 只引用不复制）；
  - 结论草稿（conclusion，随写随改）；
  - 未解决状态（status open|resolved，set 语义显式切换，resolved_at 记账）。

诚实边界：结论草稿是用户手写文本，本模块不做任何自动归纳/推断；
「项目主线」仅提供 CRUD，绝不预置示例项目或占位内容。
"""

import json
import uuid as _uuid
from typing import Any

from lumirss.itemref import InvalidItemRef, parse_item_ref
from lumirss.util import utc_now

MAX_TITLE = 120
MAX_TEXT = 2000
MAX_CONCLUSION = 4000
MAX_QUESTION = 500


class ResearchInvalid(ValueError):
    """研究项目/问题负载非法（映射 422）。"""


class ProjectNotFound(Exception):
    """研究项目不存在（映射 404）。"""


class QuestionNotFound(Exception):
    """父问题或子问题不存在（映射 404）。"""


def _clean(value: Any, *, label: str, max_len: int, required: bool = True) -> str | None:
    if value is None:
        if required:
            raise ResearchInvalid(f"{label} 不能为空。")
        return None
    if not isinstance(value, str):
        raise ResearchInvalid(f"{label} 必须是字符串。")
    text = value.strip()
    if not text:
        if required:
            raise ResearchInvalid(f"{label} 不能为空。")
        return None
    if len(text) > max_len:
        raise ResearchInvalid(f"{label} 过长（≤{max_len} 字符）。")
    return text


def clean_item_ref(value: Any) -> str | None:
    """ItemRef 校验（rss:/library: 前缀 + 载荷合法）；None 直接放行。"""
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ResearchInvalid("itemRef 不能为空字符串。")
    try:
        return parse_item_ref(value.strip()).format()
    except InvalidItemRef as exc:
        raise ResearchInvalid(f"itemRef 非法：{exc}") from exc


async def require_project(db: Any, project_id: str) -> dict[str, Any]:
    """项目存在性校验；返回行 dict（其他 NEW-25x 模块共用）。"""
    await db.migrate()
    row = await db.fetch_one(
        "SELECT id, title, description, created_at, updated_at "
        "FROM research_projects WHERE id = ?",
        (project_id,),
    )
    if row is None:
        raise ProjectNotFound(project_id)
    return dict(row)


class ResearchProjectStore:
    def __init__(self, db: Any) -> None:
        self._db = db

    async def create(self, *, title: Any, description: Any = None) -> dict[str, Any]:
        clean_title = _clean(title, label="title", max_len=MAX_TITLE)
        clean_desc = _clean(description, label="description", max_len=2000, required=False)
        project_id = str(_uuid.uuid4())
        now = utc_now()
        await self._db.execute(
            "INSERT INTO research_projects (id, title, description, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (project_id, clean_title, clean_desc, now, now),
        )
        return await self.get(project_id)

    async def list(self) -> dict[str, Any]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT p.id, p.title, p.description, p.created_at, p.updated_at, "
            "(SELECT COUNT(*) FROM research_questions q WHERE q.project_id = p.id) AS question_count "
            "FROM research_projects p ORDER BY p.created_at DESC, p.rowid DESC LIMIT 200"
        )
        return {
            "items": [
                {
                    "id": str(row["id"]),
                    "title": str(row["title"]),
                    "description": row["description"] if row["description"] is None else str(row["description"]),
                    "questionCount": int(row["question_count"]),
                    "createdAt": str(row["created_at"]),
                    "updatedAt": str(row["updated_at"]),
                }
                for row in rows
            ]
        }

    async def get(self, project_id: str) -> dict[str, Any]:
        project = await require_project(self._db, project_id)
        await self._db.migrate()
        counts = await self._db.fetch_one(
            "SELECT "
            "(SELECT COUNT(*) FROM research_questions WHERE project_id = ?) AS questions, "
            "(SELECT COUNT(*) FROM research_subquestions s JOIN research_questions q ON s.question_id = q.id "
            " WHERE q.project_id = ? AND s.status = 'open') AS open_subquestions",
            (project_id, project_id),
        )
        return {
            "id": str(project["id"]),
            "title": str(project["title"]),
            "description": project["description"] if project["description"] is None else str(project["description"]),
            "questionCount": int(counts["questions"]) if counts else 0,
            "openSubquestionCount": int(counts["open_subquestions"]) if counts else 0,
            "createdAt": str(project["created_at"]),
            "updatedAt": str(project["updated_at"]),
        }

    async def update(self, project_id: str, *, title: Any = None, description: Any = None) -> dict[str, Any]:
        project = await require_project(self._db, project_id)
        clean_title = _clean(title, label="title", max_len=MAX_TITLE) if title is not None else str(project["title"])
        clean_desc = (
            _clean(description, label="description", max_len=2000, required=False)
            if description is not None
            else project["description"]
        )
        await self._db.execute(
            "UPDATE research_projects SET title = ?, description = ?, updated_at = ? WHERE id = ?",
            (clean_title, clean_desc, utc_now(), project_id),
        )
        return await self.get(project_id)

    async def delete(self, project_id: str) -> None:
        """删除项目及其全部研究数据（本人库内级联；显式动作）。"""
        await require_project(self._db, project_id)
        await self._db.migrate()
        question_ids = [
            str(row["id"])
            for row in await self._db.fetch_all(
                "SELECT id FROM research_questions WHERE project_id = ?", (project_id,)
            )
        ]

        def _tx(conn: Any) -> None:
            for qid in question_ids:
                conn.execute(
                    "DELETE FROM research_question_materials WHERE subquestion_id IN "
                    "(SELECT id FROM research_subquestions WHERE question_id = ?)",
                    (qid,),
                )
                conn.execute(
                    "DELETE FROM research_subquestions WHERE question_id = ?", (qid,)
                )
            conn.execute("DELETE FROM research_questions WHERE project_id = ?", (project_id,))
            conn.execute("DELETE FROM research_projects WHERE id = ?", (project_id,))
            conn.execute(
                "DELETE FROM research_hypotheses WHERE project_id = ?", (project_id,)
            )
            conn.execute(
                "DELETE FROM research_counterexamples WHERE project_id = ?", (project_id,)
            )
            conn.execute(
                "DELETE FROM research_glossary_terms WHERE project_id = ?", (project_id,)
            )
            conn.execute(
                "DELETE FROM research_timeline_events WHERE project_id = ?", (project_id,)
            )
            conn.execute(
                "DELETE FROM research_decision_materials WHERE decision_id IN "
                "(SELECT id FROM research_decisions WHERE project_id = ?)",
                (project_id,),
            )
            conn.execute(
                "DELETE FROM research_decision_followups WHERE decision_id IN "
                "(SELECT id FROM research_decisions WHERE project_id = ?)",
                (project_id,),
            )
            conn.execute(
                "DELETE FROM research_decisions WHERE project_id = ?", (project_id,)
            )
            conn.execute(
                "DELETE FROM research_material_gaps WHERE project_id = ?", (project_id,)
            )
            conn.execute(
                "DELETE FROM research_outline_items WHERE section_id IN "
                "(SELECT id FROM research_outline_sections WHERE project_id = ?)",
                (project_id,),
            )
            conn.execute(
                "DELETE FROM research_outline_sections WHERE project_id = ?", (project_id,)
            )
            conn.execute(
                "DELETE FROM research_conclusion_history WHERE project_id = ?", (project_id,)
            )
            conn.execute(
                "DELETE FROM research_conclusions WHERE project_id = ?", (project_id,)
            )
            conn.execute(
                "DELETE FROM research_share_confirmations WHERE project_id = ?", (project_id,)
            )

        from lumirss.db_tx import transaction

        await transaction(self._db, _tx)


class ResearchQuestionStore:
    def __init__(self, db: Any) -> None:
        self._db = db

    # -- 父问题 -----------------------------------------------------------

    async def add_question(self, project_id: str, *, question: Any) -> dict[str, Any]:
        await require_project(self._db, project_id)
        text = _clean(question, label="question", max_len=MAX_QUESTION)
        question_id = str(_uuid.uuid4())
        await self._db.execute(
            "INSERT INTO research_questions (id, project_id, question, created_at) "
            "VALUES (?, ?, ?, ?)",
            (question_id, project_id, text, utc_now()),
        )
        return await self.get_question(question_id)

    async def list_questions(self, project_id: str) -> dict[str, Any]:
        await require_project(self._db, project_id)
        rows = await self._db.fetch_all(
            "SELECT id, question, created_at FROM research_questions "
            "WHERE project_id = ? ORDER BY created_at ASC, rowid ASC",
            (project_id,),
        )
        return {
            "projectId": project_id,
            "items": [
                {
                    "id": str(row["id"]),
                    "question": str(row["question"]),
                    "createdAt": str(row["created_at"]),
                    "subquestions": [
                        self._sub_view(sub)
                        for sub in await self._db.fetch_all(
                            "SELECT * FROM research_subquestions WHERE question_id = ? "
                            "ORDER BY created_at ASC, rowid ASC",
                            (str(row["id"]),),
                        )
                    ],
                }
                for row in rows
            ],
        }

    async def get_question(self, question_id: str) -> dict[str, Any]:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, project_id, question, created_at FROM research_questions WHERE id = ?",
            (question_id,),
        )
        if row is None:
            raise QuestionNotFound(question_id)
        return {
            "id": str(row["id"]),
            "projectId": str(row["project_id"]),
            "question": str(row["question"]),
            "createdAt": str(row["created_at"]),
            "subquestions": [
                self._sub_view(sub)
                for sub in await self._db.fetch_all(
                    "SELECT * FROM research_subquestions WHERE question_id = ? "
                    "ORDER BY created_at ASC, rowid ASC",
                    (question_id,),
                )
            ],
        }

    async def delete_question(self, question_id: str) -> None:
        await self.get_question(question_id)  # 存在性校验

        def _tx(conn: Any) -> None:
            conn.execute(
                "DELETE FROM research_question_materials WHERE subquestion_id IN "
                "(SELECT id FROM research_subquestions WHERE question_id = ?)",
                (question_id,),
            )
            conn.execute("DELETE FROM research_subquestions WHERE question_id = ?", (question_id,))
            conn.execute("DELETE FROM research_questions WHERE id = ?", (question_id,))

        from lumirss.db_tx import transaction

        await transaction(self._db, _tx)

    # -- 子问题 -----------------------------------------------------------

    def _sub_view(self, row: Any) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "questionId": str(row["question_id"]),
            "text": str(row["text"]),
            "conclusion": row["conclusion"] if row["conclusion"] is None else str(row["conclusion"]),
            "status": str(row["status"]),
            "createdAt": str(row["created_at"]),
            "updatedAt": str(row["updated_at"]),
            "resolvedAt": row["resolved_at"] if row["resolved_at"] is None else str(row["resolved_at"]),
        }

    async def _sub_row(self, subquestion_id: str) -> dict[str, Any]:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT * FROM research_subquestions WHERE id = ?", (subquestion_id,)
        )
        if row is None:
            raise QuestionNotFound(subquestion_id)
        return dict(row)

    async def add_subquestion(self, question_id: str, *, text: Any) -> dict[str, Any]:
        await self.get_question(question_id)  # 存在性校验
        clean_text = _clean(text, label="text", max_len=MAX_QUESTION)
        sub_id = str(_uuid.uuid4())
        now = utc_now()
        await self._db.execute(
            "INSERT INTO research_subquestions (id, question_id, text, status, created_at, updated_at) "
            "VALUES (?, ?, ?, 'open', ?, ?)",
            (sub_id, question_id, clean_text, now, now),
        )
        row = await self._sub_row(sub_id)
        return self._sub_view(row)

    async def update_subquestion(
        self, subquestion_id: str, *, text: Any = None, conclusion: Any = None, status: Any = None
    ) -> dict[str, Any]:
        row = await self._sub_row(subquestion_id)
        clean_text = _clean(text, label="text", max_len=MAX_QUESTION) if text is not None else str(row["text"])
        clean_conclusion = (
            _clean(conclusion, label="conclusion", max_len=MAX_CONCLUSION, required=False)
            if conclusion is not None
            else row["conclusion"]
        )
        now = utc_now()
        if status is not None:
            if status not in ("open", "resolved"):
                raise ResearchInvalid("status 只能是 open 或 resolved。")
            resolved_at = now if status == "resolved" else None
            await self._db.execute(
                "UPDATE research_subquestions SET text = ?, conclusion = ?, status = ?, "
                "resolved_at = ?, updated_at = ? WHERE id = ?",
                (clean_text, clean_conclusion, status, resolved_at, now, subquestion_id),
            )
        else:
            await self._db.execute(
                "UPDATE research_subquestions SET text = ?, conclusion = ?, updated_at = ? WHERE id = ?",
                (clean_text, clean_conclusion, now, subquestion_id),
            )
        return self._sub_view(await self._sub_row(subquestion_id))

    async def delete_subquestion(self, subquestion_id: str) -> None:
        await self._sub_row(subquestion_id)

        def _tx(conn: Any) -> None:
            conn.execute(
                "DELETE FROM research_question_materials WHERE subquestion_id = ?",
                (subquestion_id,),
            )
            conn.execute("DELETE FROM research_subquestions WHERE id = ?", (subquestion_id,))

        from lumirss.db_tx import transaction

        await transaction(self._db, _tx)

    # -- 子问题材料 ---------------------------------------------------------

    async def add_material(self, subquestion_id: str, *, item_ref: Any) -> dict[str, Any]:
        await self._sub_row(subquestion_id)
        ref = clean_item_ref(item_ref)
        if ref is None:
            raise ResearchInvalid("itemRef 不能为空。")
        existing = await self._db.fetch_one(
            "SELECT id FROM research_question_materials WHERE subquestion_id = ? AND item_ref = ?",
            (subquestion_id, ref),
        )
        if existing is not None:
            return {"id": str(existing["id"]), "subquestionId": subquestion_id, "itemRef": ref, "outcome": "duplicate"}
        material_id = str(_uuid.uuid4())
        await self._db.execute(
            "INSERT INTO research_question_materials (id, subquestion_id, item_ref, added_at) "
            "VALUES (?, ?, ?, ?)",
            (material_id, subquestion_id, ref, utc_now()),
        )
        return {"id": material_id, "subquestionId": subquestion_id, "itemRef": ref, "outcome": "created"}

    async def list_materials(self, subquestion_id: str) -> dict[str, Any]:
        await self._sub_row(subquestion_id)
        rows = await self._db.fetch_all(
            "SELECT id, item_ref, added_at FROM research_question_materials "
            "WHERE subquestion_id = ? ORDER BY added_at ASC, rowid ASC",
            (subquestion_id,),
        )
        return {
            "subquestionId": subquestion_id,
            "items": [
                {"id": str(row["id"]), "itemRef": str(row["item_ref"]), "addedAt": str(row["added_at"])}
                for row in rows
            ],
        }

    async def remove_material(self, material_id: str) -> None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id FROM research_question_materials WHERE id = ?", (material_id,)
        )
        if row is None:
            raise QuestionNotFound(material_id)
        await self._db.execute(
            "DELETE FROM research_question_materials WHERE id = ?", (material_id,)
        )


def dumps_refs(refs: list[str]) -> str:
    """材料引用列表 → JSON（NEW-259 trigger_refs 共用）。"""
    return json.dumps(refs, ensure_ascii=False)
