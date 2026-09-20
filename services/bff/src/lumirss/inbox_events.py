"""F107 Inbox 投递事件 —— SQL 唯一入口。

每次投递（成功 delivered / 重复 duplicate / 失败 failed）一条事件：
- guid + payload_hash 构成「去重依据」的诚实展示（哈希展示前 8 位）；
- payload_json 保存重放所需的最小原始载荷（与正式 ingest 同一形状，
  有界 ≤100KB）；
- failed 事件可重放（复用原载荷 + 既有 (source, guid) 幂等）；
- 写入侧裁剪总量（500 条），重启后事件仍在（SQLite 持久）。

写站点 3 处：INSERT / 裁剪 DELETE / （replay 复用 record 的 INSERT）。
"""

import hashlib
import json
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_ROWS = 500
_MAX_PAYLOAD_JSON = 100_000
_STATUSES = ("delivered", "duplicate", "failed")


def payload_hash_of(payload: dict[str, Any]) -> str:
    """载荷指纹（guid+title+content 规范化 JSON 的 sha256 前 16 位）。"""
    canonical = json.dumps(
        {
            "guid": payload.get("guid") or "",
            "title": payload.get("title") or "",
            "content": payload.get("content") or "",
            "contentHtml": payload.get("contentHtml") or "",
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


class InboxEventStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def record(
        self,
        *,
        source_uuid: str,
        guid: str,
        status: str,
        error_summary: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> int | None:
        if status not in _STATUSES:
            raise ValueError(f"status must be one of {_STATUSES}.")
        await self._db.migrate()
        payload_json = None
        if payload is not None:
            payload_json = json.dumps(payload, ensure_ascii=False)[:_MAX_PAYLOAD_JSON]
        row_id = await self._db.execute(
            "INSERT INTO inbox_events (source_uuid, guid, status, error_summary, payload_hash, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                source_uuid,
                guid[:512],
                status,
                (error_summary or "")[:200] or None,
                payload_hash_of(payload or {}),
                payload_json,
                utc_now(),
            ),
        )
        await self._db.execute(
            "DELETE FROM inbox_events WHERE id NOT IN (SELECT id FROM inbox_events ORDER BY id DESC LIMIT ?)",
            (_MAX_ROWS,),
        )
        return int(row_id) if row_id else None

    async def list_events(
        self, source_uuid: str, limit: int = 50
    ) -> list[dict[str, Any]]:
        await self._db.migrate()
        bounded = max(1, min(limit, 100))
        rows = await self._db.fetch_all(
            "SELECT id, source_uuid, guid, status, error_summary, payload_hash, created_at FROM inbox_events WHERE source_uuid = ? ORDER BY id DESC LIMIT ?",
            (source_uuid, bounded),
        )
        return [self._row(r) for r in rows]

    async def get_event(self, event_id: int) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, source_uuid, guid, status, error_summary, payload_hash, payload_json, created_at FROM inbox_events WHERE id = ?",
            (event_id,),
        )
        if row is None:
            return None
        view = self._row(row)
        try:
            view["payload"] = (
                json.loads(str(row["payload_json"]))
                if row["payload_json"]
                else None
            )
        except ValueError:
            view["payload"] = None
        return view

    def _row(self, row: Any) -> dict[str, Any]:
        payload_hash = str(row["payload_hash"] or "")
        return {
            "id": int(row["id"]),
            "sourceUuid": str(row["source_uuid"]),
            "guid": str(row["guid"]),
            "status": str(row["status"]),
            "errorSummary": row["error_summary"],
            "payloadHashPrefix": payload_hash[:8],
            "createdAt": str(row["created_at"]),
        }
