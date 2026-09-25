"""N105 工作区会话快照 —— 标签页/分组状态的命名快照与恢复。

- payload 只携带 ItemRef 引用与排序元数据（position/group/pinned +
  组顺序），绝不复制内容（ADR 0004：解析在读取时经 Source Registry）；
- 捕获覆盖全量成员（``list_items_full``，工作区容量上限），不走 API
  页上限——快照绝不静默截断；
- 恢复只作用于仍存在的成员：
  * ``reorder``：重排/重分组/重固定既有条目（快照外的成员原样保留）；
  * ``replace``：先移除快照外成员再应用（N102 固定保护——拒绝丢固定
    条目除非 ``force``）；
  * 快照里已消失的 ref 诚实上报 ``missing``，绝不复活（内容从未被
    复制，无物可复）；
- 恢复结果返回 diff 摘要 {restored, missing, kept, removed}；
- 每次 restore 真实写库时 bump workspaces.revision（P15 并发）；
- 工作区删除 → 快照行随 FK 级联消失。

本文件直接写站点 3 处（快照 INSERT / 恢复 UPDATE+DELETE / 组顺序
UPDATE）；成员行的删除与续读指针清除同事务（指针绝不悬空）。
"""

import json
import sqlite3
import uuid
from typing import Any

from lumirss.db_tx import transaction
from lumirss.storage import Database
from lumirss.util import utc_now
from lumirss.workspaces import (
    _MAX_NAME_LENGTH,
    WorkspaceInvalid,
    WorkspaceItemPinned,
    WorkspaceNotFound,
    WorkspaceStore,
)

_MAX_SNAPSHOTS_PER_WORKSPACE = 50
_RESTORE_MODES = ("reorder", "replace")
_PAYLOAD_VERSION = 1


class WorkspaceSnapshotNotFound(Exception):
    """No snapshot exists under the requested id（映射 404）。"""


class WorkspaceSnapshotStore:
    """Persistence for workspace_snapshots (N105)."""

    def __init__(self, db: Database, workspace_store: WorkspaceStore) -> None:
        self._db = db
        self._workspaces = workspace_store

    # -- capture / list / delete -------------------------------------------

    async def capture(self, workspace_id: str, name: str) -> dict[str, Any]:
        """捕获当前标签页/分组状态为命名快照（201）。"""
        clean = _validate_snapshot_name(name)
        summary = await self._workspaces.get_workspace(workspace_id)
        if summary is None:
            raise WorkspaceNotFound(workspace_id)
        items = await self._workspaces.list_items_full(workspace_id)
        group_order = await self._workspaces._stored_group_order(workspace_id)  # noqa: SLF001 — 同域协作
        count_row = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM workspace_snapshots WHERE workspace_id = ?",
            (workspace_id,),
        )
        if count_row is not None and int(count_row["n"]) >= _MAX_SNAPSHOTS_PER_WORKSPACE:
            raise WorkspaceInvalid(
                f"Too many snapshots (max {_MAX_SNAPSHOTS_PER_WORKSPACE})."
            )
        payload = {
            "version": _PAYLOAD_VERSION,
            "items": [
                {
                    "item_ref": item.item_ref,
                    "group": item.group_name,
                    "pinned": 1 if item.pinned else 0,
                    "position": item.position,
                }
                for item in items
            ],
            "group_order": group_order,
        }
        snapshot_id = f"snap-{uuid.uuid4().hex}"
        created_at = utc_now()
        await self._db.execute(
            "INSERT INTO workspace_snapshots (id, workspace_id, name, created_at, payload_json) VALUES (?, ?, ?, ?, ?)",
            (snapshot_id, workspace_id, clean, created_at, json.dumps(payload, ensure_ascii=False)),
        )
        return {
            "id": snapshot_id,
            "workspaceId": workspace_id,
            "name": clean,
            "createdAt": created_at,
            "itemCount": len(items),
        }

    async def list_snapshots(self, workspace_id: str) -> list[dict[str, Any]]:
        """快照列表（新→旧；itemCount 从 payload 派生）。"""
        await self._db.migrate()
        # rowid DESC = 插入序新→旧（created_at 秒级会并列，并列时随机
        # uuid 不保证先后；rowid 才是诚实的捕获顺序）。
        rows = await self._db.fetch_all(
            "SELECT id, workspace_id, name, created_at, payload_json FROM workspace_snapshots WHERE workspace_id = ? ORDER BY rowid DESC",
            (workspace_id,),
        )
        return [self._view(row) for row in rows]

    async def get_snapshot(self, workspace_id: str, snapshot_id: str) -> dict[str, Any] | None:
        row = await self._db.fetch_one(
            "SELECT id, workspace_id, name, created_at, payload_json FROM workspace_snapshots WHERE workspace_id = ? AND id = ?",
            (workspace_id, snapshot_id),
        )
        return self._view(row) if row is not None else None

    async def delete(self, workspace_id: str, snapshot_id: str) -> bool:
        """删除一个快照；False = 不存在。"""
        await self._db.migrate()

        def _tx(conn: sqlite3.Connection) -> bool:
            cursor = conn.execute(
                "DELETE FROM workspace_snapshots WHERE workspace_id = ? AND id = ?",
                (workspace_id, snapshot_id),
            )
            return cursor.rowcount > 0

        return await transaction(self._db, _tx)

    # -- diff (N115) ---------------------------------------------------------

    async def diff(
        self, workspace_id: str, snapshot_id_a: str, snapshot_id_b: str
    ) -> dict[str, Any]:
        """N115：两快照差异（纯只读，绝不触碰工作区成员行）。

        - ``added``：B 有 A 无（按 B 内 position 序）；
        - ``removed``：A 有 B 无（按 A 内 position 序）；
        - ``moved``：两者都有但 position 变化（按 B 序）；
        - ``groupChanges``：两者都有但分组归属变化（None = 未分组；
          按 B 序）。
        全部只携带 ref 与排序元数据——ref 的内容定位走既有 views/
        resolve 端点，本端点绝不解析内容。"""
        state_a = await self._load_state(workspace_id, snapshot_id_a)
        state_b = await self._load_state(workspace_id, snapshot_id_b)
        refs_a = {state["ref"]: state for state in state_a}
        refs_b = {state["ref"]: state for state in state_b}

        added = [
            state["ref"]
            for state in sorted(state_b, key=lambda s: s["position"])
            if state["ref"] not in refs_a
        ]
        removed = [
            state["ref"]
            for state in sorted(state_a, key=lambda s: s["position"])
            if state["ref"] not in refs_b
        ]
        moved = []
        group_changes = []
        for state in sorted(state_b, key=lambda s: s["position"]):
            other = refs_a.get(state["ref"])
            if other is None:
                continue
            if other["position"] != state["position"]:
                moved.append(
                    {
                        "ref": state["ref"],
                        "fromPos": other["position"],
                        "toPos": state["position"],
                    }
                )
            if other["group"] != state["group"]:
                group_changes.append(
                    {
                        "ref": state["ref"],
                        "from": other["group"],
                        "to": state["group"],
                    }
                )
        return {
            "snapshotA": snapshot_id_a,
            "snapshotB": snapshot_id_b,
            "added": added,
            "removed": removed,
            "moved": moved,
            "groupChanges": group_changes,
        }

    async def _load_state(
        self, workspace_id: str, snapshot_id: str
    ) -> list[dict[str, Any]]:
        """快照 payload → 排序元数据列表（与 restore 同一容错口径）。"""
        row = await self._db.fetch_one(
            "SELECT payload_json FROM workspace_snapshots WHERE workspace_id = ? AND id = ?",
            (workspace_id, snapshot_id),
        )
        if row is None:
            raise WorkspaceSnapshotNotFound(snapshot_id)
        try:
            payload = json.loads(str(row["payload_json"]))
        except ValueError as exc:
            raise WorkspaceInvalid("Snapshot payload is not valid JSON.") from exc
        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            raise WorkspaceInvalid("Snapshot payload is missing items.")
        state: list[dict[str, Any]] = []
        for entry in items:
            if not isinstance(entry, dict) or not isinstance(entry.get("item_ref"), str):
                continue
            state.append(
                {
                    "ref": str(entry["item_ref"]),
                    "group": (
                        str(entry["group"])
                        if isinstance(entry.get("group"), str)
                        else None
                    ),
                    "position": (
                        int(entry["position"])
                        if isinstance(entry.get("position"), int)
                        else 0
                    ),
                }
            )
        return state

    # -- restore -------------------------------------------------------------

    async def restore(
        self,
        workspace_id: str,
        snapshot_id: str,
        mode: str,
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        """恢复快照（reorder | replace），返回 diff 摘要。

        - ``restored``：快照 ref 成功重排/重分组/重固定的数量；
        - ``missing``：快照中已不在工作区的 ref（诚实上报，绝不复活）；
        - ``kept``：快照外、原样保留的成员数（replace 模式恒为 0）；
        - ``removed``：replace 模式被移除的 ref（reorder 恒为空）。
        """
        if mode not in _RESTORE_MODES:
            raise WorkspaceInvalid("mode must be 'reorder' or 'replace'.")
        summary = await self._workspaces.get_workspace(workspace_id)
        if summary is None:
            raise WorkspaceNotFound(workspace_id)
        row = await self._db.fetch_one(
            "SELECT payload_json FROM workspace_snapshots WHERE workspace_id = ? AND id = ?",
            (workspace_id, snapshot_id),
        )
        if row is None:
            raise WorkspaceSnapshotNotFound(snapshot_id)
        try:
            payload = json.loads(str(row["payload_json"]))
        except ValueError as exc:
            raise WorkspaceInvalid("Snapshot payload is not valid JSON.") from exc
        snapshot_items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(snapshot_items, list):
            raise WorkspaceInvalid("Snapshot payload is missing items.")
        group_order = (
            payload.get("group_order")
            if isinstance(payload, dict) and isinstance(payload.get("group_order"), list)
            else []
        )
        snapshot_state = []
        for entry in snapshot_items:
            if not isinstance(entry, dict) or not isinstance(entry.get("item_ref"), str):
                continue
            snapshot_state.append(
                {
                    "ref": str(entry["item_ref"]),
                    "group": (
                        str(entry["group"])
                        if isinstance(entry.get("group"), str)
                        else None
                    ),
                    "pinned": bool(entry.get("pinned")),
                }
            )

        current = await self._workspaces.list_items_full(workspace_id)
        current_by_ref = {item.item_ref: item for item in current}
        missing = [s["ref"] for s in snapshot_state if s["ref"] not in current_by_ref]
        snapshot_refs = {s["ref"] for s in snapshot_state}

        removed: list[str] = []
        kept = 0
        if mode == "replace":
            outsiders = [item for item in current if item.item_ref not in snapshot_refs]
            pinned_blockers = [item.item_ref for item in outsiders if item.pinned]
            if pinned_blockers and not force:
                raise WorkspaceItemPinned(workspace_id, pinned_blockers[0])
            removed = [item.item_ref for item in outsiders]
        else:
            kept = sum(1 for item in current if item.item_ref not in snapshot_refs)

        applied = [s for s in snapshot_state if s["ref"] in current_by_ref]

        def _tx(conn: sqlite3.Connection) -> None:
            if mode == "replace" and removed:
                for ref in removed:
                    conn.execute(
                        "DELETE FROM workspace_items WHERE workspace_id = ? AND item_ref = ?",
                        (workspace_id, ref),
                    )
                # 续读指针绝不悬空（与 remove_item 同契约）。
                for ref in removed:
                    conn.execute(
                        "DELETE FROM workspace_resume WHERE workspace_id = ? AND item_ref = ?",
                        (workspace_id, ref),
                    )
            # 快照成员按快照顺序拿 1..k；reorder 模式下快照外成员保持
            # 相对顺序垫在后面（与 reorder_items 同语义）。
            next_position = 0
            for state in applied:
                next_position += 1
                conn.execute(
                    "UPDATE workspace_items SET position = ?, group_name = ?, pinned = ? WHERE workspace_id = ? AND item_ref = ?",
                    (
                        next_position,
                        state["group"],
                        1 if state["pinned"] else 0,
                        workspace_id,
                        state["ref"],
                    ),
                )
            if mode == "reorder":
                tail = [
                    item.item_ref
                    for item in current
                    if item.item_ref not in snapshot_refs
                ]
                for ref in tail:
                    next_position += 1
                    conn.execute(
                        "UPDATE workspace_items SET position = ? WHERE workspace_id = ? AND item_ref = ?",
                        (next_position, workspace_id, ref),
                    )
            conn.execute(
                "UPDATE workspaces SET group_order_json = ?, revision = revision + 1 WHERE id = ?",
                (json.dumps([str(n) for n in group_order], ensure_ascii=False), workspace_id),
            )

        await transaction(self._db, _tx)
        return {
            "restored": len(applied),
            "missing": missing,
            "kept": kept,
            "removed": removed,
        }

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _view(row: Any) -> dict[str, Any]:
        """行 → API 视图（itemCount 从 payload 派生；payload 本体不出库）。"""
        try:
            payload = json.loads(str(row["payload_json"]))
        except ValueError:
            payload = {}
        items = payload.get("items") if isinstance(payload, dict) else None
        return {
            "id": str(row["id"]),
            "workspaceId": str(row["workspace_id"]),
            "name": str(row["name"]),
            "createdAt": str(row["created_at"]),
            "itemCount": len(items) if isinstance(items, list) else 0,
        }


def _validate_snapshot_name(name: str) -> str:
    """快照名与工作区名同界（非空、去首尾空白、≤100 字符）。"""
    if not isinstance(name, str):
        raise WorkspaceInvalid("Snapshot name must be a string.")
    clean = name.strip()
    if not clean:
        raise WorkspaceInvalid("Snapshot name must not be empty.")
    if len(clean) > _MAX_NAME_LENGTH:
        raise WorkspaceInvalid("Snapshot name is too long.")
    return clean
