"""NEW-254 研究术语表 —— 项目内术语、采用的解释与出处。

- UNIQUE(project_id, term)：一个项目里一个术语只有一个「当前采用」的
  解释；改解释走 PATCH（当前采用语义，不保留历史——与 NEW-259 结论
  历史的有意区别）。
- 查词：GET lookup?term=…&projectId=…（文章阅读时主动调出），只读、
  零写入；查不到 → found=false（诚实空态）。
- 边界：本表是研究项目私有工作术语表；查词/改词绝不触碰全局词典
  （glossary 表零交互）。
"""

import uuid as _uuid
from typing import Any

from lumirss.new251_research import (
    ResearchInvalid,
    _clean,
    require_project,
)
from lumirss.util import utc_now

MAX_TERM = 120
MAX_INTERPRETATION = 2000


class TermNotFound(Exception):
    """术语不存在（映射 404）。"""


class TermConflict(Exception):
    """同项目下已有同名术语（映射 409）。"""


class ResearchGlossaryStore:
    def __init__(self, db: Any) -> None:
        self._db = db

    async def _row(self, term_id: str) -> dict[str, Any]:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT * FROM research_glossary_terms WHERE id = ?", (term_id,)
        )
        if row is None:
            raise TermNotFound(term_id)
        return dict(row)

    @staticmethod
    def _view(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "projectId": str(row["project_id"]),
            "term": str(row["term"]),
            "interpretation": str(row["interpretation"]),
            "source": row["source"] if row["source"] is None else str(row["source"]),
            "createdAt": str(row["created_at"]),
            "updatedAt": str(row["updated_at"]),
        }

    async def create(
        self, project_id: str, *, term: Any, interpretation: Any, source: Any = None
    ) -> dict[str, Any]:
        await require_project(self._db, project_id)
        clean_term = _clean(term, label="term", max_len=MAX_TERM)
        assert clean_term is not None
        clean_interp = _clean(interpretation, label="interpretation", max_len=MAX_INTERPRETATION)
        assert clean_interp is not None
        clean_source = _clean(source, label="source", max_len=500, required=False)
        existing = await self._db.fetch_one(
            "SELECT id FROM research_glossary_terms WHERE project_id = ? AND term = ?",
            (project_id, clean_term),
        )
        if existing is not None:
            raise TermConflict(clean_term)
        term_id = str(_uuid.uuid4())
        now = utc_now()
        await self._db.execute(
            "INSERT INTO research_glossary_terms (id, project_id, term, interpretation, "
            "source, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (term_id, project_id, clean_term, clean_interp, clean_source, now, now),
        )
        return self._view(await self._row(term_id))

    async def list(self, project_id: str) -> dict[str, Any]:
        await require_project(self._db, project_id)
        rows = await self._db.fetch_all(
            "SELECT id FROM research_glossary_terms WHERE project_id = ? ORDER BY term ASC",
            (project_id,),
        )
        return {
            "projectId": project_id,
            "items": [self._view(await self._row(str(row["id"]))) for row in rows],
        }

    async def update(
        self, term_id: str, *, interpretation: Any = None, source: Any = None
    ) -> dict[str, Any]:
        row = await self._row(term_id)
        clean_interp = (
            _clean(interpretation, label="interpretation", max_len=MAX_INTERPRETATION)
            if interpretation is not None
            else str(row["interpretation"])
        )
        assert clean_interp is not None
        clean_source = (
            _clean(source, label="source", max_len=500, required=False)
            if source is not None
            else row["source"]
        )
        await self._db.execute(
            "UPDATE research_glossary_terms SET interpretation = ?, source = ?, updated_at = ? "
            "WHERE id = ?",
            (clean_interp, clean_source, utc_now(), term_id),
        )
        return self._view(await self._row(term_id))

    async def delete(self, term_id: str) -> None:
        await self._row(term_id)
        await self._db.execute("DELETE FROM research_glossary_terms WHERE id = ?", (term_id,))

    async def lookup(self, project_id: str, *, term: Any) -> dict[str, Any]:
        """文章阅读时主动调出：精确匹配（区分大小写按存储原文，
        另附大小写不敏感命中），只读。"""
        await require_project(self._db, project_id)
        raw = _clean(term, label="term", max_len=MAX_TERM)
        if raw is None:
            raise ResearchInvalid("term 不能为空。")
        exact = await self._db.fetch_one(
            "SELECT id FROM research_glossary_terms WHERE project_id = ? AND term = ?",
            (project_id, raw),
        )
        row = None
        if exact is not None:
            row = await self._row(str(exact["id"]))
        else:
            ci = await self._db.fetch_one(
                "SELECT id FROM research_glossary_terms "
                "WHERE project_id = ? AND term = ? COLLATE NOCASE LIMIT 1",
                (project_id, raw),
            )
            if ci is not None:
                row = await self._row(str(ci["id"]))
        return {
            "projectId": project_id,
            "term": raw,
            "found": row is not None,
            "match": self._view(row) if row is not None else None,
        }
