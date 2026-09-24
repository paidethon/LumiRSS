"""Workspace store (phase2 M1) — ordered ItemRef collections.

A workspace is a named, ordered set of typed ItemRefs
(``rss:<entryRef>`` / ``library:<uuid>``). Content is never copied:
resolving refs to views happens through :mod:`lumirss.sources` at read
time. ``read-later`` is a reserved workspace id seeded by migration 0008;
the API refuses to delete or rename it. All SQL is single-line inline
literals with bound params.

N101 标签页分组：成员可携带可选 ``group_name``（NULL = 未分组，呈现为
隐式前置组）。组成员关系完全由 ``workspace_items.group_name`` 派生；
组的顺序存 ``workspaces.group_order_json``（组名有序数组，JSON 列方案
——无需 workspace_groups 表，也不产生孤儿行）。跨工作区串扰在结构上
不可能：每一行都带 workspace_id。

N102 固定标签页：成员可 ``pinned``。固定条目在分组视图中排所有组之前
（仍按 position 排序）；移除固定条目需显式 ``force``（否则 409
workspace_item_pinned）。
"""

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

from lumirss.db_tx import transaction
from lumirss.itemref import parse_item_ref
from lumirss.opaque_ref import decode_opaque_ref, encode_opaque_ref
from lumirss.storage import Database
from lumirss.util import utc_now

RESERVED_WORKSPACE_ID = "read-later"
_MAX_NAME_LENGTH = 100
_MAX_WORKSPACES = 200
_MAX_ITEMS_PER_WORKSPACE = 5000
_MAX_REORDER_BATCH = 500
_DEFAULT_ITEM_LIMIT = 200
_MAX_ITEM_LIMIT = 500
# N101：分组标签上限（单组名 / 单工作区组数 / 顺序数组长度）。
_MAX_GROUP_NAME_LENGTH = 64
_MAX_GROUPS = 100


class WorkspaceInvalid(ValueError):
    """Workspace payload failed validation (name, refs, batch size)."""


class WorkspaceNotFound(Exception):
    """No workspace exists under the requested id."""


class ReservedWorkspaceError(Exception):
    """The operation targets the immutable read-later workspace."""


class WorkspaceItemPinned(Exception):
    """N102：目标条目已固定——移除/替换需显式 force（映射 409）。

    防误删：固定是用户显式表达的「别丢」意图，静默移除等于撕毁约定。"""

    def __init__(self, workspace_id: str, item_ref: str) -> None:
        self.workspace_id = workspace_id
        self.item_ref = item_ref
        super().__init__(
            "Item is pinned; retry with force to remove it anyway."
        )


class WorkspaceRevisionConflict(Exception):
    """P15：乐观并发拒绝——工作区条目域已被另一设备改动（映射 409）。

    ``current_revision`` 随错误体返回，客户端重取后可用新 revision 重试。"""

    def __init__(self, workspace_id: str, current_revision: int) -> None:
        self.workspace_id = workspace_id
        self.current_revision = current_revision
        super().__init__(
            f"Workspace was updated on another device (revision {current_revision}); refetch and retry."
        )


@dataclass(frozen=True)
class WorkspaceSummary:
    id: str
    name: str
    position: int
    item_count: int
    reserved: bool
    description: str = ""
    archived: bool = False
    archived_at: str | None = None
    # P15：条目域变更计数（add/remove/reorder/status 时 +1）；重排序的
    # 乐观并发以此为凭据。
    revision: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "position": self.position,
            "itemCount": self.item_count,
            "reserved": self.reserved,
            "description": self.description,
            "archived": self.archived,
            "archivedAt": self.archived_at,
            "revision": self.revision,
        }


@dataclass(frozen=True)
class WorkspaceItem:
    """One workspace member: the typed ref plus ordering metadata.

    N101/N102：``group_name``（None = 未分组）与 ``pinned`` 是同一行的
    增量元数据；排序语义不变（position 升序）。"""

    item_ref: str
    position: int
    added_at: str
    group_name: str | None = None
    pinned: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "itemRef": self.item_ref,
            "position": self.position,
            "addedAt": self.added_at,
            "groupName": self.group_name,
            "pinned": self.pinned,
        }


@dataclass(frozen=True)
class WorkspaceResume:
    """P15：「上次看到哪」指针（每工作区一行）。

    ``position_at_save`` 是保存时刻该条目的位置快照——仅用于呈现
    「当时读到第几条」，条目后续被重排时快照不跟随（诚实标注保存时刻）。"""

    item_ref: str
    position_at_save: int | None
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "itemRef": self.item_ref,
            "positionAtSave": self.position_at_save,
            "updatedAt": self.updated_at,
        }


class WorkspaceStore:
    """Persistence for workspaces + workspace_items."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # -- workspace CRUD ----------------------------------------------------

    async def create_workspace(self, name: str, description: str = "") -> WorkspaceSummary:
        clean = _validate_name(name)
        clean_description = _validate_description(description)
        count = await self._count_workspaces()
        if count >= _MAX_WORKSPACES:
            raise WorkspaceInvalid(f"Too many workspaces (max {_MAX_WORKSPACES}).")
        await self._db.migrate()
        existing = await self._db.fetch_one("SELECT id FROM workspaces WHERE name = ?", (clean,))
        if existing is not None:
            raise WorkspaceInvalid("A workspace with this name already exists.")
        row = await self._db.fetch_one("SELECT COALESCE(MAX(position), 0) AS p FROM workspaces")
        next_position = (int(row["p"]) if row is not None else 0) + 1
        workspace_id = f"ws-{utc_now_compact()}-{next_position:04d}"
        await self._db.execute(
            "INSERT INTO workspaces (id, name, description, position, created_at) VALUES (?, ?, ?, ?, ?)",
            (workspace_id, clean, clean_description, next_position, utc_now()),
        )
        return WorkspaceSummary(
            id=workspace_id,
            name=clean,
            position=next_position,
            item_count=0,
            reserved=False,
            description=clean_description,
        )

    async def _count_workspaces(self) -> int:
        await self._db.migrate()
        row = await self._db.fetch_one("SELECT COUNT(*) AS n FROM workspaces")
        return int(row["n"]) if row is not None else 0

    async def list_workspaces(
        self, *, include_archived: bool = False
    ) -> list[WorkspaceSummary]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT w.id, w.name, w.description, w.position, w.archived_at, w.revision, COUNT(wi.item_ref) AS n"
            " FROM workspaces w LEFT JOIN workspace_items wi ON wi.workspace_id = w.id"
            " WHERE (? = 1 OR w.archived_at IS NULL)"
            " GROUP BY w.id, w.name, w.description, w.position, w.archived_at, w.revision ORDER BY w.position ASC, w.id ASC",
            (1 if include_archived else 0,),
        )
        return [
            WorkspaceSummary(
                id=str(row["id"]),
                name=str(row["name"]),
                position=int(row["position"]),
                item_count=int(row["n"]),
                reserved=str(row["id"]) == RESERVED_WORKSPACE_ID,
                description=str(row["description"] or ""),
                archived=row["archived_at"] is not None,
                archived_at=str(row["archived_at"]) if row["archived_at"] else None,
                revision=int(row["revision"]),
            )
            for row in rows
        ]

    async def get_workspace(self, workspace_id: str) -> WorkspaceSummary | None:
        # F084：深链接可命中已归档工作区（archived 过滤只作用于列表）。
        for summary in await self.list_workspaces(include_archived=True):
            if summary.id == workspace_id:
                return summary
        return None

    async def rename_workspace(
        self, workspace_id: str, name: str, description: str | None = None
    ) -> WorkspaceSummary:
        if workspace_id == RESERVED_WORKSPACE_ID:
            raise ReservedWorkspaceError(RESERVED_WORKSPACE_ID)
        clean = _validate_name(name)
        await self._db.migrate()
        row = await self._db.fetch_one("SELECT id FROM workspaces WHERE id = ?", (workspace_id,))
        if row is None:
            raise WorkspaceNotFound(workspace_id)
        if description is None:
            await self._db.execute("UPDATE workspaces SET name = ? WHERE id = ?", (clean, workspace_id))
        else:
            await self._db.execute(
                "UPDATE workspaces SET name = ?, description = ? WHERE id = ?",
                (clean, _validate_description(description), workspace_id),
            )
        updated = await self.get_workspace(workspace_id)
        assert updated is not None
        return updated

    async def delete_workspace(self, workspace_id: str) -> bool:
        """Delete a workspace and its membership rows atomically (pool #45);
        False when absent."""
        if workspace_id == RESERVED_WORKSPACE_ID:
            raise ReservedWorkspaceError(RESERVED_WORKSPACE_ID)
        await self._db.migrate()
        row = await self._db.fetch_one("SELECT id FROM workspaces WHERE id = ?", (workspace_id,))
        if row is None:
            return False

        def _delete(conn: sqlite3.Connection) -> None:
            conn.execute("DELETE FROM workspace_items WHERE workspace_id = ?", (workspace_id,))
            conn.execute("DELETE FROM workspaces WHERE id = ?", (workspace_id,))

        await transaction(self._db, _delete)
        return True

    # -- membership --------------------------------------------------------

    @staticmethod
    def _item_from_row(row: Any) -> WorkspaceItem:
        """Row → WorkspaceItem（0083 起行携带 group_name / pinned）。"""
        return WorkspaceItem(
            item_ref=str(row["item_ref"]),
            position=int(row["position"]),
            added_at=str(row["added_at"]),
            group_name=(
                str(row["group_name"]) if row["group_name"] is not None else None
            ),
            pinned=bool(row["pinned"]),
        )

    async def add_item(
        self, workspace_id: str, item_ref: str, group_name: str | None = None
    ) -> WorkspaceItem:
        """Idempotent add: an existing (workspace, ref) pair returns as-is.

        N101：``group_name`` 可选（None = 未分组）；幂等重放返回既有行
        原样（组归属以既有行为准——改组走 set_item_group）。
        """
        await self._db.migrate()
        clean_group = _validate_group_name(group_name)
        row = await self._db.fetch_one("SELECT id FROM workspaces WHERE id = ?", (workspace_id,))
        if row is None:
            raise WorkspaceNotFound(workspace_id)
        parsed = parse_item_ref(item_ref)
        existing = await self._db.fetch_one(
            "SELECT item_ref, position, added_at, group_name, pinned FROM workspace_items WHERE workspace_id = ? AND item_ref = ?",
            (workspace_id, parsed.format()),
        )
        if existing is not None:
            return self._item_from_row(existing)
        count_row = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM workspace_items WHERE workspace_id = ?",
            (workspace_id,),
        )
        count = int(count_row["n"]) if count_row is not None else 0
        if count >= _MAX_ITEMS_PER_WORKSPACE:
            raise WorkspaceInvalid(
                f"Workspace is full (max {_MAX_ITEMS_PER_WORKSPACE} items)."
            )
        pos_row = await self._db.fetch_one(
            "SELECT COALESCE(MAX(position), 0) AS p FROM workspace_items WHERE workspace_id = ?",
            (workspace_id,),
        )
        next_position = (int(pos_row["p"]) if pos_row is not None else 0) + 1
        now = utc_now()

        def _insert(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO workspace_items (workspace_id, item_ref, position, added_at, group_name, pinned) VALUES (?, ?, ?, ?, ?, 0)",
                (workspace_id, parsed.format(), next_position, now, clean_group),
            )
            # P15：真实新增才 bump（幂等重放不制造并发噪声）。
            conn.execute(
                "UPDATE workspaces SET revision = revision + 1 WHERE id = ?",
                (workspace_id,),
            )

        try:
            await transaction(self._db, _insert)
        except sqlite3.IntegrityError:
            # Concurrent add of the same ref: converge on the unique pair.
            existing = await self._db.fetch_one(
                "SELECT item_ref, position, added_at, group_name, pinned FROM workspace_items WHERE workspace_id = ? AND item_ref = ?",
                (workspace_id, parsed.format()),
            )
            if existing is None:
                raise
            return self._item_from_row(existing)
        return WorkspaceItem(
            item_ref=parsed.format(),
            position=next_position,
            added_at=now,
            group_name=clean_group,
        )

    async def remove_item(
        self, workspace_id: str, item_ref: str, *, force: bool = False
    ) -> bool:
        """Remove one member; False when the pair does not exist.

        N102：固定条目拒绝静默移除——``force=False`` 且行 pinned →
        WorkspaceItemPinned（409），绝不半删。``force=True`` 才放行。

        P15：删除同时（同一事务）清掉指向该条目的续读指针并 bump
        revision——指针绝不悬空指向已移出的条目。"""
        await self._db.migrate()
        parsed = parse_item_ref(item_ref)

        def _tx(conn: sqlite3.Connection) -> bool:
            row = conn.execute(
                "SELECT pinned FROM workspace_items WHERE workspace_id = ? AND item_ref = ?",
                (workspace_id, parsed.format()),
            ).fetchone()
            if row is None:
                return False
            if bool(row["pinned"]) and not force:
                raise WorkspaceItemPinned(workspace_id, parsed.format())
            conn.execute(
                "DELETE FROM workspace_items WHERE workspace_id = ? AND item_ref = ?",
                (workspace_id, parsed.format()),
            )
            conn.execute(
                "DELETE FROM workspace_resume WHERE workspace_id = ? AND item_ref = ?",
                (workspace_id, parsed.format()),
            )
            conn.execute(
                "UPDATE workspaces SET revision = revision + 1 WHERE id = ?",
                (workspace_id,),
            )
            return True

        return await transaction(self._db, _tx)

    async def list_items(
        self, workspace_id: str, *, limit: int = _DEFAULT_ITEM_LIMIT
    ) -> list[WorkspaceItem]:
        if limit < 1 or limit > _MAX_ITEM_LIMIT:
            raise WorkspaceInvalid(f"limit must be between 1 and {_MAX_ITEM_LIMIT}.")
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT item_ref, position, added_at, group_name, pinned FROM workspace_items WHERE workspace_id = ? ORDER BY position ASC, item_ref ASC LIMIT ?",
            (workspace_id, limit),
        )
        return [self._item_from_row(row) for row in rows]

    async def list_items_desc(
        self,
        workspace_id: str,
        *,
        cursor: str | None = None,
        limit: int = 25,
        order: str = "newest",
    ) -> tuple[list[WorkspaceItem], str | None]:
        """Keyset page over the reserved workspace's members by add time
        (read-later timeline, P0-01); ``order`` is ``newest`` (default,
        historical) or ``oldest`` (pool #14).

        Cursor is an opaque envelope over (added_at, item_ref, order) —
        a cursor is only valid for the order it was issued under;
        legacy two-field cursors mean ``newest``. An absent workspace or
        an invalid cursor raises WorkspaceInvalid.
        """
        if limit < 1 or limit > _MAX_ITEM_LIMIT:
            raise WorkspaceInvalid(f"limit must be between 1 and {_MAX_ITEM_LIMIT}.")
        if order not in ("newest", "oldest"):
            raise WorkspaceInvalid("order must be 'newest' or 'oldest'.")
        await self._db.migrate()
        now_iso = utc_now()
        row = await self._db.fetch_one(
            "SELECT id FROM workspaces WHERE id = ?", (workspace_id,)
        )
        if row is None:
            raise WorkspaceNotFound(workspace_id)
        key = _decode_timeline_cursor(cursor) if cursor else None
        if key is not None and key[2] != order:
            raise WorkspaceInvalid(
                "timeline cursor belongs to a different sort order."
            )
        key_added = key[0] if key else None
        key_ref = key[1] if key else None
        # F19：延后（snoozed_until > now）的行不进入时间线；到期自动回。
        if order == "oldest":
            sql = "SELECT item_ref, position, added_at, group_name, pinned FROM workspace_items WHERE workspace_id = ? AND (snoozed_until IS NULL OR snoozed_until <= ?) AND (? IS NULL OR added_at > ? OR (added_at = ? AND item_ref > ?)) ORDER BY added_at ASC, item_ref ASC LIMIT ?"
        else:
            sql = "SELECT item_ref, position, added_at, group_name, pinned FROM workspace_items WHERE workspace_id = ? AND (snoozed_until IS NULL OR snoozed_until <= ?) AND (? IS NULL OR added_at < ? OR (added_at = ? AND item_ref < ?)) ORDER BY added_at DESC, item_ref DESC LIMIT ?"
        rows = await self._db.fetch_all(
            sql,
            (workspace_id, now_iso, key_added, key_added, key_added, key_ref, limit + 1),
        )
        has_more = len(rows) > limit
        rows = rows[:limit]
        items = [self._item_from_row(r) for r in rows]
        next_cursor = None
        if has_more and items:
            last = items[-1]
            next_cursor = _encode_timeline_cursor(last.added_at, last.item_ref, order)
        return items, next_cursor

    async def snooze_item(
        self, workspace_id: str, item_ref: str, until: str | None
    ) -> bool:
        """F19：延后/取消延后一个保存项（until=None = 取消延后）。

        行保留、成员关系不变；只影响 read-later 时间线的可见性。
        Returns False when the item is not a member of the workspace."""
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT item_ref FROM workspace_items WHERE workspace_id = ? AND item_ref = ?",
            (workspace_id, item_ref),
        )
        if row is None:
            return False
        await self._db.execute(
            "UPDATE workspace_items SET snoozed_until = ? WHERE workspace_id = ? AND item_ref = ?",
            (until, workspace_id, item_ref),
        )
        return True

    async def list_snoozed(self, workspace_id: str) -> list[tuple[str, str]]:
        """当前处于延后状态的 (item_ref, snoozed_until) 列表（新→旧）。"""
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT item_ref, snoozed_until FROM workspace_items WHERE workspace_id = ? AND snoozed_until IS NOT NULL ORDER BY snoozed_until ASC, item_ref ASC",
            (workspace_id,),
        )
        return [(str(r["item_ref"]), str(r["snoozed_until"])) for r in rows]

    async def reorder_items(
        self,
        workspace_id: str,
        ordered_refs: list[str],
        expected_revision: int | None = None,
    ) -> int:
        """Assign positions 1..N for the given refs (bounded batch).

        Refs not included keep their relative order after the moved block;
        unknown refs are refused rather than silently ignored.

        P15：``expected_revision``（If-Match 式，可选——旧调用方不传则
        行为不变）在写事务内先比对，不匹配 → WorkspaceRevisionConflict
        （409 + 当前 revision），绝不静默覆盖另一设备的排序。
        """
        if not ordered_refs:
            raise WorkspaceInvalid("Reorder batch must not be empty.")
        if len(ordered_refs) > _MAX_REORDER_BATCH:
            raise WorkspaceInvalid(
                f"Reorder batch too large (max {_MAX_REORDER_BATCH})."
            )
        parsed: list[str] = [parse_item_ref(ref).format() for ref in ordered_refs]
        # Validation reads the full membership (bounded by the workspace
        # cap, not the default page limit — pages would falsely reject
        # refs living past the first page of a long workspace).
        rows = await self._db.fetch_all(
            "SELECT item_ref FROM workspace_items WHERE workspace_id = ? LIMIT ?",
            (workspace_id, _MAX_ITEMS_PER_WORKSPACE),
        )
        known = {str(row["item_ref"]) for row in rows}
        unknown = [ref for ref in parsed if ref not in known]
        if unknown:
            raise WorkspaceInvalid("Reorder contains refs not in the workspace.")

        def _tx(conn: sqlite3.Connection) -> int:
            if expected_revision is not None:
                row = conn.execute(
                    "SELECT revision FROM workspaces WHERE id = ?",
                    (workspace_id,),
                ).fetchone()
                current = int(row["revision"]) if row is not None else None
                if current is None:
                    raise WorkspaceNotFound(workspace_id)
                if current != expected_revision:
                    raise WorkspaceRevisionConflict(workspace_id, current)
            moved = 0
            for index, ref in enumerate(parsed, start=1):
                cursor = conn.execute(
                    "UPDATE workspace_items SET position = ? WHERE workspace_id = ? AND item_ref = ?",
                    (index, workspace_id, ref),
                )
                moved += cursor.rowcount
            conn.execute(
                "UPDATE workspaces SET revision = revision + 1 WHERE id = ?",
                (workspace_id,),
            )
            return moved

        return await transaction(self._db, _tx)

    # -- groups + pinning (N101 / N102) --------------------------------------

    async def list_items_full(self, workspace_id: str) -> list[WorkspaceItem]:
        """全量成员（position 序，上限 = 工作区容量）。

        供快照捕获/恢复使用：不走 API 页上限（500），快照绝不静默截断。"""
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT item_ref, position, added_at, group_name, pinned FROM workspace_items WHERE workspace_id = ? ORDER BY position ASC, item_ref ASC LIMIT ?",
            (workspace_id, _MAX_ITEMS_PER_WORKSPACE),
        )
        return [self._item_from_row(row) for row in rows]

    async def set_item_group(
        self, workspace_id: str, item_ref: str, group_name: str | None
    ) -> WorkspaceItem | None:
        """N101：移动条目到分组（``None`` = 移回未分组隐式前置组）。

        条目不是成员 → None（路由层映射 404）；组归属真实变化才 bump
        revision（幂等重放不制造跨设备 409 噪声）。"""
        await self._db.migrate()
        parsed = parse_item_ref(item_ref)
        clean = _validate_group_name(group_name)
        current = await self._db.fetch_one(
            "SELECT group_name FROM workspace_items WHERE workspace_id = ? AND item_ref = ?",
            (workspace_id, parsed.format()),
        )
        if current is None:
            return None
        changed = (
            str(current["group_name"]) if current["group_name"] is not None else None
        ) != clean
        if changed:
            def _update(conn: sqlite3.Connection) -> None:
                conn.execute(
                    "UPDATE workspace_items SET group_name = ? WHERE workspace_id = ? AND item_ref = ?",
                    (clean, workspace_id, parsed.format()),
                )
                conn.execute(
                    "UPDATE workspaces SET revision = revision + 1 WHERE id = ?",
                    (workspace_id,),
                )

            await transaction(self._db, _update)
        row = await self._db.fetch_one(
            "SELECT item_ref, position, added_at, group_name, pinned FROM workspace_items WHERE workspace_id = ? AND item_ref = ?",
            (workspace_id, parsed.format()),
        )
        assert row is not None
        return self._item_from_row(row)

    async def set_item_pinned(
        self, workspace_id: str, item_ref: str, pinned: bool
    ) -> WorkspaceItem | None:
        """N102：设置固定标记（set 语义，非 toggle；幂等重放不 bump）。

        条目不是成员 → None（路由层映射 404）。"""
        await self._db.migrate()
        parsed = parse_item_ref(item_ref)
        current = await self._db.fetch_one(
            "SELECT pinned FROM workspace_items WHERE workspace_id = ? AND item_ref = ?",
            (workspace_id, parsed.format()),
        )
        if current is None:
            return None
        changed = bool(current["pinned"]) != pinned
        if changed:
            def _update(conn: sqlite3.Connection) -> None:
                conn.execute(
                    "UPDATE workspace_items SET pinned = ? WHERE workspace_id = ? AND item_ref = ?",
                    (1 if pinned else 0, workspace_id, parsed.format()),
                )
                conn.execute(
                    "UPDATE workspaces SET revision = revision + 1 WHERE id = ?",
                    (workspace_id,),
                )

            await transaction(self._db, _update)
        row = await self._db.fetch_one(
            "SELECT item_ref, position, added_at, group_name, pinned FROM workspace_items WHERE workspace_id = ? AND item_ref = ?",
            (workspace_id, parsed.format()),
        )
        assert row is not None
        return self._item_from_row(row)

    async def _stored_group_order(self, workspace_id: str) -> list[str]:
        """group_order_json 的容错解析（损坏/非列表 → []，绝不 500）。"""
        row = await self._db.fetch_one(
            "SELECT group_order_json FROM workspaces WHERE id = ?", (workspace_id,)
        )
        if row is None:
            raise WorkspaceNotFound(workspace_id)
        try:
            parsed = json.loads(str(row["group_order_json"] or "[]"))
        except ValueError:
            return []
        if not isinstance(parsed, list):
            return []
        return [str(name) for name in parsed if isinstance(name, str)]

    async def group_overview(
        self, workspace_id: str, *, limit: int = _DEFAULT_ITEM_LIMIT
    ) -> dict[str, Any]:
        """N101：分组视图（呈现层派生，不落第二份成员关系）。

        - 固定区（pinned，position 序）在最前——N102「固定排所有组之前」；
        - 未分组 = 隐式前置组（name=None，非空才出现）；
        - 命名组按 group_order_json 排序，未列入顺序的组按组名字典序追加；
        - 组内条目按 position 序；分组作用于前 ``limit`` 个成员（与列表
          页上限一致）。
        """
        if limit < 1 or limit > _MAX_ITEM_LIMIT:
            raise WorkspaceInvalid(f"limit must be between 1 and {_MAX_ITEM_LIMIT}.")
        await self._db.migrate()
        summary = await self.get_workspace(workspace_id)
        if summary is None:
            raise WorkspaceNotFound(workspace_id)
        items = await self.list_items(workspace_id, limit=limit)
        order = await self._stored_group_order(workspace_id)

        pinned = [item for item in items if item.pinned]
        ungrouped = [item for item in items if item.group_name is None and not item.pinned]
        named: dict[str, list[WorkspaceItem]] = {}
        for item in items:
            if item.group_name is not None and not item.pinned:
                named.setdefault(item.group_name, []).append(item)
        ordered_names = [name for name in order if name in named]
        ordered_names += sorted(set(named) - set(ordered_names))

        groups: list[dict[str, Any]] = []
        if ungrouped:
            groups.append({"name": None, "items": ungrouped})
        groups.extend({"name": name, "items": named[name]} for name in ordered_names)
        return {
            "workspaceId": workspace_id,
            "revision": summary.revision,
            "groupOrder": order,
            "pinned": pinned,
            "groups": groups,
        }

    async def set_group_order(self, workspace_id: str, order: list[str]) -> list[str]:
        """N101：设置命名组的呈现顺序（PUT 幂等；不创建、不重命名组）。

        - 每个名字必须是当前真实存在的组（有成员的 group_name）——顺序
          只重排既有组，诚实拒绝未知名字（400）；
        - 顺序真实变化才 bump revision（幂等重放不制造并发噪声）。
        """
        if not isinstance(order, list):
            raise WorkspaceInvalid("order must be a list of group names.")
        if len(order) > _MAX_GROUPS:
            raise WorkspaceInvalid(f"Too many groups (max {_MAX_GROUPS}).")
        cleaned = [_validate_group_name(name) for name in order]
        if len(set(cleaned)) != len(cleaned):
            raise WorkspaceInvalid("order must not contain duplicate group names.")
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT group_order_json FROM workspaces WHERE id = ?", (workspace_id,)
        )
        if row is None:
            raise WorkspaceNotFound(workspace_id)
        rows = await self._db.fetch_all(
            "SELECT DISTINCT group_name FROM workspace_items WHERE workspace_id = ? AND group_name IS NOT NULL",
            (workspace_id,),
        )
        existing = {str(r["group_name"]) for r in rows}
        unknown = [name for name in cleaned if name not in existing]
        if unknown:
            raise WorkspaceInvalid(
                "order contains groups that do not exist in this workspace."
            )
        current = await self._stored_group_order(workspace_id)
        if current == cleaned:
            return cleaned

        def _update(conn: sqlite3.Connection) -> None:
            conn.execute(
                "UPDATE workspaces SET group_order_json = ?, revision = revision + 1 WHERE id = ?",
                (json.dumps(cleaned, ensure_ascii=False), workspace_id),
            )

        await transaction(self._db, _update)
        return cleaned

    # -- resume pointer (P15) ----------------------------------------------

    async def get_resume(self, workspace_id: str) -> WorkspaceResume | None:
        """当前续读指针；无（或工作区不存在）返回 None。"""
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT item_ref, position_at_save, updated_at FROM workspace_resume WHERE workspace_id = ?",
            (workspace_id,),
        )
        if row is None:
            return None
        return WorkspaceResume(
            item_ref=str(row["item_ref"]),
            position_at_save=(
                int(row["position_at_save"])
                if row["position_at_save"] is not None
                else None
            ),
            updated_at=str(row["updated_at"]),
        )

    async def set_resume(self, workspace_id: str, item_ref: str) -> WorkspaceResume:
        """保存/覆盖续读指针（PUT 幂等 upsert）。

        校验与 add_item 同构：工作区不存在 → WorkspaceNotFound；
        ref 非法 → InvalidItemRef；条目不是成员 → WorkspaceNotFound。
        不 bump revision：指针是每设备的阅读光标，不是共享条目状态。"""
        await self._db.migrate()
        row = await self._db.fetch_one("SELECT id FROM workspaces WHERE id = ?", (workspace_id,))
        if row is None:
            raise WorkspaceNotFound(workspace_id)
        parsed = parse_item_ref(item_ref)
        member = await self._db.fetch_one(
            "SELECT position FROM workspace_items WHERE workspace_id = ? AND item_ref = ?",
            (workspace_id, parsed.format()),
        )
        if member is None:
            raise WorkspaceNotFound(f"workspace item {item_ref}")
        position = int(member["position"])
        now = utc_now()

        def _upsert(conn: sqlite3.Connection) -> None:
            existing = conn.execute(
                "SELECT workspace_id FROM workspace_resume WHERE workspace_id = ?",
                (workspace_id,),
            ).fetchone()
            if existing is None:
                conn.execute(
                    "INSERT INTO workspace_resume (workspace_id, item_ref, position_at_save, updated_at) VALUES (?, ?, ?, ?)",
                    (workspace_id, parsed.format(), position, now),
                )
            else:
                conn.execute(
                    "UPDATE workspace_resume SET item_ref = ?, position_at_save = ?, updated_at = ? WHERE workspace_id = ?",
                    (parsed.format(), position, now, workspace_id),
                )

        await transaction(self._db, _upsert)
        return WorkspaceResume(
            item_ref=parsed.format(),
            position_at_save=position,
            updated_at=now,
        )


def utc_now_compact() -> str:
    return utc_now().replace("-", "").replace(":", "").replace("+00:00", "")


_DESC_CURSOR_PREFIX = "c1ws."
_MAX_DESC_CURSOR_LENGTH = 1024


def _encode_timeline_cursor(added_at: str, item_ref: str, order: str) -> str:
    payload = json.dumps([added_at, item_ref, order], separators=(",", ":"))
    return encode_opaque_ref(_DESC_CURSOR_PREFIX, payload)


def _decode_timeline_cursor(cursor: str) -> tuple[str, str, str]:
    """Returns (added_at, item_ref, order); legacy two-field payloads are
    the historical ``newest`` order."""
    payload = decode_opaque_ref(
        cursor,
        prefix=_DESC_CURSOR_PREFIX,
        max_length=_MAX_DESC_CURSOR_LENGTH,
        error_type=WorkspaceInvalid,
        description="workspace timeline cursor",
    )
    try:
        parsed = json.loads(payload)
    except ValueError as exc:
        raise WorkspaceInvalid("timeline cursor payload is not valid JSON.") from exc
    if (
        isinstance(parsed, list)
        and len(parsed) == 3
        and all(isinstance(v, str) for v in parsed)
    ):
        added_at, item_ref, order = parsed
        if order not in ("newest", "oldest"):
            raise WorkspaceInvalid("timeline cursor order is not recognized.")
        return added_at, item_ref, order
    if (
        isinstance(parsed, list)
        and len(parsed) == 2
        and all(isinstance(v, str) for v in parsed)
    ):
        return parsed[0], parsed[1], "newest"
    raise WorkspaceInvalid("timeline cursor payload is not a key pair.")


def _validate_group_name(name: str | None) -> str | None:
    """N101：分组标签校验——None 保留（未分组）；空白串归一为 None；
    其余去首尾空白、上限 64 字符。"""
    if name is None:
        return None
    if not isinstance(name, str):
        raise WorkspaceInvalid("Group name must be a string or null.")
    clean = name.strip()
    if not clean:
        return None
    if len(clean) > _MAX_GROUP_NAME_LENGTH:
        raise WorkspaceInvalid(
            f"Group name is too long (max {_MAX_GROUP_NAME_LENGTH} chars)."
        )
    return clean


def _validate_name(name: str) -> str:
    if not isinstance(name, str):
        raise WorkspaceInvalid("Workspace name must be a string.")
    clean = name.strip()
    if not clean:
        raise WorkspaceInvalid("Workspace name must not be empty.")
    if len(clean) > _MAX_NAME_LENGTH:
        raise WorkspaceInvalid("Workspace name is too long.")
    return clean


def _validate_description(description: str) -> str:
    """F25：纯文本说明；空白归一、上限 500 字符（None 视为空由调用方处理）。"""
    if not isinstance(description, str):
        raise WorkspaceInvalid("Workspace description must be a string.")
    clean = " ".join(description.split())
    if len(clean) > 500:
        raise WorkspaceInvalid("Workspace description is too long (max 500 chars).")
    return clean
