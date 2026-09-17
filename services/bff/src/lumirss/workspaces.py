"""Workspace store (phase2 M1) — ordered ItemRef collections.

A workspace is a named, ordered set of typed ItemRefs
(``rss:<entryRef>`` / ``library:<uuid>``). Content is never copied:
resolving refs to views happens through :mod:`lumirss.sources` at read
time. ``read-later`` is a reserved workspace id seeded by migration 0008;
the API refuses to delete or rename it. All SQL is single-line inline
literals with bound params.
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


class WorkspaceInvalid(ValueError):
    """Workspace payload failed validation (name, refs, batch size)."""


class WorkspaceNotFound(Exception):
    """No workspace exists under the requested id."""


class ReservedWorkspaceError(Exception):
    """The operation targets the immutable read-later workspace."""


@dataclass(frozen=True)
class WorkspaceSummary:
    id: str
    name: str
    position: int
    item_count: int
    reserved: bool
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "position": self.position,
            "itemCount": self.item_count,
            "reserved": self.reserved,
            "description": self.description,
        }


@dataclass(frozen=True)
class WorkspaceItem:
    """One workspace member: the typed ref plus ordering metadata."""

    item_ref: str
    position: int
    added_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "itemRef": self.item_ref,
            "position": self.position,
            "addedAt": self.added_at,
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

    async def list_workspaces(self) -> list[WorkspaceSummary]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT w.id, w.name, w.description, w.position, COUNT(wi.item_ref) AS n"
            " FROM workspaces w LEFT JOIN workspace_items wi ON wi.workspace_id = w.id"
            " GROUP BY w.id, w.name, w.description, w.position ORDER BY w.position ASC, w.id ASC"
        )
        return [
            WorkspaceSummary(
                id=str(row["id"]),
                name=str(row["name"]),
                position=int(row["position"]),
                item_count=int(row["n"]),
                reserved=str(row["id"]) == RESERVED_WORKSPACE_ID,
                description=str(row["description"] or ""),
            )
            for row in rows
        ]

    async def get_workspace(self, workspace_id: str) -> WorkspaceSummary | None:
        for summary in await self.list_workspaces():
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

    async def add_item(self, workspace_id: str, item_ref: str) -> WorkspaceItem:
        """Idempotent add: an existing (workspace, ref) pair returns as-is."""
        await self._db.migrate()
        row = await self._db.fetch_one("SELECT id FROM workspaces WHERE id = ?", (workspace_id,))
        if row is None:
            raise WorkspaceNotFound(workspace_id)
        parsed = parse_item_ref(item_ref)
        existing = await self._db.fetch_one(
            "SELECT item_ref, position, added_at FROM workspace_items WHERE workspace_id = ? AND item_ref = ?",
            (workspace_id, parsed.format()),
        )
        if existing is not None:
            return WorkspaceItem(
                item_ref=str(existing["item_ref"]),
                position=int(existing["position"]),
                added_at=str(existing["added_at"]),
            )
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
        try:
            await self._db.execute(
                "INSERT INTO workspace_items (workspace_id, item_ref, position, added_at) VALUES (?, ?, ?, ?)",
                (workspace_id, parsed.format(), next_position, now),
            )
        except sqlite3.IntegrityError:
            # Concurrent add of the same ref: converge on the unique pair.
            existing = await self._db.fetch_one(
                "SELECT item_ref, position, added_at FROM workspace_items WHERE workspace_id = ? AND item_ref = ?",
                (workspace_id, parsed.format()),
            )
            if existing is None:
                raise
            return WorkspaceItem(
                item_ref=str(existing["item_ref"]),
                position=int(existing["position"]),
                added_at=str(existing["added_at"]),
            )
        return WorkspaceItem(
            item_ref=parsed.format(), position=next_position, added_at=now
        )

    async def remove_item(self, workspace_id: str, item_ref: str) -> bool:
        """Remove one member; False when the pair does not exist."""
        await self._db.migrate()
        parsed = parse_item_ref(item_ref)
        row = await self._db.fetch_one(
            "SELECT item_ref FROM workspace_items WHERE workspace_id = ? AND item_ref = ?",
            (workspace_id, parsed.format()),
        )
        if row is None:
            return False
        await self._db.execute(
            "DELETE FROM workspace_items WHERE workspace_id = ? AND item_ref = ?",
            (workspace_id, parsed.format()),
        )
        return True

    async def list_items(
        self, workspace_id: str, *, limit: int = _DEFAULT_ITEM_LIMIT
    ) -> list[WorkspaceItem]:
        if limit < 1 or limit > _MAX_ITEM_LIMIT:
            raise WorkspaceInvalid(f"limit must be between 1 and {_MAX_ITEM_LIMIT}.")
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT item_ref, position, added_at FROM workspace_items WHERE workspace_id = ? ORDER BY position ASC, item_ref ASC LIMIT ?",
            (workspace_id, limit),
        )
        return [
            WorkspaceItem(
                item_ref=str(row["item_ref"]),
                position=int(row["position"]),
                added_at=str(row["added_at"]),
            )
            for row in rows
        ]

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
            sql = "SELECT item_ref, position, added_at FROM workspace_items WHERE workspace_id = ? AND (snoozed_until IS NULL OR snoozed_until <= ?) AND (? IS NULL OR added_at > ? OR (added_at = ? AND item_ref > ?)) ORDER BY added_at ASC, item_ref ASC LIMIT ?"
        else:
            sql = "SELECT item_ref, position, added_at FROM workspace_items WHERE workspace_id = ? AND (snoozed_until IS NULL OR snoozed_until <= ?) AND (? IS NULL OR added_at < ? OR (added_at = ? AND item_ref < ?)) ORDER BY added_at DESC, item_ref DESC LIMIT ?"
        rows = await self._db.fetch_all(
            sql,
            (workspace_id, now_iso, key_added, key_added, key_added, key_ref, limit + 1),
        )
        has_more = len(rows) > limit
        rows = rows[:limit]
        items = [
            WorkspaceItem(
                item_ref=str(r["item_ref"]),
                position=int(r["position"]),
                added_at=str(r["added_at"]),
            )
            for r in rows
        ]
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
        self, workspace_id: str, ordered_refs: list[str]    ) -> int:
        """Assign positions 1..N for the given refs (bounded batch).

        Refs not included keep their relative order after the moved block;
        unknown refs are refused rather than silently ignored.
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
            moved = 0
            for index, ref in enumerate(parsed, start=1):
                cursor = conn.execute(
                    "UPDATE workspace_items SET position = ? WHERE workspace_id = ? AND item_ref = ?",
                    (index, workspace_id, ref),
                )
                moved += cursor.rowcount
            return moved

        return await transaction(self._db, _tx)


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
