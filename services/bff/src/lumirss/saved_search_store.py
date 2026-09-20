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
from lumirss.token_hash import hash_token
from lumirss.util import utc_now

_MAX_SAVED_SEARCHES = 50
_MAX_NAME_LENGTH = 60
_MAX_QUERY_LENGTH = 200
_MAX_CATEGORY_KEY = 200
_ALLOWED_VIEWS = ("all", "unread", "starred")

# F061：列表/读取携带的列（feed_secret 绝不进 _row 输出——管理端只给
# hasFeedToken 布尔；原始值仅供公开路由常量时间比对）。
_ROW_COLUMNS = (
    "id, name, query, params, pinned, pin_order, filters_json, feed_secret, "
    "created_at, updated_at"
)


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


# F035：构建器完整意图白名单（与 /api/v1/search 条目一一对应）。
_FILTER_KEYS = (
    "feedRef", "unreadOnly", "favoriteOnly", "hasSummary", "from", "to",
    "intitle", "phrase", "exclude",
)


def normalize_filters(raw: Any) -> dict[str, Any] | None:
    """白名单化构建器意图；None = 未提供（老视图兼容）。"""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise SavedSearchInvalid("filters 必须是对象。")
    clean: dict[str, Any] = {}
    for key in _FILTER_KEYS:
        value = raw.get(key)
        if value is None:
            continue
        if isinstance(value, bool) or (
            isinstance(value, (int, float)) and key in ("unreadOnly", "favoriteOnly", "hasSummary")
        ):
            clean[key] = bool(value)
            continue
        if isinstance(value, str):
            if len(value) > 200:
                raise SavedSearchInvalid(f"filters.{key} 过长（最多 200 字）。")
            clean[key] = value
            continue
        raise SavedSearchInvalid(f"filters.{key} 类型非法。")
    return clean or None


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
            f"SELECT {_ROW_COLUMNS} FROM saved_searches ORDER BY created_at DESC, id DESC",
            (),
        )
        return [self._row(row) for row in rows]

    async def get(self, view_id: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            f"SELECT {_ROW_COLUMNS} FROM saved_searches WHERE id = ?",
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

    async def set_pinned(self, view_id: str, pinned: bool) -> dict[str, Any] | None:
        """F035：固定/取消固定；固定时排到已固定视图末尾。"""
        await self._db.migrate()
        current = await self.get(view_id)
        if current is None:
            return None
        if pinned:
            row = await self._db.fetch_one(
                "SELECT COALESCE(MAX(pin_order), -1) + 1 AS p FROM saved_searches WHERE pinned = 1",
                (),
            )
            order = int(row["p"]) if row is not None else 0
        else:
            order = None
        await self._db.execute(
            "UPDATE saved_searches SET pinned = ?, pin_order = ?, updated_at = ? WHERE id = ?",
            (1 if pinned else 0, order, utc_now(), view_id),
        )
        updated = await self.get(view_id)
        assert updated is not None
        return updated

    async def set_pin_order(self, view_id: str, pin_order: int) -> dict[str, Any] | None:
        await self._db.migrate()
        current = await self.get(view_id)
        if current is None or not current["pinned"]:
            return None
        await self._db.execute(
            "UPDATE saved_searches SET pin_order = ?, updated_at = ? WHERE id = ?",
            (max(0, int(pin_order)), utc_now(), view_id),
        )
        updated = await self.get(view_id)
        assert updated is not None
        return updated

    async def pinned_views(self) -> "list[dict[str, Any]]":
        """固定视图（pin_order 升序）。"""
        await self._db.migrate()
        rows = await self._db.fetch_all(
            f"SELECT {_ROW_COLUMNS} FROM saved_searches WHERE pinned = 1 ORDER BY pin_order ASC, created_at ASC",
            (),
        )
        return [self._row(row) for row in rows]

    async def set_filters(self, view_id: str, filters: dict[str, Any] | None) -> dict[str, Any] | None:
        """F035：保存/更新构建器完整意图（W1 F017 遗留的闭合）。"""
        clean = normalize_filters(filters)
        await self._db.migrate()
        if await self.get(view_id) is None:
            return None
        await self._db.execute(
            "UPDATE saved_searches SET filters_json = ?, updated_at = ? WHERE id = ?",
            (
                json.dumps(clean, ensure_ascii=False, sort_keys=True) if clean else None,
                utc_now(),
                view_id,
            ),
        )
        updated = await self.get(view_id)
        assert updated is not None
        return updated

    @staticmethod
    def _row(row: Any) -> dict[str, Any]:
        row_dict = dict(row)
        filters_json = row_dict.get("filters_json")
        return {
            "id": str(row["id"]),
            "name": str(row["name"]),
            "query": str(row["query"]),
            "params": json.loads(str(row["params"])),
            "pinned": bool(row_dict.get("pinned", False)),
            "pinOrder": (
                int(row_dict["pin_order"]) if row_dict.get("pin_order") is not None else None
            ),
            "filters": json.loads(filters_json) if filters_json else None,
            # F061：布尔暴露启用态；secret 本身永不随管理端出站。
            "hasFeedToken": bool(row_dict.get("feed_secret")),
            "createdAt": str(row["created_at"]),
            "updatedAt": str(row["updated_at"]),
        }

    # -- F061：私有 Atom 订阅 token ------------------------------------------

    async def get_feed_secret(self, view_id: str) -> str | None:
        """存储值（§13.4 后为 SHA-256；旧明文行兼容）——仅供公开路由
        verify_token 比对；视图缺失/未启用 → None。"""
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT feed_secret FROM saved_searches WHERE id = ?",
            (view_id,),
        )
        if row is None or not row["feed_secret"]:
            return None
        return str(row["feed_secret"])

    async def set_feed_secret(self, view_id: str, secret: str) -> bool:
        """写入 secret（启用 = 首次生成；轮换 = 覆写，旧值立即失效）。

        返回 False = 视图不存在。"""
        await self._db.migrate()
        if await self.get(view_id) is None:
            return False
        # §13.4：只存哈希（原始值仅启用/轮换响应出现一次）。
        await self._db.execute(
            "UPDATE saved_searches SET feed_secret = ?, feed_secret_is_hash = 1, updated_at = ? WHERE id = ?",
            (hash_token(secret), utc_now(), view_id),
        )
        return True
