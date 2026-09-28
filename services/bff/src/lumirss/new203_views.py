"""NEW-203 来源分流视图 —— 同一 feed 的多个个人读取侧视图。

语义边界（模块存在的理由）：

- 「分流」是**读取侧派生**：一个已订阅 feed 仍然只有一个抓取任务
  （FreshRSS 域零改动——负向契约由测试断言零 adapter 调用）、条目
  身份不变；视图只是 search_entries 投影上的一个命名过滤器
  （field ∈ title|content|author，op 固定 ``contains``，大小写不敏感）；
- 不做语义更复杂的规则语言（无正则/无取反/无多条件）——个人视图的
  分流语义保持可解释：``列 包含 关键词``；
- 视图行被删/上游退订后，视图如实变空（不 shadow-copy，投影可再
  生成，与全库口径一致）。

LIKE 转义：``%``/``_``/``\\`` 逐字转义 + ``ESCAPE '\\'``——用户输入
永远按字面匹配。
"""

import uuid as _uuid
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

MAX_NAME = 60
MAX_VALUE = 120
MAX_FEED_URL = 2048
FIELDS = ("title", "content", "author")
ENTRIES_LIMIT_MAX = 50


class SourceViewInvalid(ValueError):
    """视图定义非法（名称/字段/关键词），路由层映射 422。"""


class SourceViewNotFound(Exception):
    """视图不存在 —— 404 source_view_not_found。"""


class SourceViewExists(Exception):
    """同 feed 下同名视图已存在 —— 409 source_view_exists。"""


def validate_view_input(
    *, feed_url: Any = None, name: Any = None, field: Any = None, value: Any = None
) -> dict[str, Any]:
    """校验并归一化视图字段（缺席的字段不校验——PATCH 局部更新复用）。"""
    cleaned: dict[str, Any] = {}
    if feed_url is not None:
        clean_url = str(feed_url).strip()
        if not clean_url or len(clean_url) > MAX_FEED_URL:
            raise SourceViewInvalid("feedUrl 不能为空（≤2048 字符）。")
        cleaned["feed_url"] = clean_url
    if name is not None:
        clean_name = str(name).strip()
        if not clean_name:
            raise SourceViewInvalid("name 不能为空。")
        if len(clean_name) > MAX_NAME:
            raise SourceViewInvalid(f"name 过长（≤{MAX_NAME} 字符）。")
        cleaned["name"] = clean_name
    if field is not None:
        if field not in FIELDS:
            raise SourceViewInvalid(
                f"field 必须是 {'/'.join(FIELDS)} 之一（op 固定 contains）。"
            )
        cleaned["field"] = field
    if value is not None:
        clean_value = str(value).strip()
        if not clean_value:
            raise SourceViewInvalid("value（包含关键词）不能为空。")
        if len(clean_value) > MAX_VALUE:
            raise SourceViewInvalid(f"value 过长（≤{MAX_VALUE} 字符）。")
        cleaned["value"] = clean_value
    return cleaned


def escape_like(value: str) -> str:
    """字面 LIKE 模式转义（配 ESCAPE '\\'）。"""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _row_to_view(row: Any) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "feedUrl": str(row["feed_url"]),
        "name": str(row["name"]),
        "field": str(row["field"]),
        "value": str(row["value"]),
        "createdAt": str(row["created_at"]),
    }


def _row_to_entry(row: Any) -> dict[str, Any]:
    return {
        "entryRef": str(row["entry_ref"]),
        "title": str(row["title"] or ""),
        "author": str(row["author"] or ""),
        "publishedAt": str(row["published_at"]),
        "url": str(row["url"] or ""),
    }


class SourceViewStore:
    """SQL 唯一入口；inline literal at each execute site（repo 约定）。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(self, parts: dict[str, Any]) -> dict[str, Any]:
        complete = {"feed_url", "name", "field", "value"} <= set(parts)
        if not complete:
            raise SourceViewInvalid("feedUrl/name/field/value 全部必填。")
        await self._db.migrate()
        if await self._by_feed_name(parts["feed_url"], parts["name"]):
            raise SourceViewExists(parts["name"])
        view_id = str(_uuid.uuid4())
        now = utc_now()
        await self._db.execute(
            "INSERT INTO new203_source_views"
            " (id, feed_url, name, field, value, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                view_id,
                parts["feed_url"],
                parts["name"],
                parts["field"],
                parts["value"],
                now,
            ),
        )
        return {
            "id": view_id,
            "feedUrl": parts["feed_url"],
            "name": parts["name"],
            "field": parts["field"],
            "value": parts["value"],
            "createdAt": now,
        }

    async def _by_feed_name(self, feed_url: str, name: str) -> dict[str, Any] | None:
        row = await self._db.fetch_one(
            "SELECT id, feed_url, name, field, value, created_at"
            " FROM new203_source_views WHERE feed_url = ? AND name = ?",
            (feed_url, name),
        )
        return _row_to_view(row) if row is not None else None

    async def list_views(self, feed_url: str | None = None) -> list[dict[str, Any]]:
        await self._db.migrate()
        if feed_url:
            rows = await self._db.fetch_all(
                "SELECT id, feed_url, name, field, value, created_at"
                " FROM new203_source_views WHERE feed_url = ?"
                " ORDER BY created_at ASC, id ASC LIMIT 200",
                (feed_url,),
            )
        else:
            rows = await self._db.fetch_all(
                "SELECT id, feed_url, name, field, value, created_at"
                " FROM new203_source_views"
                " ORDER BY created_at ASC, id ASC LIMIT 200",
                (),
            )
        return [_row_to_view(row) for row in rows]

    async def get(self, view_id: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, feed_url, name, field, value, created_at"
            " FROM new203_source_views WHERE id = ?",
            (view_id,),
        )
        return _row_to_view(row) if row is not None else None

    async def update(self, view_id: str, parts: dict[str, Any]) -> dict[str, Any]:
        existing = await self.get(view_id)
        if existing is None:
            raise SourceViewNotFound(view_id)
        if not parts:
            return existing
        if "name" in parts and parts["name"] != existing["name"]:
            clash = await self._by_feed_name(existing["feedUrl"], parts["name"])
            if clash is not None and clash["id"] != view_id:
                raise SourceViewExists(parts["name"])
        assignments: list[str] = []
        params: list[Any] = []
        for column in ("name", "field", "value"):
            if column in parts:
                assignments.append(f"{column} = ?")
                params.append(parts[column])
        params.append(view_id)
        await self._db.execute(
            f"UPDATE new203_source_views SET {', '.join(assignments)} WHERE id = ?",
            tuple(params),
        )
        updated = await self.get(view_id)
        assert updated is not None
        return updated

    async def delete(self, view_id: str) -> bool:
        await self._db.migrate()
        changed = await self._db.execute(
            "DELETE FROM new203_source_views WHERE id = ?", (view_id,)
        )
        return bool(changed)

    async def view_entries(self, view_id: str, *, limit: int = ENTRIES_LIMIT_MAX) -> dict[str, Any]:
        """视图条目（读取侧投影过滤；有界；视图删/源退订 → 如实为空）。"""
        view = await self.get(view_id)
        if view is None:
            raise SourceViewNotFound(view_id)
        await self._db.migrate()
        column = {"title": "title", "content": "content_text", "author": "author"}[
            view["field"]
        ]
        pattern = f"%{escape_like(view['value'])}%"
        bounded = max(1, min(int(limit), ENTRIES_LIMIT_MAX))
        rows = await self._db.fetch_all(
            "SELECT entry_ref, title, author, published_at, url"
            f" FROM search_entries WHERE feed_url = ?"
            f" AND LOWER({column}) LIKE LOWER(?) ESCAPE '\\'"
            " ORDER BY published_at DESC, id DESC LIMIT ?",
            (view["feedUrl"], pattern, bounded),
        )
        return {
            "view": view,
            "entries": [_row_to_entry(row) for row in rows],
            "basis": "projection",
            "note": (
                "分流是读取侧视图：抓取任务与条目身份不变，不复制不旁路；"
                "匹配口径 = 字段包含关键词（大小写不敏感）。"
            ),
        }
