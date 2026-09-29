"""NEW-239 标注冲突解决器 —— 两台设备改同一条笔记的并排解决。

模型（版本列承载 last-writer 冲突检测）：

- ``lumi_notes.version`` 单调整数（创建=1，NEW-239 通道每次成功写入
  +1）。既有 PATCH 的 baseUpdatedAt 乐观锁仍然有效（两道闸互不替代）。
- 设备提交编辑（POST /conflicted-edits）：baseVersion 命中 → 直接
  应用并 bump；过期 → 409，编辑**暂存**为 pending（另一台设备的
  工作绝不静默丢弃），响应带服务端当前版（并排素材）。
- 解决（POST /conflicted-edits/{id}/resolve）：
  * keep_server  —— 保留服务端版，丢弃 pending；
  * keep_pending —— 应用 pending；被覆盖的服务端版先入 note_versions
    （origin='conflict'，历史不覆盖）；
  * keep_both    —— 服务端版不动，pending 内容另存为新笔记
    （标题加「（冲突副本）」）；
  * merged       —— 应用用户合并后的 title/contentMd（必填）；服务端
    版同样先入快照。
- 全部解决动作写 note_conflict_log 台账。
"""

import sqlite3
import uuid as _uuid
from typing import Any

from lumirss.db_tx import transaction
from lumirss.itemref import new_library_uuid
from lumirss.lumi_notes import content_hash_of
from lumirss.search_library import upsert_search_row
from lumirss.storage import Database
from lumirss.util import utc_now

MAX_TITLE = 500
MAX_CONTENT_BYTES = 100 * 1024
RESOLUTIONS = ("keep_server", "keep_pending", "keep_both", "merged")


class ConflictInvalid(ValueError):
    """负载非法（标题/正文/解决方式），映射 422。"""


class ConflictNotFound(Exception):
    """笔记或 pending 编辑不存在（或已解决），映射 404。"""


class NoteConflictResolver:
    def __init__(self, db: Database) -> None:
        self._db = db

    # -- 内部 --------------------------------------------------------------

    async def _note_row(self, note_id: str) -> dict[str, Any]:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT uuid, title, content_md, workspace_id, version, created_at, updated_at, deleted_at "
            "FROM lumi_notes WHERE uuid = ?",
            (note_id,),
        )
        if row is None or row["deleted_at"] is not None:
            raise ConflictNotFound(note_id)
        return dict(row)

    @staticmethod
    def _validate_title(title: Any) -> str:
        clean = str(title or "").strip()
        if not clean:
            raise ConflictInvalid("标题不能为空。")
        if len(clean) > MAX_TITLE:
            raise ConflictInvalid("标题过长（≤500 字符）。")
        return clean

    @staticmethod
    def _validate_content(content: Any) -> str:
        if not isinstance(content, str):
            raise ConflictInvalid("contentMd 必须是字符串。")
        if len(content.encode("utf-8")) > MAX_CONTENT_BYTES:
            raise ConflictInvalid("contentMd 超过 100KB 上限。")
        return content

    @staticmethod
    def _server_view(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "noteId": str(row["uuid"]),
            "title": str(row["title"]),
            "contentMd": str(row["content_md"]),
            "version": int(row["version"]),
            "updatedAt": str(row["updated_at"]),
        }

    # -- 提交编辑（冲突检测 + 暂存） ---------------------------------------

    async def submit_edit(
        self,
        note_id: str,
        *,
        title: Any,
        content_md: Any,
        base_version: Any,
        device_label: str | None,
    ) -> dict[str, Any]:
        """设备提交编辑：命中 → 应用（bump version）；过期 → 409 语义
        （ConflictStale），pending 落库等待并排解决。"""
        row = await self._note_row(note_id)
        clean_title = self._validate_title(title)
        clean_content = self._validate_content(content_md)
        if not isinstance(base_version, int) or isinstance(base_version, bool):
            raise ConflictInvalid("baseVersion 必须是整数。")
        label = str(device_label or "").strip()[:100]
        current_version = int(row["version"])

        if base_version == current_version:
            now = utc_now()

            def _tx(conn: sqlite3.Connection) -> None:
                conn.execute(
                    "UPDATE lumi_notes SET title = ?, content_md = ?, content_hash = ?, version = version + 1, updated_at = ? WHERE uuid = ?",
                    (clean_title, clean_content, content_hash_of(clean_content), now, note_id),
                )
                upsert_search_row(
                    conn,
                    ref=f"note:{note_id}",
                    kind="note",
                    title=clean_title,
                    body=clean_content[:4000],
                    url=None,
                    now=now,
                )

            await transaction(self._db, _tx)
            updated = await self._note_row(note_id)
            return {"outcome": "applied", "note": self._server_view(updated)}

        # 过期：pending 暂存（永不静默丢弃另一台设备的编辑）
        pending_id = str(_uuid.uuid4())
        now = utc_now()
        await self._db.execute(
            "INSERT INTO note_pending_edits (id, note_id, base_version, title, content_md, device_label, status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
            (pending_id, note_id, base_version, clean_title, clean_content, label, now),
        )
        raise ConflictStale(
            pending_id=pending_id,
            server=self._server_view(row),
            incoming={"title": clean_title, "contentMd": clean_content, "deviceLabel": label},
        )

    # -- pending 列表（并排素材） ------------------------------------------

    async def pending_edits(self, note_id: str) -> dict[str, Any]:
        row = await self._note_row(note_id)
        rows = await self._db.fetch_all(
            "SELECT id, base_version, title, content_md, device_label, status, created_at, resolved_at "
            "FROM note_pending_edits WHERE note_id = ? AND status = 'pending' "
            "ORDER BY created_at ASC, rowid ASC",
            (note_id,),
        )
        return {
            "server": self._server_view(row),
            "pending": [
                {
                    "id": str(r["id"]),
                    "baseVersion": int(r["base_version"]),
                    "title": str(r["title"]),
                    "contentMd": str(r["content_md"]),
                    "deviceLabel": str(r["device_label"] or ""),
                    "createdAt": str(r["created_at"]),
                }
                for r in rows
            ],
        }

    # -- 解决 ---------------------------------------------------------------

    async def resolve(
        self,
        note_id: str,
        pending_id: str,
        *,
        resolution: Any,
        merged_title: Any = None,
        merged_content: Any = None,
    ) -> dict[str, Any]:
        clean_resolution = str(resolution or "").strip()
        if clean_resolution not in RESOLUTIONS:
            raise ConflictInvalid(
                f"resolution 必须是 {'/'.join(RESOLUTIONS)} 之一。"
            )
        row = await self._note_row(note_id)
        pending = await self._db.fetch_one(
            "SELECT * FROM note_pending_edits WHERE id = ? AND note_id = ?",
            (pending_id, note_id),
        )
        if pending is None or pending["status"] != "pending":
            raise ConflictNotFound(pending_id)
        now = utc_now()
        log_id = str(_uuid.uuid4())
        snapshot_id: str | None = None
        new_note_id: str | None = None

        if clean_resolution == "keep_server":
            resulting = self._server_view(row)

            def _tx(conn: sqlite3.Connection) -> None:
                conn.execute(
                    "UPDATE note_pending_edits SET status = 'resolved', resolution = 'keep_server', resolved_at = ? WHERE id = ?",
                    (now, pending_id),
                )
                conn.execute(
                    "INSERT INTO note_conflict_log (id, note_id, pending_edit_id, resolution, resolved_at) VALUES (?, ?, ?, 'keep_server', ?)",
                    (log_id, note_id, pending_id, now),
                )

            await transaction(self._db, _tx)

        elif clean_resolution in ("keep_pending", "merged"):
            if clean_resolution == "keep_pending":
                final_title = str(pending["title"])
                final_content = str(pending["content_md"])
            else:
                final_title = self._validate_title(merged_title)
                final_content = self._validate_content(merged_content)
            snapshot_id = str(_uuid.uuid4())

            def _tx(conn: sqlite3.Connection) -> None:
                # 被覆盖的服务端版先入快照（origin='conflict'，历史不覆盖）
                conn.execute(
                    "INSERT INTO note_versions (id, note_id, title, content_md, origin, created_at) VALUES (?, ?, ?, ?, 'conflict', ?)",
                    (snapshot_id, note_id, str(row["title"]), str(row["content_md"]), now),
                )
                conn.execute(
                    "UPDATE lumi_notes SET title = ?, content_md = ?, content_hash = ?, version = version + 1, updated_at = ? WHERE uuid = ?",
                    (final_title, final_content, content_hash_of(final_content), now, note_id),
                )
                upsert_search_row(
                    conn,
                    ref=f"note:{note_id}",
                    kind="note",
                    title=final_title,
                    body=final_content[:4000],
                    url=None,
                    now=now,
                )
                conn.execute(
                    "UPDATE note_pending_edits SET status = 'resolved', resolution = ?, resolved_at = ? WHERE id = ?",
                    (clean_resolution, now, pending_id),
                )
                conn.execute(
                    "INSERT INTO note_conflict_log (id, note_id, pending_edit_id, resolution, resolved_at) VALUES (?, ?, ?, ?, ?)",
                    (log_id, note_id, pending_id, clean_resolution, now),
                )

            await transaction(self._db, _tx)
            resulting = self._server_view(await self._note_row(note_id))

        else:  # keep_both
            final_title = str(pending["title"]).strip() or "未命名"
            copy_title = f"{final_title}（冲突副本）"
            new_note_id = new_library_uuid()

            def _tx(conn: sqlite3.Connection) -> None:
                conn.execute(
                    "INSERT INTO lumi_notes (uuid, title, content_md, workspace_id, sections_json, content_hash, source, created_at, updated_at, version) VALUES (?, ?, ?, ?, NULL, ?, 'manual', ?, ?, 1)",
                    (
                        new_note_id,
                        copy_title,
                        str(pending["content_md"]),
                        row["workspace_id"],
                        content_hash_of(str(pending["content_md"])),
                        now,
                        now,
                    ),
                )
                upsert_search_row(
                    conn,
                    ref=f"note:{new_note_id}",
                    kind="note",
                    title=copy_title,
                    body=str(pending["content_md"])[:4000],
                    url=None,
                    now=now,
                )
                conn.execute(
                    "UPDATE note_pending_edits SET status = 'resolved', resolution = 'keep_both', resolved_at = ? WHERE id = ?",
                    (now, pending_id),
                )
                conn.execute(
                    "INSERT INTO note_conflict_log (id, note_id, pending_edit_id, resolution, resolved_at) VALUES (?, ?, ?, 'keep_both', ?)",
                    (log_id, note_id, pending_id, now),
                )

            await transaction(self._db, _tx)
            resulting = self._server_view(await self._note_row(note_id))

        return {
            "resolution": clean_resolution,
            "note": resulting,
            "conflictSnapshotVersionId": snapshot_id,
            "copyNoteId": new_note_id,
            "resolvedAt": now,
        }

    async def conflict_log(self, note_id: str) -> list[dict[str, Any]]:
        row = await self._note_row(note_id)
        del row
        rows = await self._db.fetch_all(
            "SELECT id, pending_edit_id, resolution, resolved_at FROM note_conflict_log "
            "WHERE note_id = ? ORDER BY resolved_at DESC, rowid DESC",
            (note_id,),
        )
        return [
            {
                "id": str(r["id"]),
                "pendingEditId": str(r["pending_edit_id"]),
                "resolution": str(r["resolution"]),
                "resolvedAt": str(r["resolved_at"]),
            }
            for r in rows
        ]


class ConflictStale(Exception):
    """提交的编辑基于过期版本（409 语义）。携带 pending id 与并排素材。"""

    def __init__(self, *, pending_id: str, server: dict[str, Any], incoming: dict[str, Any]) -> None:
        super().__init__("笔记已被另一台设备更新，请并排解决冲突。")
        self.pending_id = pending_id
        self.server = server
        self.incoming = incoming
