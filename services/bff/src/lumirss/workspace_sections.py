"""N113 分节大纲 —— 工作区内的显式大纲结构与分节成员。

- workspace_sections：显式分节（title + sort_index），与 N101 隐式分组
  互补（分组是呈现层派生标签，分节是用户显式创建的大纲，也是 N114
  汇编预览的输入）；
- workspace_section_items：分节成员以 item_ref 引用（绝不复制内容，
  ADR 0004）；同一 article 可同时出现在多个分节（PK (section_id,
  item_ref) 天然允许，跨分节只有引用没有第二份内容）；
- 加入分节的 ref 必须已是工作区成员（分节是工作区内的组织结构）；
- 工作区内条目被移除后分节引用行保留，列表端点诚实标记
  ``unresolved``（绝不静默隐藏；清理预演 N120 可显式移除）；
- 分节顺序 / 节内条目顺序均为持久化 sort_index/position（PUT 全量
  重排，非增量 swap）；分节顺序真实变化才 bump workspaces.revision
  （P15 并发，幂等重放不制造跨设备 409 噪声）。

本文件直接写站点 6 处（section INSERT/UPDATE(title)/DELETE、item
INSERT/DELETE、sort_index/position 重排 UPDATE）。
"""

import sqlite3
import uuid
from typing import Any

from lumirss.db_tx import transaction
from lumirss.itemref import parse_item_ref
from lumirss.storage import Database
from lumirss.util import utc_now
from lumirss.workspaces import (
    _MAX_NAME_LENGTH,
    WorkspaceNotFound,
    WorkspaceStore,
)

_MAX_SECTIONS_PER_WORKSPACE = 100
_MAX_ITEMS_PER_SECTION = 1000
_MAX_REORDER_BATCH = 500


class SectionInvalid(ValueError):
    """分节载荷非法（标题/引用/重排批次），映射 422。"""


class SectionNotFound(Exception):
    """分节不存在（或不属于该工作区），映射 404。"""


class SectionItemNotFound(Exception):
    """分节引用不存在（或条目不是工作区成员无法入节），映射 404。"""


class WorkspaceSectionStore:
    """Persistence for workspace_sections + workspace_section_items."""

    def __init__(self, db: Database, workspace_store: WorkspaceStore) -> None:
        self._db = db
        self._workspaces = workspace_store

    # -- section CRUD ------------------------------------------------------

    async def create_section(self, workspace_id: str, title: str) -> dict[str, Any]:
        clean = _validate_title(title)
        summary = await self._workspaces.get_workspace(workspace_id)
        if summary is None:
            raise WorkspaceNotFound(workspace_id)
        await self._db.migrate()
        count_row = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM workspace_sections WHERE workspace_id = ?",
            (workspace_id,),
        )
        if count_row is not None and int(count_row["n"]) >= _MAX_SECTIONS_PER_WORKSPACE:
            raise SectionInvalid(
                f"Too many sections (max {_MAX_SECTIONS_PER_WORKSPACE})."
            )
        row = await self._db.fetch_one(
            "SELECT COALESCE(MAX(sort_index), 0) AS p FROM workspace_sections WHERE workspace_id = ?",
            (workspace_id,),
        )
        sort_index = (int(row["p"]) if row is not None else 0) + 1
        section_id = f"sec-{uuid.uuid4().hex}"
        created_at = utc_now()
        await self._db.execute(
            "INSERT INTO workspace_sections (id, workspace_id, title, sort_index, created_at) VALUES (?, ?, ?, ?, ?)",
            (section_id, workspace_id, clean, sort_index, created_at),
        )
        return {
            "id": section_id,
            "workspaceId": workspace_id,
            "title": clean,
            "sortIndex": sort_index,
            "createdAt": created_at,
            "items": [],
        }

    async def rename_section(
        self, workspace_id: str, section_id: str, title: str
    ) -> dict[str, Any]:
        clean = _validate_title(title)
        row = await self._get_section_row(workspace_id, section_id)
        if row is None:
            raise SectionNotFound(section_id)
        await self._db.execute(
            "UPDATE workspace_sections SET title = ? WHERE id = ?",
            (clean, section_id),
        )
        return await self.get_section(workspace_id, section_id)

    async def delete_section(self, workspace_id: str, section_id: str) -> bool:
        """删除分节（成员引用行随 FK 级联消失）；False = 不存在。"""
        row = await self._get_section_row(workspace_id, section_id)
        if row is None:
            return False

        def _tx(conn: sqlite3.Connection) -> bool:
            conn.execute(
                "DELETE FROM workspace_section_items WHERE section_id = ?",
                (section_id,),
            )
            cursor = conn.execute(
                "DELETE FROM workspace_sections WHERE id = ?", (section_id,)
            )
            return cursor.rowcount > 0

        return bool(await transaction(self._db, _tx))

    # -- membership --------------------------------------------------------

    async def add_item(
        self, workspace_id: str, section_id: str, item_ref: str
    ) -> dict[str, Any]:
        """把一个工作区成员引用进分节（幂等；同一 ref 可进入多个分节）。

        条目不是工作区成员 → SectionItemNotFound（404，分节只组织既有
        成员）；重复加入同一分节 → 返回既有行原样（幂等重放）。"""
        try:
            clean_ref = parse_item_ref(item_ref).format()
        except ValueError as exc:
            raise SectionInvalid(str(exc)) from exc
        row = await self._get_section_row(workspace_id, section_id)
        if row is None:
            raise SectionNotFound(section_id)
        member = await self._db.fetch_one(
            "SELECT 1 FROM workspace_items WHERE workspace_id = ? AND item_ref = ?",
            (workspace_id, clean_ref),
        )
        if member is None:
            raise SectionItemNotFound(clean_ref)
        existing = await self._db.fetch_one(
            "SELECT section_id, item_ref, position, added_at FROM workspace_section_items WHERE section_id = ? AND item_ref = ?",
            (section_id, clean_ref),
        )
        if existing is not None:
            return self._item_view(existing, unresolved=False)
        pos_row = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM workspace_section_items WHERE section_id = ?",
            (section_id,),
        )
        count = int(pos_row["n"]) if pos_row is not None else 0
        if count >= _MAX_ITEMS_PER_SECTION:
            raise SectionInvalid(
                f"Too many items in one section (max {_MAX_ITEMS_PER_SECTION})."
            )
        now = utc_now()
        await self._db.execute(
            "INSERT INTO workspace_section_items (section_id, item_ref, position, added_at) VALUES (?, ?, ?, ?)",
            (section_id, clean_ref, count + 1, now),
        )
        return {"itemRef": clean_ref, "position": count + 1, "addedAt": now}

    async def remove_item(
        self, workspace_id: str, section_id: str, item_ref: str
    ) -> bool:
        """从分节移除一个引用（只拆引用，绝不删除工作区成员本身）。"""
        try:
            clean_ref = parse_item_ref(item_ref).format()
        except ValueError as exc:
            raise SectionInvalid(str(exc)) from exc
        row = await self._get_section_row(workspace_id, section_id)
        if row is None:
            raise SectionNotFound(section_id)

        def _tx(conn: sqlite3.Connection) -> bool:
            cursor = conn.execute(
                "DELETE FROM workspace_section_items WHERE section_id = ? AND item_ref = ?",
                (section_id, clean_ref),
            )
            return cursor.rowcount > 0

        return bool(await transaction(self._db, _tx))

    # -- listing + reorder ---------------------------------------------------

    async def get_section(
        self, workspace_id: str, section_id: str
    ) -> dict[str, Any]:
        rows = await self.list_sections(workspace_id)
        for section in rows:
            if section["id"] == section_id:
                return section
        raise SectionNotFound(section_id)

    async def list_sections(self, workspace_id: str) -> list[dict[str, Any]]:
        """分节大纲（sort_index 序），每节成员 position 序并诚实标记
        ``unresolved``（引用已不是工作区成员——绝不静默隐藏）。"""
        summary = await self._workspaces.get_workspace(workspace_id)
        if summary is None:
            raise WorkspaceNotFound(workspace_id)
        await self._db.migrate()
        section_rows = await self._db.fetch_all(
            "SELECT id, workspace_id, title, sort_index, created_at FROM workspace_sections WHERE workspace_id = ? ORDER BY sort_index ASC, created_at ASC, id ASC",
            (workspace_id,),
        )
        member_rows = await self._db.fetch_all(
            "SELECT item_ref FROM workspace_items WHERE workspace_id = ? LIMIT 5000",
            (workspace_id,),
        )
        members = {str(r["item_ref"]) for r in member_rows}
        sections: list[dict[str, Any]] = []
        for row in section_rows:
            item_rows = await self._db.fetch_all(
                "SELECT section_id, item_ref, position, added_at FROM workspace_section_items WHERE section_id = ? ORDER BY position ASC, item_ref ASC",
                (str(row["id"]),),
            )
            sections.append(
                {
                    "id": str(row["id"]),
                    "workspaceId": str(row["workspace_id"]),
                    "title": str(row["title"]),
                    "sortIndex": int(row["sort_index"]),
                    "createdAt": str(row["created_at"]),
                    "items": [
                        self._item_view(
                            item_row, unresolved=str(item_row["item_ref"]) not in members
                        )
                        for item_row in item_rows
                    ],
                }
            )
        return sections

    async def reorder_sections(
        self, workspace_id: str, section_ids: list[str]
    ) -> None:
        """分节顺序持久化（PUT 全量 1..N；遗漏的分节保持相对顺序垫后）。"""
        if not isinstance(section_ids, list) or not section_ids:
            raise SectionInvalid("sectionIds 必须是非空数组。")
        if len(section_ids) > _MAX_REORDER_BATCH:
            raise SectionInvalid(
                f"Reorder batch too large (max {_MAX_REORDER_BATCH})."
            )
        if len(set(section_ids)) != len(section_ids):
            raise SectionInvalid("sectionIds must not contain duplicates.")
        rows = await self._db.fetch_all(
            "SELECT id FROM workspace_sections WHERE workspace_id = ?",
            (workspace_id,),
        )
        known = {str(r["id"]) for r in rows}
        unknown = [sid for sid in section_ids if sid not in known]
        if unknown:
            raise SectionInvalid("sectionIds contains unknown sections.")

        def _tx(conn: sqlite3.Connection) -> None:
            for index, sid in enumerate(section_ids, start=1):
                conn.execute(
                    "UPDATE workspace_sections SET sort_index = ? WHERE id = ?",
                    (index, sid),
                )
            conn.execute(
                "UPDATE workspaces SET revision = revision + 1 WHERE id = ?",
                (workspace_id,),
            )

        await transaction(self._db, _tx)

    async def reorder_items(
        self, workspace_id: str, section_id: str, item_refs: list[str]
    ) -> None:
        """节内条目顺序持久化（PUT 全量 1..N；遗漏引用保持相对顺序垫后）。"""
        if not isinstance(item_refs, list) or not item_refs:
            raise SectionInvalid("itemRefs 必须是非空数组。")
        if len(item_refs) > _MAX_REORDER_BATCH:
            raise SectionInvalid(
                f"Reorder batch too large (max {_MAX_REORDER_BATCH})."
            )
        row = await self._get_section_row(workspace_id, section_id)
        if row is None:
            raise SectionNotFound(section_id)
        rows = await self._db.fetch_all(
            "SELECT item_ref FROM workspace_section_items WHERE section_id = ?",
            (section_id,),
        )
        known = {str(r["item_ref"]) for r in rows}
        unknown = [ref for ref in item_refs if ref not in known]
        if unknown:
            raise SectionInvalid("itemRefs contains refs not in this section.")

        def _tx(conn: sqlite3.Connection) -> None:
            for index, ref in enumerate(item_refs, start=1):
                conn.execute(
                    "UPDATE workspace_section_items SET position = ? WHERE section_id = ? AND item_ref = ?",
                    (index, section_id, ref),
                )

        await transaction(self._db, _tx)

    # -- compile support (N114) ----------------------------------------------

    async def sections_for_compile(
        self, workspace_id: str, section_ids: list[str] | None
    ) -> list[dict[str, Any]]:
        """汇编输入：全部分节（sort_index 序）或按 sectionIds 过滤（保持
        大纲顺序）。未知 sectionId → SectionInvalid（诚实拒绝，不静默跳）。"""
        sections = await self.list_sections(workspace_id)
        if section_ids is None:
            return sections
        if not isinstance(section_ids, list):
            raise SectionInvalid("sectionIds 必须是数组或 null。")
        known = {s["id"] for s in sections}
        unknown = [sid for sid in section_ids if sid not in known]
        if unknown:
            raise SectionInvalid("sectionIds contains unknown sections.")
        wanted = set(section_ids)
        return [s for s in sections if s["id"] in wanted]

    # -- helpers -------------------------------------------------------------

    async def _get_section_row(
        self, workspace_id: str, section_id: str
    ) -> Any:
        await self._db.migrate()
        return await self._db.fetch_one(
            "SELECT id, workspace_id, title, sort_index, created_at FROM workspace_sections WHERE workspace_id = ? AND id = ?",
            (workspace_id, section_id),
        )

    @staticmethod
    def _item_view(row: Any, *, unresolved: bool) -> dict[str, Any]:
        return {
            "itemRef": str(row["item_ref"]),
            "position": int(row["position"]),
            "addedAt": str(row["added_at"]),
            "unresolved": unresolved,
        }


def _validate_title(title: str) -> str:
    """分节标题与工作区名同界（非空、去首尾空白、≤100 字符）。"""
    if not isinstance(title, str):
        raise SectionInvalid("Section title must be a string.")
    clean = title.strip()
    if not clean:
        raise SectionInvalid("Section title must not be empty.")
    if len(clean) > _MAX_NAME_LENGTH:
        raise SectionInvalid("Section title is too long.")
    return clean
