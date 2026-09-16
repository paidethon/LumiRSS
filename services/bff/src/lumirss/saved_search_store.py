"""Saved search views (pool #09): persist query + filter intent.

A saved view stores the QUERY and its filter parameters — never the
result set — so opening a view re-queries and new matching entries show
up automatically. House rules: single-user scope, bounded count (50),
normalized whitelisted params, one transaction for the count-check +
insert so the cap actually holds.
"""

import json
import uuid as _uuid
from typing import Any

from lumirss.db_tx import transaction
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_SAVED_SEARCHES = 50
_MAX_NAME_LENGTH = 60
_MAX_QUERY_LENGTH = 200
_MAX_CATEGORY_KEY = 200
_ALLOWED_VIEWS = ("all", "unread", "starred")


class SavedSearchInvalid(ValueError):
    """A saved-search payload failed validation (mapped to 400)."""


class SavedSearchNotFound(Exception):
    """No such saved view (mapped to 404)."""


class SavedSearchLimit(Exception):
    """The saved-view cap was reached (mapped to 409)."""


def normalize_name(name: Any) -> str:
    if not isinstance(name, str):
        raise SavedSearchInvalid("名称必须是字符串。")
    clean = name.strip()
    if not clean:
        raise SavedSearchInvalid("名称不能为空。")
    if len(clean) > _MAX_NAME_LENGTH:
        raise SavedSearchInvalid("名称过长（最多 60 字）。")
    return clean


def normalize_query(query: Any) -> str:
    if not isinstance(query, str):
        raise SavedSearchInvalid("查询必须是字符串。")
    clean = query.strip()
    if not clean:
        raise SavedSearchInvalid("查询不能为空。")
    if len(clean) > _MAX_QUERY_LENGTH:
        raise SavedSearchInvalid("查询过长（最多 200 字）。")
    return clean


def normalize_params(raw: Any) -> dict[str, Any]:
    """Whitelist the stored filter intent; unknown keys are dropped."""
    if raw is None:
        return {"view": "all", "categoryKey": ""}
    if not isinstance(raw, dict):
        raise SavedSearchInvalid("params 必须是对象。")
    view = raw.get("view") or "all"
    if view not in _ALLOWED_VIEWS:
        raise SavedSearchInvalid("view 只支持 all / unread / starred。")
    category_key = raw.get("categoryKey") or ""
    if not isinstance(category_key, str) or len(category_key) > _MAX_CATEGORY_KEY:
        raise SavedSearchInvalid("categoryKey 非法。")
    return {"view": view, "categoryKey": category_key}


class SavedSearchStore:
    """CRUD over the saved_searches table (newest-first listing)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def list(self) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, name, query, params, created_at, updated_at FROM saved_searches ORDER BY created_at DESC, id DESC",
            (),
        )
        return [self._row(row) for row in rows]

    async def get(self, view_id: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, name, query, params, created_at, updated_at FROM saved_searches WHERE id = ?",
            (view_id,),
        )
        return self._row(row) if row is not None else None

    async def create(self, name: Any, query: Any, params: Any) -> dict[str, Any]:
        clean_name = normalize_name(name)
        clean_query = normalize_query(query)
        clean_params = normalize_params(params)
        await self._db.migrate()
        now = utc_now()
        view_id = str(_uuid.uuid4())

        def _insert(conn: Any) -> None:
            # BEGIN IMMEDIATE + count re-check inside the write lock so
            # concurrent creates cannot push past the cap.
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM saved_searches", ()
            ).fetchone()
            if row is not None and int(row["n"]) >= _MAX_SAVED_SEARCHES:
                raise SavedSearchLimit(
                    f"保存的搜索最多 {_MAX_SAVED_SEARCHES} 条，请先删除不需要的视图。"
                )
            conn.execute(
                "INSERT INTO saved_searches (id, name, query, params, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    view_id,
                    clean_name,
                    clean_query,
                    json.dumps(clean_params, ensure_ascii=False, sort_keys=True),
                    now,
                    now,
                ),
            )

        await transaction(self._db, _insert)
        created = await self.get(view_id)
        assert created is not None
        return created

    async def rename(self, view_id: str, name: Any) -> dict[str, Any] | None:
        clean_name = normalize_name(name)
        await self._db.migrate()
        if await self.get(view_id) is None:
            return None
        await self._db.execute(
            "UPDATE saved_searches SET name = ?, updated_at = ? WHERE id = ?",
            (clean_name, utc_now(), view_id),
        )
        return await self.get(view_id)

    async def delete(self, view_id: str) -> bool:
        # Pool #45 hygiene: existence check + delete in ONE transaction so
        # a concurrent delete cannot turn our 204 into a no-op.
        def _delete(conn: Any) -> int:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT id FROM saved_searches WHERE id = ?", (view_id,)
            ).fetchone()
            if row is None:
                return 0
            conn.execute("DELETE FROM saved_searches WHERE id = ?", (view_id,))
            return 1

        return (await transaction(self._db, _delete)) == 1

    @staticmethod
    def _row(row: Any) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "name": str(row["name"]),
            "query": str(row["query"]),
            "params": json.loads(str(row["params"])),
            "createdAt": str(row["created_at"]),
            "updatedAt": str(row["updated_at"]),
        }
