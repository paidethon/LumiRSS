"""N013 来源改名（别名）+ 历史 —— source_aliases / source_alias_history
的 SQL 唯一入口。

语义：

- put_alias：upsert。custom_name 变化时写一条历史（old_custom_name =
  之前的别名；upstream_name_at_save = 保存时刻的上游标题快照，供
  「上游改名是否发生在别名之后」回溯）；首设别名历史 old 为 NULL。
  每 feed 历史封顶 20 条（超出删最旧）。
- 上游标题变更永不触碰 custom_name——本模块没有「随上游改名」的
  路径，别名只被显式 PUT / DELETE 改变（测试固定该负向契约）。
- delete_alias：只删别名行，历史保留（「恢复旧名」= 用历史名字 PUT）。
- feed_url 是 per-user 库内的键（RoutingDatabase 路由），无跨账户
  泄漏面；隔离由 user_scope 中间件统一保证（测试各验一例）。

写站点 3 处（INSERT history / upsert alias / 删最旧历史 + DELETE alias
= 4）。独立成文件：source_overrides.py execute 站点已满。
"""

from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

MAX_NAME_CHARS = 200
HISTORY_CAP_PER_FEED = 20


class SourceAliasInvalid(ValueError):
    """别名非法（空/超长）→ 路由层映射 422。"""


class SourceAliasNotFound(KeyError):
    """该 feed 无别名（DELETE 幂等性外的显式 404）。"""


def validate_custom_name(value: Any) -> str:
    if not isinstance(value, str):
        raise SourceAliasInvalid("custom_name 必须是字符串。")
    clean = value.strip()
    if not clean:
        raise SourceAliasInvalid("custom_name 不能为空。")
    if len(clean) > MAX_NAME_CHARS:
        raise SourceAliasInvalid(f"custom_name 过长（最多 {MAX_NAME_CHARS} 字）。")
    return clean


def _alias_row(row: Any) -> dict[str, Any]:
    return {
        "feedUrl": str(row["feed_url"]),
        "customName": str(row["custom_name"]),
        "updatedAt": str(row["updated_at"] or ""),
    }


def _history_row(row: Any) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "feedUrl": str(row["feed_url"]),
        "oldCustomName": row["old_custom_name"],
        "upstreamNameAtSave": row["upstream_name_at_save"],
        "changedAt": str(row["changed_at"] or ""),
    }


class SourceAliasStore:
    """CRUD over source_aliases + source_alias_history（bounded table）。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def put_alias(
        self, feed_url: str, custom_name: Any, upstream_name: str | None = None
    ) -> dict[str, Any]:
        """设置/更名（upsert）+ 变化时写历史（含上游名快照）+ 封顶。"""
        clean = validate_custom_name(custom_name)
        await self._db.migrate()
        current = await self._db.fetch_one(
            "SELECT custom_name FROM source_aliases WHERE feed_url = ?",
            (feed_url,),
        )
        previous = str(current["custom_name"]) if current is not None else None
        await self._db.execute(
            "INSERT INTO source_aliases (feed_url, custom_name, updated_at) VALUES (?, ?, ?) ON CONFLICT(feed_url) DO UPDATE SET custom_name = excluded.custom_name, updated_at = excluded.updated_at",
            (feed_url, clean, utc_now()),
        )
        if current is None or previous != clean:
            await self._db.execute(
                "INSERT INTO source_alias_history (feed_url, old_custom_name, upstream_name_at_save, changed_at) VALUES (?, ?, ?, ?)",
                (feed_url, previous, upstream_name, utc_now()),
            )
            await self._db.execute(
                "DELETE FROM source_alias_history WHERE feed_url = ? AND id NOT IN (SELECT id FROM source_alias_history WHERE feed_url = ? ORDER BY id DESC LIMIT ?)",
                (feed_url, feed_url, HISTORY_CAP_PER_FEED),
            )
        row = await self._db.fetch_one(
            "SELECT feed_url, custom_name, updated_at FROM source_aliases WHERE feed_url = ?",
            (feed_url,),
        )
        return _alias_row(row)

    async def get_alias(self, feed_url: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT feed_url, custom_name, updated_at FROM source_aliases WHERE feed_url = ?",
            (feed_url,),
        )
        return _alias_row(row) if row is not None else None

    async def list_aliases(self) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT feed_url, custom_name, updated_at FROM source_aliases ORDER BY updated_at DESC"
        )
        return [_alias_row(row) for row in rows]

    async def history(
        self, feed_url: str, limit: int = HISTORY_CAP_PER_FEED
    ) -> list[dict[str, Any]]:
        """某来源的改名历史（新→旧；有界）。"""
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, feed_url, old_custom_name, upstream_name_at_save, changed_at FROM source_alias_history WHERE feed_url = ? ORDER BY id DESC LIMIT ?",
            (feed_url, max(1, min(int(limit), HISTORY_CAP_PER_FEED))),
        )
        return [_history_row(row) for row in rows]

    async def delete_alias(self, feed_url: str) -> None:
        """删除别名（历史保留）；无别名 → SourceAliasNotFound（404）。"""
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT feed_url FROM source_aliases WHERE feed_url = ?",
            (feed_url,),
        )
        if row is None:
            raise SourceAliasNotFound(feed_url)
        await self._db.execute(
            "DELETE FROM source_aliases WHERE feed_url = ?",
            (feed_url,),
        )
