"""F076 图谱命名视图 — graph_views 存取（表见迁移 0056）。

- name 全局唯一（UNIQUE）：同名保存需显式 overwrite=true，否则 409
  graph_view_exists（覆盖确认流）；
- layout_json：{nodeRef: {x,y}}，≤200 节点位置；filters_json：视图
  筛选意图；focus_node：恢复时聚焦的节点（可空）；
- 恢复语义在客户端：应用位置到存在节点、新节点默认位、失效节点跳过。

全部 SQL 为内联字面量 + 绑定参数；写站点 3 处（insert/update/delete）。
"""

import json as _json
import uuid as _uuid
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

NAME_MAX = 50
MAX_LAYOUT_NODES = 200

_INSERT_SQL = """INSERT INTO graph_views (
id, name, layout_json, filters_json, focus_node, created_at, updated_at)
VALUES (?, ?, ?, ?, ?, ?, ?)"""

_UPDATE_SQL = """UPDATE graph_views SET layout_json = ?, filters_json = ?,
focus_node = ?, updated_at = ? WHERE id = ?"""

_RENAME_SQL = """UPDATE graph_views SET name = ?, updated_at = ? WHERE id = ?"""

_SELECT = """SELECT id, name, layout_json, filters_json, focus_node,
created_at, updated_at FROM graph_views"""


class GraphViewExists(Exception):
    """同名视图已存在且未确认覆盖（映射 409）。"""

    def __init__(self, name: str) -> None:
        super().__init__(f"graph view '{name}' already exists.")
        self.name = name


class GraphViewNotFound(Exception):
    """视图不存在（映射 404）。"""


class GraphViewInvalid(ValueError):
    """视图载荷非法（映射 400/422）。"""


def _clean_name(name: Any) -> str:
    if not isinstance(name, str):
        raise GraphViewInvalid("name must be a string.")
    clean = name.strip()
    if not clean:
        raise GraphViewInvalid("name must not be blank.")
    if len(clean) > NAME_MAX:
        raise GraphViewInvalid(f"name must be at most {NAME_MAX} characters.")
    return clean


def _clean_layout(layout: Any) -> str:
    if layout is None:
        return "{}"
    if not isinstance(layout, dict):
        raise GraphViewInvalid("layout must be an object.")
    if len(layout) > MAX_LAYOUT_NODES:
        raise GraphViewInvalid(f"layout supports at most {MAX_LAYOUT_NODES} nodes.")
    for ref, pos in layout.items():
        if not isinstance(ref, str) or not isinstance(pos, dict):
            raise GraphViewInvalid("layout entries must be ref -> {x, y}.")
        if not isinstance(pos.get("x"), (int, float)) or not isinstance(pos.get("y"), (int, float)):
            raise GraphViewInvalid("layout positions must carry numeric x/y.")
    return _json.dumps(layout, ensure_ascii=False, sort_keys=True)


def _clean_filters(filters: Any) -> str:
    if filters is None:
        return "{}"
    if not isinstance(filters, dict):
        raise GraphViewInvalid("filters must be an object.")
    return _json.dumps(filters, ensure_ascii=False, sort_keys=True)


def _row(row: Any) -> dict[str, Any]:
    def _loads(raw: Any) -> Any:
        try:
            return _json.loads(raw) if raw else {}
        except _json.JSONDecodeError:
            return {}

    return {
        "id": str(row["id"]),
        "name": str(row["name"]),
        "layout": _loads(row["layout_json"]),
        "filters": _loads(row["filters_json"]),
        "focusNode": row["focus_node"],
        "createdAt": str(row["created_at"]),
        "updatedAt": str(row["updated_at"]),
    }


class GraphViewStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def list_views(self) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(f"{_SELECT} ORDER BY updated_at DESC")
        return [_row(row) for row in rows]

    async def get(self, view_id: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(f"{_SELECT} WHERE id = ?", (view_id,))
        return _row(row) if row is not None else None

    async def create(
        self,
        name: Any,
        layout: Any,
        filters: Any,
        focus_node: Any = None,
        *,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        clean_name = _clean_name(name)
        layout_json = _clean_layout(layout)
        filters_json = _clean_filters(filters)
        if focus_node is not None and not isinstance(focus_node, str):
            raise GraphViewInvalid("focusNode must be a string or null.")
        await self._db.migrate()
        existing = await self._db.fetch_one(
            "SELECT id FROM graph_views WHERE name = ?", (clean_name,)
        )
        if existing is not None:
            if not overwrite:
                raise GraphViewExists(clean_name)
            await self._db.execute(
                _UPDATE_SQL,
                (layout_json, filters_json, focus_node, utc_now(), str(existing["id"])),
            )
            view = await self.get(str(existing["id"]))
            assert view is not None
            return view
        view_id = str(_uuid.uuid4())
        now = utc_now()
        await self._db.execute(
            _INSERT_SQL,
            (view_id, clean_name, layout_json, filters_json, focus_node, now, now),
        )
        view = await self.get(view_id)
        assert view is not None
        return view

    async def delete(self, view_id: str) -> bool:
        await self._db.migrate()
        row = await self._db.fetch_one("SELECT id FROM graph_views WHERE id = ?", (view_id,))
        if row is None:
            return False
        await self._db.execute("DELETE FROM graph_views WHERE id = ?", (view_id,))
        return True
