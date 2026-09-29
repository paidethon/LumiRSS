"""NEW-258 研究大纲编排 —— 章节 + 素材（引文/笔记/小结）→ Markdown 草稿。

- 章节（research_outline_sections）按 position 排；素材
  （research_outline_items）按 position 排，kind: quote（选定引文，
  citation 记出处）/ note（笔记）/ summary（小结）；
- 排序诚实边界：不实现拖拽——提供 move（up/down）与 assign（分配到
  其他章节）两个显式动作；draft 响应 note 字段如实说明这一点；
- Markdown 草稿：纯文本生成（只读、零写入），引文带出处行；
  空章节诚实保留标题（「（本章暂无素材）」）。
"""

import uuid as _uuid
from typing import Any

from lumirss.new251_research import (
    ResearchInvalid,
    _clean,
    require_project,
)
from lumirss.util import utc_now

MAX_SECTION_TITLE = 200
MAX_CONTENT = 8000
KINDS = ("quote", "note", "summary")
_KIND_LABELS = {"quote": "引文", "note": "笔记", "summary": "小结"}
_MOVE_NOTE = "排序为显式上移/下移+跨章节分配（本部署未实现拖拽）——诚实标注，不是拖拽。"


class OutlineNotFound(Exception):
    """章节或素材不存在（映射 404）。"""


def _renumber(items: list[tuple[str, int]]) -> list[tuple[str, int]]:
    """把 (id, old_position) 重排为连续 1..N（保相对顺序）。"""
    return [(item_id, index + 1) for index, (item_id, _old) in enumerate(items)]


class OutlineStore:
    def __init__(self, db: Any) -> None:
        self._db = db

    # -- 读取 ------------------------------------------------------------

    async def get(self, project_id: str) -> dict[str, Any]:
        await require_project(self._db, project_id)
        await self._db.migrate()
        sections = await self._db.fetch_all(
            "SELECT id, title, position, created_at FROM research_outline_sections "
            "WHERE project_id = ? ORDER BY position ASC, rowid ASC",
            (project_id,),
        )
        view_sections = []
        for section in sections:
            section_id = str(section["id"])
            items = await self._db.fetch_all(
                "SELECT id, kind, content, citation, position, created_at, updated_at "
                "FROM research_outline_items WHERE section_id = ? "
                "ORDER BY position ASC, rowid ASC",
                (section_id,),
            )
            view_sections.append(
                {
                    "id": section_id,
                    "title": str(section["title"]),
                    "position": int(section["position"]),
                    "createdAt": str(section["created_at"]),
                    "items": [
                        {
                            "id": str(item["id"]),
                            "sectionId": section_id,
                            "kind": str(item["kind"]),
                            "content": str(item["content"]),
                            "citation": (
                                item["citation"] if item["citation"] is None else str(item["citation"])
                            ),
                            "position": int(item["position"]),
                            "createdAt": str(item["created_at"]),
                            "updatedAt": str(item["updated_at"]),
                        }
                        for item in items
                    ],
                }
            )
        return {"projectId": project_id, "sections": view_sections, "note": _MOVE_NOTE}

    # -- 章节 ------------------------------------------------------------

    async def add_section(self, project_id: str, *, title: Any) -> dict[str, Any]:
        await require_project(self._db, project_id)
        clean_title = _clean(title, label="title", max_len=MAX_SECTION_TITLE)
        assert clean_title is not None
        row = await self._db.fetch_one(
            "SELECT COALESCE(MAX(position), 0) AS max_pos FROM research_outline_sections "
            "WHERE project_id = ?",
            (project_id,),
        )
        section_id = str(_uuid.uuid4())
        await self._db.execute(
            "INSERT INTO research_outline_sections (id, project_id, title, position, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (section_id, project_id, clean_title, int(row["max_pos"]) + 1, utc_now()),
        )
        return {"id": section_id, "projectId": project_id, "title": clean_title, "items": []}

    async def rename_section(self, section_id: str, *, title: Any) -> dict[str, Any]:
        await self._section_exists(section_id)
        clean_title = _clean(title, label="title", max_len=MAX_SECTION_TITLE)
        assert clean_title is not None
        await self._db.execute(
            "UPDATE research_outline_sections SET title = ? WHERE id = ?",
            (clean_title, section_id),
        )
        return {"id": section_id, "title": clean_title}

    async def delete_section(self, section_id: str) -> None:
        await self._section_exists(section_id)

        from lumirss.db_tx import transaction

        def _tx(conn: Any) -> None:
            conn.execute("DELETE FROM research_outline_items WHERE section_id = ?", (section_id,))
            conn.execute("DELETE FROM research_outline_sections WHERE id = ?", (section_id,))

        await transaction(self._db, _tx)

    async def _section_exists(self, section_id: str) -> None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id FROM research_outline_sections WHERE id = ?", (section_id,)
        )
        if row is None:
            raise OutlineNotFound(section_id)

    async def move_section(self, section_id: str, *, direction: str) -> dict[str, Any]:
        """章节上移/下移（显式动作；不是拖拽）。"""
        await self._section_exists(section_id)
        if direction not in ("up", "down"):
            raise ResearchInvalid("direction 只能是 up 或 down。")
        row = await self._db.fetch_one(
            "SELECT project_id, position FROM research_outline_sections WHERE id = ?",
            (section_id,),
        )
        siblings = await self._db.fetch_all(
            "SELECT id, position FROM research_outline_sections WHERE project_id = ? "
            "ORDER BY position ASC, rowid ASC",
            (str(row["project_id"]),),
        )
        ids = [str(s["id"]) for s in siblings]
        index = ids.index(section_id)
        swap_with = index - 1 if direction == "up" else index + 1
        if swap_with < 0 or swap_with >= len(ids):
            return {"moved": 0, "note": "已在边界，无可交换的相邻章节。"}
        ids[index], ids[swap_with] = ids[swap_with], ids[index]

        from lumirss.db_tx import transaction

        def _tx(conn: Any) -> None:
            for sibling_id, pos in _renumber([(i, 0) for i in ids]):
                conn.execute(
                    "UPDATE research_outline_sections SET position = ? WHERE id = ?",
                    (pos, sibling_id),
                )

        await transaction(self._db, _tx)
        return {"moved": 1, "note": "章节顺序已更新（上移/下移）。"}

    # -- 素材 ------------------------------------------------------------

    async def _item_row(self, item_id: str) -> dict[str, Any]:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT * FROM research_outline_items WHERE id = ?", (item_id,)
        )
        if row is None:
            raise OutlineNotFound(item_id)
        return dict(row)

    async def add_item(
        self, section_id: str, *, kind: Any, content: Any, citation: Any = None
    ) -> dict[str, Any]:
        await self._section_exists(section_id)
        if kind not in KINDS:
            raise ResearchInvalid("kind 只能是 quote / note / summary。")
        clean_content = _clean(content, label="content", max_len=MAX_CONTENT)
        assert clean_content is not None
        clean_citation = _clean(citation, label="citation", max_len=500, required=False)
        if kind == "quote" and not clean_citation:
            raise ResearchInvalid("quote（选定引文）必须写明出处（citation）。")
        row = await self._db.fetch_one(
            "SELECT COALESCE(MAX(position), 0) AS max_pos FROM research_outline_items "
            "WHERE section_id = ?",
            (section_id,),
        )
        item_id = str(_uuid.uuid4())
        now = utc_now()
        await self._db.execute(
            "INSERT INTO research_outline_items (id, section_id, kind, content, citation, "
            "position, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (item_id, section_id, kind, clean_content, clean_citation, int(row["max_pos"]) + 1, now, now),
        )
        return {
            "id": item_id,
            "sectionId": section_id,
            "kind": kind,
            "content": clean_content,
            "citation": clean_citation,
        }

    async def update_item(
        self, item_id: str, *, content: Any = None, citation: Any = None
    ) -> dict[str, Any]:
        row = await self._item_row(item_id)
        clean_content = (
            _clean(content, label="content", max_len=MAX_CONTENT)
            if content is not None
            else str(row["content"])
        )
        assert clean_content is not None
        clean_citation = (
            _clean(citation, label="citation", max_len=500, required=False)
            if citation is not None
            else row["citation"]
        )
        await self._db.execute(
            "UPDATE research_outline_items SET content = ?, citation = ?, updated_at = ? WHERE id = ?",
            (clean_content, clean_citation, utc_now(), item_id),
        )
        return {"id": item_id, "content": clean_content, "citation": clean_citation}

    async def delete_item(self, item_id: str) -> None:
        await self._item_row(item_id)
        await self._db.execute("DELETE FROM research_outline_items WHERE id = ?", (item_id,))

    async def move_item(self, item_id: str, *, direction: str) -> dict[str, Any]:
        """素材在同章节内上移/下移。"""
        row = await self._item_row(item_id)
        if direction not in ("up", "down"):
            raise ResearchInvalid("direction 只能是 up 或 down。")
        section_id = str(row["section_id"])
        siblings = await self._db.fetch_all(
            "SELECT id FROM research_outline_items WHERE section_id = ? "
            "ORDER BY position ASC, rowid ASC",
            (section_id,),
        )
        ids = [str(s["id"]) for s in siblings]
        index = ids.index(item_id)
        swap_with = index - 1 if direction == "up" else index + 1
        if swap_with < 0 or swap_with >= len(ids):
            return {"moved": 0, "note": "已在边界，无可交换的相邻素材。"}
        ids[index], ids[swap_with] = ids[swap_with], ids[index]

        from lumirss.db_tx import transaction

        def _tx(conn: Any) -> None:
            for sibling_id, pos in _renumber([(i, 0) for i in ids]):
                conn.execute(
                    "UPDATE research_outline_items SET position = ? WHERE id = ?",
                    (pos, sibling_id),
                )

        await transaction(self._db, _tx)
        return {"moved": 1, "note": "素材顺序已更新（上移/下移）。"}

    async def assign_item(self, item_id: str, *, target_section_id: str) -> dict[str, Any]:
        """把素材分配到另一章节（显式动作；跨章节移动不靠拖拽）。"""
        row = await self._item_row(item_id)
        if str(row["section_id"]) == target_section_id:
            raise ResearchInvalid("素材已在该章节。")
        await self._section_exists(target_section_id)
        target = await self._db.fetch_one(
            "SELECT COALESCE(MAX(position), 0) AS max_pos FROM research_outline_items "
            "WHERE section_id = ?",
            (target_section_id,),
        )
        await self._db.execute(
            "UPDATE research_outline_items SET section_id = ?, position = ?, updated_at = ? WHERE id = ?",
            (target_section_id, int(target["max_pos"]) + 1, utc_now(), item_id),
        )
        return {"id": item_id, "sectionId": target_section_id, "note": "已分配到目标章节。"}

    # -- Markdown 草稿 -----------------------------------------------------

    async def draft_markdown(self, project_id: str) -> dict[str, Any]:
        """带引用的 Markdown 草稿（纯文本生成，只读零写入）。"""
        outline = await self.get(project_id)
        project = await require_project(self._db, project_id)
        lines: list[str] = [f"# {project['title']}", ""]
        item_total = 0
        for section in outline["sections"]:
            lines.append(f"## {section['title']}")
            lines.append("")
            if not section["items"]:
                lines.append("（本章暂无素材）")
                lines.append("")
                continue
            for item in section["items"]:
                item_total += 1
                label = _KIND_LABELS[item["kind"]]
                if item["kind"] == "quote":
                    lines.append(f"> {item['content']}")
                    if item["citation"]:
                        lines.append(f"> — {item['citation']}")
                else:
                    lines.append(f"- **{label}**：{item['content']}")
            lines.append("")
        draft = "\n".join(lines).rstrip() + "\n"
        return {
            "projectId": project_id,
            "markdown": draft,
            "sectionCount": len(outline["sections"]),
            "itemCount": item_total,
            "note": _MOVE_NOTE + " 草稿为只读生成，不落库不覆盖。",
        }
