"""F020 本地 Markdown 批量入库 —— lumi_notes 存储（SQL 唯一入口）。

最小实体：入库（逐文件校验、content_hash 幂等）与列表（摘要首行）。
编辑 / 关联 / 删除恢复由后续波次（F090）补全——本模块刻意不提供。
"""

import hashlib
from dataclasses import dataclass
from typing import Any

from lumirss.itemref import new_library_uuid
from lumirss.util import utc_now

MAX_FILE_BYTES = 200 * 1024  # ≤200KB/文件
MAX_BATCH_FILES = 50  # ≤50 文件/批


@dataclass
class LumiNoteView:
    uuid: str
    title: str
    workspace_id: str | None
    created_at: str
    updated_at: str


class NoteImportInvalid(Exception):
    """单个文件的导入校验失败（reason 为稳定短码）。"""


def content_hash_of(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _first_line(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()
        if line:
            return line
    return ""


class LumiNotesStore:
    def __init__(self, db: Any) -> None:
        self._db = db

    async def import_note(
        self,
        *,
        name: str,
        content: str,
        workspace_id: str | None,
    ) -> tuple[LumiNoteView, bool]:
        """入库一个文件；content_hash 命中已有笔记 → (既有, False) skipped。

        重名不同内容共存（uuid 主键、无唯一标题约束）；标题取文件名
        去扩展名（正文不解析——诚实最小实体）。
        """
        await self._db.migrate()
        digest = content_hash_of(content)
        existing = await self._db.fetch_one(
            "SELECT uuid FROM lumi_notes WHERE content_hash = ?",
            (digest,),
        )
        now = utc_now()
        if existing is not None:
            uuid = str(existing["uuid"])
            row = await self._db.fetch_one(
                "SELECT uuid, title, workspace_id, created_at, updated_at FROM lumi_notes WHERE uuid = ?",
                (uuid,),
            )
            assert row is not None
            return LumiNoteView(
                uuid=str(row["uuid"]),
                title=str(row["title"]),
                workspace_id=row["workspace_id"],
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
            ), False

        uuid = new_library_uuid()
        title = name.removesuffix(".md").removesuffix(".markdown").strip() or name
        await self._db.execute(
            "INSERT INTO lumi_notes (uuid, title, content_md, workspace_id, content_hash, source, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'import', ?, ?)",
            (uuid, title, content, workspace_id, digest, now, now),
        )
        view = LumiNoteView(
            uuid=uuid, title=title, workspace_id=workspace_id,
            created_at=now, updated_at=now,
        )
        return view, True

    async def list_notes(
        self, workspace_id: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """列表（title/updated_at/摘要首行；workspace_id 过滤可选）。"""
        await self._db.migrate()
        if workspace_id is None:
            rows = await self._db.fetch_all(
                "SELECT uuid, title, content_md, workspace_id, created_at, updated_at FROM lumi_notes WHERE deleted_at IS NULL ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            )
        else:
            rows = await self._db.fetch_all(
                "SELECT uuid, title, content_md, workspace_id, created_at, updated_at FROM lumi_notes WHERE deleted_at IS NULL AND workspace_id = ? ORDER BY updated_at DESC LIMIT ?",
                (workspace_id, limit),
            )
        return [
            {
                "uuid": str(row["uuid"]),
                "title": str(row["title"]),
                "workspaceId": row["workspace_id"],
                "excerpt": _first_line(str(row["content_md"]))[:160],
                "createdAt": str(row["created_at"]),
                "updatedAt": str(row["updated_at"]),
            }
            for row in rows
        ]

