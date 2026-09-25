"""N141 search snapshots — freeze a search moment, compare later.

A snapshot stores the QUERY + whitelisted filter scope + the RESULT
REFS of one freeze (bounded keyset walk at the route, cap 2000 refs;
``truncated`` honesty flag stored beside the filters). POST …/compare
re-runs the SAME stored scope and diffs honestly — the store never
re-interprets or widens the frozen scope.

Per-user table (RoutingDatabase routes by request identity); capped at
20 rows — an over-limit create prunes the OLDEST rows inside the same
transaction, so the cap holds under concurrency (pool #45 pattern).
"""

import json
import uuid as _uuid
from typing import Any

from lumirss.db_tx import transaction
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_SNAPSHOTS = 20
_MAX_QUERY_LENGTH = 200

# 与 GET /search 同参的过滤白名单（q 单独存储；同义词扩展等聚合口径
# 之外的参数不收——快照口径 = 基础词条过滤链，与 N145/N143 一致）。
_FILTER_KEYS = (
    "feedUrl", "categoryId", "state", "favorite",
    "from", "to", "intitle", "phrase", "exclude", "hasSummary",
)

_BOOL_KEYS = ("favorite", "hasSummary")


class SearchSnapshotInvalid(ValueError):
    """A snapshot payload failed validation (mapped to 400)."""


class SearchSnapshotNotFound(Exception):
    """No such snapshot (mapped to 404)."""


def normalize_snapshot_query(query: Any) -> str:
    if not isinstance(query, str):
        raise SearchSnapshotInvalid("查询必须是字符串。")
    clean = query.strip()
    if not clean:
        raise SearchSnapshotInvalid("查询不能为空。")
    if len(clean) > _MAX_QUERY_LENGTH:
        raise SearchSnapshotInvalid("查询过长（最多 200 字）。")
    return clean


def normalize_snapshot_filters(raw: Any) -> dict[str, Any]:
    """白名单化快照过滤作用域；未知键丢弃，类型非法 → 400。"""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise SearchSnapshotInvalid("filters 必须是对象。")
    clean: dict[str, Any] = {}
    for key in _FILTER_KEYS:
        value = raw.get(key)
        if value is None:
            continue
        if key in _BOOL_KEYS:
            if isinstance(value, bool):
                clean[key] = value
            elif key == "hasSummary" and isinstance(value, (int, float)):
                clean[key] = bool(value)
            else:
                raise SearchSnapshotInvalid(f"filters.{key} 类型非法。")
            continue
        if isinstance(value, str):
            if len(value) > 200:
                raise SearchSnapshotInvalid(f"filters.{key} 过长（最多 200 字）。")
            clean[key] = value
            continue
        raise SearchSnapshotInvalid(f"filters.{key} 类型非法。")
    return clean


class SearchSnapshotStore:
    """CRUD over the search_snapshots table (newest-first listing)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self,
        query: Any,
        filters: dict[str, Any] | None,
        refs: list[str],
        *,
        truncated: bool = False,
    ) -> dict[str, Any]:
        """Freeze one snapshot; prune past the 20-row cap atomically."""
        clean_query = normalize_snapshot_query(query)
        clean_filters = normalize_snapshot_filters(filters)
        await self._db.migrate()
        snapshot_id = str(_uuid.uuid4())
        now = utc_now()

        def _insert(conn: Any) -> None:
            conn.execute("BEGIN IMMEDIATE")
            # 「最老」= 最早插入（rowid 单调）；created_at 秒级精度在
            # 同秒创建时无法区分先后。
            rows = conn.execute(
                "SELECT id FROM search_snapshots ORDER BY rowid ASC",
                (),
            ).fetchall()
            # 本条插入后超出的最老快照在同一写锁内删除（cap 真实生效）。
            excess = len(rows) + 1 - _MAX_SNAPSHOTS
            for index in range(max(0, excess)):
                conn.execute(
                    "DELETE FROM search_snapshots WHERE id = ?",
                    (str(rows[index]["id"]),),
                )
            conn.execute(
                "INSERT INTO search_snapshots (id, query, filters_json, ref_list_json, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    snapshot_id,
                    clean_query,
                    json.dumps(
                        {"params": clean_filters, "truncated": bool(truncated)},
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    json.dumps(list(refs), ensure_ascii=False),
                    now,
                ),
            )

        await transaction(self._db, _insert)
        created = await self.get(snapshot_id)
        assert created is not None
        return created

    async def list(self) -> list[dict[str, Any]]:
        """Bounded listing (no ref lists — counts only)."""
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, query, filters_json, ref_list_json, created_at"
            " FROM search_snapshots ORDER BY created_at DESC, id DESC",
            (),
        )
        return [self._row(row, include_refs=False) for row in rows]

    async def count_before(self, cutoff: str) -> int:
        """N189 活动清除预览：早于 cutoff（ISO 文本比较口径）的快照数。"""
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM search_snapshots WHERE created_at < ?",
            (cutoff,),
        )
        return int(row["n"]) if row else 0

    async def purge_before(self, cutoff: str) -> int:
        """N189 活动清除：删除早于 cutoff 的搜索快照，返回删除数。"""
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM search_snapshots WHERE created_at < ?",
            (cutoff,),
        )
        await self._db.execute(
            "DELETE FROM search_snapshots WHERE created_at < ?",
            (cutoff,),
        )
        return int(row["n"]) if row else 0

    async def get(self, snapshot_id: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, query, filters_json, ref_list_json, created_at"
            " FROM search_snapshots WHERE id = ?",
            (snapshot_id,),
        )
        if row is None:
            return None
        return self._row(row, include_refs=True)

    @staticmethod
    def _row(row: Any, *, include_refs: bool) -> dict[str, Any]:
        filters_json = json.loads(str(row["filters_json"]))
        params = filters_json.get("params") if isinstance(filters_json, dict) else {}
        truncated = (
            filters_json.get("truncated") if isinstance(filters_json, dict) else False
        )
        refs: list[str] = json.loads(str(row["ref_list_json"]))
        if not isinstance(refs, list):
            refs = []
        result: dict[str, Any] = {
            "id": str(row["id"]),
            "query": str(row["query"]),
            "filters": params if isinstance(params, dict) else {},
            "truncated": bool(truncated),
            "refCount": len(refs),
            "createdAt": str(row["created_at"]),
        }
        if include_refs:
            result["refs"] = [str(ref) for ref in refs]
        return result
