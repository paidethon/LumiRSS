"""NEW-216 集合快照差异 —— 资料集合（工作区）成员的命名快照、两次快照
的新增/移除差异、按选择恢复成员。

- 快照只存 ItemRef 引用列表（不复制内容，ADR 0004：解析在读取时经
  Source Registry）；捕获用全量成员（工作区容量上限内），绝不静默截断；
- diff(A, B)：added = 仅在 B / removed = 仅在 A（纯集合运算，有界）；
- 恢复：按用户勾选的 refs 逐条校验 ref 形状；仍不可解析（内容已删）的
  ref 不阻塞整批，进 ``skipped`` 如实回报（恢复后由 NEW-218 检查器
  诚实标记——绝不悄悄复活或悄悄丢弃）；已存在的 ref 跳过（幂等）；
  追加到集合尾部（position 顺延），单事务完成并 bump 工作区 revision。
"""

import json
import sqlite3
import uuid
from typing import Any

from lumirss.db_tx import transaction
from lumirss.itemref import parse_item_ref
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_SNAPSHOTS_PER_WS = 50
_MAX_NAME = 100
_MAX_RESTORE_BATCH = 500
_DIFF_BOUND = 500
_WS_CAPACITY = 5000


class CollectionSnapshotInvalid(ValueError):
    """快照载荷非法（名字/数量/引用形状），映射 422。"""


class CollectionSnapshotNotFound(Exception):
    """快照不存在（或不属于该集合），映射 404。"""


def _clean_name(name: str) -> str:
    clean = name.strip()
    if not clean or len(clean) > _MAX_NAME:
        raise CollectionSnapshotInvalid(f"快照名必须是 1-{_MAX_NAME} 个字符。")
    return clean


class CollectionSnapshotStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def _require_workspace(self, workspace_id: str) -> None:
        row = await self._db.fetch_one(
            "SELECT id FROM workspaces WHERE id = ?", (workspace_id,)
        )
        if row is None:
            raise CollectionSnapshotInvalid(f"集合不存在：{workspace_id}。")

    async def capture(self, workspace_id: str, name: str) -> dict[str, Any]:
        clean = _clean_name(name)
        await self._db.migrate()
        await self._require_workspace(workspace_id)
        rows = await self._db.fetch_all(
            "SELECT item_ref FROM workspace_items WHERE workspace_id = ? ORDER BY position ASC LIMIT ?",
            (workspace_id, _WS_CAPACITY + 1),
        )
        refs = [str(r["item_ref"]) for r in rows[:_WS_CAPACITY]]
        truncated = len(rows) > _WS_CAPACITY
        count = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM new216_collection_snapshots WHERE workspace_id = ?",
            (workspace_id,),
        )
        if count is not None and int(count["n"]) >= _MAX_SNAPSHOTS_PER_WS:
            raise CollectionSnapshotInvalid(
                f"该集合的快照数量已达上限（{_MAX_SNAPSHOTS_PER_WS}）。"
            )
        snapshot_id = str(uuid.uuid4())
        await self._db.execute(
            "INSERT INTO new216_collection_snapshots (id, workspace_id, name, refs_json, ref_count, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (snapshot_id, workspace_id, clean, json.dumps(refs, ensure_ascii=False), len(refs), utc_now()),
        )
        return {
            "id": snapshot_id,
            "workspaceId": workspace_id,
            "name": clean,
            "refCount": len(refs),
            "truncated": truncated,
            "createdAt": utc_now(),
        }

    async def list_snapshots(self, workspace_id: str) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, name, ref_count, created_at FROM new216_collection_snapshots WHERE workspace_id = ? ORDER BY created_at DESC, id DESC",
            (workspace_id,),
        )
        return [
            {
                "id": str(r["id"]),
                "workspaceId": workspace_id,
                "name": str(r["name"]),
                "refCount": int(r["ref_count"]),
                "createdAt": str(r["created_at"]),
            }
            for r in rows
        ]

    async def delete(self, workspace_id: str, snapshot_id: str) -> bool:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id FROM new216_collection_snapshots WHERE id = ? AND workspace_id = ?",
            (snapshot_id, workspace_id),
        )
        if row is None:
            return False
        await self._db.execute(
            "DELETE FROM new216_collection_snapshots WHERE id = ? AND workspace_id = ?",
            (snapshot_id, workspace_id),
        )
        return True

    async def _refs_of(self, workspace_id: str, snapshot_id: str) -> list[str]:
        row = await self._db.fetch_one(
            "SELECT refs_json FROM new216_collection_snapshots WHERE id = ? AND workspace_id = ?",
            (snapshot_id, workspace_id),
        )
        if row is None:
            raise CollectionSnapshotNotFound(snapshot_id)
        try:
            refs = json.loads(str(row["refs_json"]))
        except ValueError as exc:
            raise CollectionSnapshotInvalid("快照数据损坏。") from exc
        if not isinstance(refs, list):
            raise CollectionSnapshotInvalid("快照数据损坏。")
        return [str(r) for r in refs]

    async def diff(
        self, workspace_id: str, snapshot_a: str, snapshot_b: str
    ) -> dict[str, Any]:
        """两次快照差异：added = 仅 B 有 / removed = 仅 A 有（各自有界）。"""
        await self._db.migrate()
        refs_a = set(await self._refs_of(workspace_id, snapshot_a))
        refs_b = set(await self._refs_of(workspace_id, snapshot_b))
        added_all = sorted(refs_b - refs_a)
        removed_all = sorted(refs_a - refs_b)
        return {
            "workspaceId": workspace_id,
            "a": snapshot_a,
            "b": snapshot_b,
            "added": added_all[:_DIFF_BOUND],
            "removed": removed_all[:_DIFF_BOUND],
            "addedTotal": len(added_all),
            "removedTotal": len(removed_all),
        }

    async def restore(
        self, workspace_id: str, snapshot_id: str, refs: list[str]
    ) -> dict[str, Any]:
        """按勾选恢复成员：缺失的追加到尾部；已存在跳过；形状非法计数。"""
        if not 1 <= len(refs) <= _MAX_RESTORE_BATCH:
            raise CollectionSnapshotInvalid(f"恢复数量必须是 1-{_MAX_RESTORE_BATCH}。")
        await self._db.migrate()
        snapshot_refs = set(await self._refs_of(workspace_id, snapshot_id))
        cleaned: list[str] = []
        invalid = 0
        for ref in refs:
            try:
                cleaned.append(parse_item_ref(ref).format())
            except ValueError:
                invalid += 1
        not_in_snapshot = [ref for ref in cleaned if ref not in snapshot_refs]
        if not cleaned:
            raise CollectionSnapshotInvalid("所选引用形状全部非法，拒绝恢复。")
        if not_in_snapshot:
            raise CollectionSnapshotInvalid(
                "所选引用不属于这张快照，拒绝恢复。"
            )

        def _restore(conn: sqlite3.Connection) -> dict[str, Any]:
            conn.execute("BEGIN IMMEDIATE")
            existing = {
                str(r["item_ref"])
                for r in conn.execute(
                    "SELECT item_ref FROM workspace_items WHERE workspace_id = ?",
                    (workspace_id,),
                ).fetchall()
            }
            max_row = conn.execute(
                "SELECT COALESCE(MAX(position), 0) AS p FROM workspace_items WHERE workspace_id = ?",
                (workspace_id,),
            ).fetchone()
            position = int(max_row["p"]) if max_row is not None else 0
            restored: list[str] = []
            skipped_existing = 0
            for ref in cleaned:
                if ref in existing:
                    skipped_existing += 1
                    continue
                position += 1
                conn.execute(
                    "INSERT INTO workspace_items (workspace_id, item_ref, position, added_at) VALUES (?, ?, ?, ?)",
                    (workspace_id, ref, position, utc_now()),
                )
                conn.execute(
                    "UPDATE workspaces SET revision = revision + 1 WHERE id = ?",
                    (workspace_id,),
                )
                restored.append(ref)
            return {
                "workspaceId": workspace_id,
                "snapshotId": snapshot_id,
                "restored": restored,
                "skippedExisting": skipped_existing,
                "invalidRefs": invalid,
            }

        return await transaction(self._db, _restore)
