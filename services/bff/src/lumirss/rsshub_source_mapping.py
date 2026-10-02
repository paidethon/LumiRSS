"""R18 RSSHub 导入来源映射 —— rsshub_source_mappings 的唯一 SQL 入口。

语义（与迁移注释一致）：

- ``record``：一次「原生 → RSSHub」切换写一行；original_url 一字
  不改（撤销回原生的依据；同 original_url + rsshub_url 重复切换
  幂等返回既有行，不重复写入）。
- ``kept_old_source=True`` 表示原 URL 本来就已订阅、按「保留旧源 +
  关联新源」处理——FreshRSS 条目 id 内嵌 feed 地址，已读/收藏/
  批注状态无法跨源安全迁移，所以绝不自动退订旧源。
- ``revert``：置 reverted（保留历史行），不删除；撤销动作本身
  （重新订阅原地址）由路由层经控制适配器执行，本模块只管台账。
- per-user：所有访问走 Lumi 每用户库（RoutingDatabase 路由），
  无跨账户读写面。

SQL stays an inline literal at each execute site (repo convention).
"""

import uuid as _uuid
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

__all__ = ["RsshubSourceMappingStore", "RsshubMappingNotFound"]

_LIST_LIMIT = 200


class RsshubMappingNotFound(Exception):
    """The mapping does not exist for this user (mapped to 404)."""


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": str(row["mapping_uuid"]),
        "originalUrl": str(row["original_url"]),
        "rsshubUrl": str(row["rsshub_url"]),
        "namespace": row["namespace"],
        "routePath": row["route_path"],
        "strategy": str(row["strategy"]),
        "keptOldSource": bool(row["kept_old_source"]),
        "status": str(row["status"]),
        "createdAt": str(row["created_at"]),
        "revertedAt": row["reverted_at"],
    }


_SELECT = (
    "SELECT mapping_uuid, original_url, rsshub_url, namespace, route_path, "
    "strategy, kept_old_source, status, created_at, reverted_at "
    "FROM rsshub_source_mappings"
)


class RsshubSourceMappingStore:
    """Per-user 台账（bounded list，append + revert）。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def record(
        self,
        *,
        original_url: str,
        rsshub_url: str,
        namespace: str | None,
        route_path: str | None,
        strategy: str,
        kept_old_source: bool,
    ) -> dict[str, Any]:
        """写一行映射；同 (original, rsshub) 且 active 的重复切换幂等。"""
        await self._db.migrate()
        existing = await self._db.fetch_one(
            _SELECT + " WHERE original_url = ? AND rsshub_url = ? AND status = 'active' LIMIT 1",
            (original_url, rsshub_url),
        )
        if existing is not None:
            return _row_to_dict(existing)
        mapping_uuid = str(_uuid.uuid4())
        await self._db.execute(
            "INSERT INTO rsshub_source_mappings (mapping_uuid, original_url, rsshub_url, "
            "namespace, route_path, strategy, kept_old_source, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?)",
            (
                mapping_uuid,
                original_url,
                rsshub_url,
                namespace,
                route_path,
                strategy,
                1 if kept_old_source else 0,
                utc_now(),
            ),
        )
        row = await self._db.fetch_one(
            _SELECT + " WHERE mapping_uuid = ?",
            (mapping_uuid,),
        )
        assert row is not None  # just inserted in the same database
        return _row_to_dict(row)

    async def list_all(self) -> list[dict[str, Any]]:
        """全部映射（新→旧，有界 200）——来源运维工作台列表用。"""
        await self._db.migrate()
        rows = await self._db.fetch_all(
            _SELECT + " ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (_LIST_LIMIT,),
        )
        return [_row_to_dict(row) for row in rows]

    async def get(self, mapping_uuid: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            _SELECT + " WHERE mapping_uuid = ?",
            (mapping_uuid,),
        )
        return _row_to_dict(row) if row is not None else None

    async def mark_reverted(self, mapping_uuid: str) -> dict[str, Any]:
        """撤销映射（置 reverted；幂等：已 reverted 原样返回）。"""
        current = await self.get(mapping_uuid)
        if current is None:
            raise RsshubMappingNotFound(mapping_uuid)
        if current["status"] == "active":
            await self._db.execute(
                "UPDATE rsshub_source_mappings SET status = 'reverted', reverted_at = ? "
                "WHERE mapping_uuid = ?",
                (utc_now(), mapping_uuid),
            )
        reverted = await self.get(mapping_uuid)
        assert reverted is not None
        return reverted
