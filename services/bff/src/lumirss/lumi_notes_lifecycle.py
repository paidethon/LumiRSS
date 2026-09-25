"""F090 Lumi 笔记全生命周期 —— 创建 / 读取 / 更新（乐观锁）/ 软删 / 恢复。

- 搜索接线与 knowledge_cards 同模式：ref=note:{id} 写入 search_library
  （kind='note'），软删即移除投影、恢复即重写；
- PATCH 带 baseUpdatedAt 乐观锁：不一致 → 409 note_conflict；
- 软删进回收站（lumi_notes.deleted_at；trash 端点扩展 kind=note）；
- 笔记绝不写入 Obsidian Vault（本模块零文件 IO——负向断言依赖）。

N079 笔记与事实分栏：sections_json 三栏（facts/interpretation/toVerify），搜索投影 body 以「[事实]/[个人解读]/[待核实]」标签渲染（AI 面类型标签）。

本文件直接写站点 4 处（INSERT / UPDATE / 软删 / 恢复）。
"""

import sqlite3
from typing import Any

from lumirss.db_tx import transaction
from lumirss.itemref import new_library_uuid
from lumirss.lumi_notes import content_hash_of
from lumirss.note_sections import (
    parse_sections,
    render_typed_sections,
    validate_sections,
)
from lumirss.search_library import LibrarySearchWriter
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_TITLE = 500
_MAX_CONTENT_BYTES = 100 * 1024


class NoteInvalid(ValueError):
    """笔记载荷非法（标题/正文长度/引用格式），映射 422。"""


class NoteConflict(Exception):
    """baseUpdatedAt 乐观锁冲突，映射 409。"""


class NoteNotFound(Exception):
    """笔记不存在（或已软删），映射 404。"""


def _dump_sections(sections: dict[str, list[str]]) -> str:
    import json as _json

    return _json.dumps(sections, ensure_ascii=False, separators=(",", ":"))


def _sections_empty(sections: dict[str, list[str]]) -> bool:
    return all(len(items) == 0 for items in sections.values())


class NoteLifecycleStore:
    def __init__(self, db: Database) -> None:
        self._db = db
        self._search = LibrarySearchWriter(db)

    @staticmethod
    def _validate_title(title: str) -> str:
        clean = str(title or "").strip()
        if not clean:
            raise NoteInvalid("标题不能为空。")
        if len(clean) > _MAX_TITLE:
            raise NoteInvalid("标题过长（≤500 字符）。")
        return clean

    @staticmethod
    def _validate_content(content_md: str) -> str:
        if not isinstance(content_md, str):
            raise NoteInvalid("contentMd 必须是字符串。")
        if len(content_md.encode("utf-8")) > _MAX_CONTENT_BYTES:
            raise NoteInvalid("contentMd 超过 100KB 上限。")
        return content_md

    def _index(
        self,
        conn: sqlite3.Connection,
        *,
        note_id: str,
        title: str,
        content: str,
        now: str,
        sections_rendered: str = "",
    ) -> None:
        """事务内同步投影（同 upsert_search_row 惯例）。

        N079：类型化分栏以「[事实]/[个人解读]/[待核实]」标签渲染进
        body —— AI 消费面（RAG/检索）读到的每条都带类型标签，绝不把
        个人判断表述为原文事实。"""
        body = content[:4000]
        if sections_rendered:
            body = f"{body}\n\n{sections_rendered}"[:5000]
        row = conn.execute(
            "SELECT ref FROM search_library WHERE ref = ?", (f"note:{note_id}",)
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO search_library (ref, kind, title, body, url, updated_at) VALUES (?, 'note', ?, ?, NULL, ?)",
                (f"note:{note_id}", title, body, now),
            )
        else:
            conn.execute(
                "UPDATE search_library SET kind = 'note', title = ?, body = ?, updated_at = ? WHERE ref = ?",
                (title, body, now, f"note:{note_id}"),
            )

    async def create_note(
        self,
        *,
        title: str,
        content_md: str,
        workspace_id: str | None,
        sections: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        clean_title = self._validate_title(title)
        clean_content = self._validate_content(content_md)
        clean_sections = validate_sections(sections)
        sections_json = (
            _dump_sections(clean_sections) if not _sections_empty(clean_sections) else None
        )
        await self._db.migrate()
        note_id = new_library_uuid()
        now = utc_now()

        def _tx(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO lumi_notes (uuid, title, content_md, workspace_id, sections_json, content_hash, source, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'manual', ?, ?)",
                (
                    note_id,
                    clean_title,
                    clean_content,
                    workspace_id,
                    sections_json,
                    content_hash_of(clean_content),
                    now,
                    now,
                ),
            )
            self._index(
                conn,
                note_id=note_id,
                title=clean_title,
                content=clean_content,
                now=now,
                sections_rendered=render_typed_sections(clean_sections),
            )

        await transaction(self._db, _tx)
        return {
            "uuid": note_id,
            "title": clean_title,
            "contentMd": clean_content,
            "workspaceId": workspace_id,
            "sections": clean_sections,
            "createdAt": now,
            "updatedAt": now,
        }

    async def get_note(self, note_id: str, *, include_deleted: bool = False) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT uuid, title, content_md, workspace_id, source, sections_json, created_at, updated_at, deleted_at FROM lumi_notes WHERE uuid = ?",
            (note_id,),
        )
        if row is None:
            return None
        if row["deleted_at"] is not None and not include_deleted:
            return None
        return {
            "uuid": str(row["uuid"]),
            "title": str(row["title"]),
            "contentMd": str(row["content_md"]),
            "workspaceId": row["workspace_id"],
            "source": str(row["source"] or "manual"),
            # N079：分栏（NULL/损坏 → 三空数组，诚实兼容旧数据）。
            "sections": parse_sections(row["sections_json"]),
            "createdAt": str(row["created_at"]),
            "updatedAt": str(row["updated_at"]),
            "deletedAt": row["deleted_at"],
        }

    async def update_note(
        self,
        note_id: str,
        *,
        title: str | None,
        content_md: str | None,
        base_updated_at: str | None,
        sections: dict[str, Any] | None = None,
        sections_given: bool = False,
    ) -> dict[str, Any]:
        current = await self.get_note(note_id)
        if current is None:
            raise NoteNotFound(note_id)
        if (
            base_updated_at is not None
            and str(base_updated_at) != current["updatedAt"]
        ):
            raise NoteConflict("笔记已被其他编辑更新，请刷新后重试。")
        clean_title = (
            self._validate_title(title) if title is not None else current["title"]
        )
        clean_content = (
            self._validate_content(content_md)
            if content_md is not None
            else current["contentMd"]
        )
        # N079：sentinel 语义——调用方未给键 = 不修改；给了 = 全量替换
        # （显式空对象/空栏 = 清空）。非法形状 → NoteSectionsInvalid（422）。
        clean_sections = (
            validate_sections(sections) if sections_given else current["sections"]
        )
        sections_json = (
            _dump_sections(clean_sections) if not _sections_empty(clean_sections) else None
        )
        now = utc_now()

        def _tx(conn: sqlite3.Connection) -> None:
            # N160：AI 答案证据笔记在覆盖前先把上一版推入修订台账
            # （provenance 保留：三段结构 + 人工修改的演进可回溯）。
            # 普通导入/手写笔记不入台账。
            if current.get("source") == "ai_answer":
                conn.execute(
                    "INSERT INTO lumi_note_revisions (note_id, title, content_md, origin, edited_at) VALUES (?, ?, ?, 'edit', ?)",
                    (note_id, current["title"], current["contentMd"], now),
                )
            conn.execute(
                "UPDATE lumi_notes SET title = ?, content_md = ?, sections_json = ?, content_hash = ?, updated_at = ? WHERE uuid = ?",
                (
                    clean_title,
                    clean_content,
                    sections_json,
                    content_hash_of(clean_content),
                    now,
                    note_id,
                ),
            )
            self._index(
                conn,
                note_id=note_id,
                title=clean_title,
                content=clean_content,
                now=now,
                sections_rendered=render_typed_sections(clean_sections),
            )

        await transaction(self._db, _tx)
        return {
            "uuid": note_id,
            "title": clean_title,
            "contentMd": clean_content,
            "workspaceId": current["workspaceId"],
            "sections": clean_sections,
            "createdAt": current["createdAt"],
            "updatedAt": now,
        }

    # -- N160 从答案生成证据笔记 ---------------------------------------------

    @staticmethod
    def build_answer_note_markdown(
        *,
        question: str,
        answer: str,
        excerpts: list[dict[str, str]],
    ) -> str:
        """三段式证据笔记正文：摘录（精确原文 + 引用）/ 生成内容
        （显式标注 AI 生成）/ 人工修改（空，编辑时由修订台账续记）。"""
        lines = ["## 摘录", ""]
        for excerpt in excerpts:
            ref = str(excerpt.get("ref") or "")
            title = str(excerpt.get("title") or "")
            text = str(excerpt.get("text") or "").strip()
            label = f"{title}（{ref}）" if title else ref
            lines.append(f"- 「{text}」 —— {label}")
        if len(lines) == 2:
            lines.append("-（无可用摘录）")
        lines.extend(
            [
                "",
                "## 生成内容",
                "",
                "> 以下内容由 AI 生成（基于上述摘录），未经人工核验。",
                "",
                answer.strip(),
                "",
                "## 人工修改",
                "",
            ]
        )
        return "\n".join(lines)

    async def create_answer_note(
        self,
        *,
        title: str,
        question: str,
        answer: str,
        excerpts: list[dict[str, str]],
        workspace_id: str | None,
    ) -> dict[str, Any]:
        """N160：把一次回答落成证据笔记（source='ai_answer'）。"""
        content_md = self.build_answer_note_markdown(
            question=question, answer=answer, excerpts=excerpts
        )
        clean_title = self._validate_title(title)
        self._validate_content(content_md)
        await self._db.migrate()
        note_id = new_library_uuid()
        now = utc_now()

        def _tx(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO lumi_notes (uuid, title, content_md, workspace_id, content_hash, source, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'ai_answer', ?, ?)",
                (
                    note_id,
                    clean_title,
                    content_md,
                    workspace_id,
                    content_hash_of(content_md),
                    now,
                    now,
                ),
            )
            self._index(
                conn, note_id=note_id, title=clean_title, content=content_md, now=now
            )

        await transaction(self._db, _tx)
        return {
            "uuid": note_id,
            "title": clean_title,
            "contentMd": content_md,
            "workspaceId": workspace_id,
            "createdAt": now,
            "updatedAt": now,
        }

    async def list_note_revisions(self, note_id: str) -> list[dict[str, Any]]:
        """N160：证据笔记的修订台账（新→旧；provenance 演进链）。"""
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, note_id, title, content_md, origin, edited_at FROM lumi_note_revisions WHERE note_id = ? ORDER BY edited_at DESC, id DESC LIMIT 100",
            (note_id,),
        )
        return [
            {
                "id": int(row["id"]),
                "noteId": str(row["note_id"]),
                "title": str(row["title"]),
                "contentMd": str(row["content_md"]),
                "origin": str(row["origin"]),
                "editedAt": str(row["edited_at"]),
            }
            for row in rows
        ]

    async def soft_delete_note(self, note_id: str) -> bool:
        """软删（回收站 kind=note）+ 移除搜索投影。"""
        current = await self.get_note(note_id)
        if current is None:
            return False

        def _tx(conn: sqlite3.Connection) -> int:
            cursor = conn.execute(
                "UPDATE lumi_notes SET deleted_at = ? WHERE uuid = ? AND deleted_at IS NULL",
                (utc_now(), note_id),
            )
            if cursor.rowcount:
                conn.execute(
                    "DELETE FROM search_library WHERE ref = ?", (f"note:{note_id}",)
                )
            return cursor.rowcount

        return bool(await transaction(self._db, _tx))

    async def restore_note(self, note_id: str) -> bool:
        current = await self.get_note(note_id, include_deleted=True)
        if current is None or current["deletedAt"] is None:
            return False

        def _tx(conn: sqlite3.Connection) -> int:
            cursor = conn.execute(
                "UPDATE lumi_notes SET deleted_at = NULL WHERE uuid = ? AND deleted_at IS NOT NULL",
                (note_id,),
            )
            if cursor.rowcount:
                self._index(
                    conn,
                    note_id=note_id,
                    title=current["title"],
                    content=current["contentMd"],
                    now=utc_now(),
                    sections_rendered=render_typed_sections(current["sections"]),
                )
            return cursor.rowcount

        return bool(await transaction(self._db, _tx))
