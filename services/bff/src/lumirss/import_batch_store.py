"""F049 导入批次追踪 — OPML/书签/MD 笔记导入的可追溯批次。

- counts 如实（成功/跳过/失败）；errors ≤50 条（超出截断并标记
  errorsTruncated）；retry_payload 存失败项的最小重试载荷（≤50 条）。
- 重试只重试失败项；幂等：已存在的目标记 skipped，不重复创建、
  不覆盖后来被修改的内容。
"""

import json
import uuid as _uuid
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_ERRORS = 50
_MAX_RETRY_ITEMS = 50
_KINDS = ("opml", "bookmarks", "md_notes")


class ImportBatchStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def record(
        self,
        *,
        kind: str,
        counts: dict[str, int],
        errors: list[dict[str, Any]] | None = None,
        retry_payload: list[dict[str, Any]] | None = None,
    ) -> str:
        await self._db.migrate()
        if kind not in _KINDS:
            raise ValueError(f"kind must be one of {_KINDS}.")
        clean_errors = (errors or [])[:_MAX_ERRORS]
        clean_retry = (retry_payload or [])[:_MAX_RETRY_ITEMS]
        batch_id = str(_uuid.uuid4())
        await self._db.execute(
            "INSERT INTO import_batches (id, kind, created_at, counts_json, errors_json, retry_payload_json) VALUES (?, ?, ?, ?, ?, ?)",
            (
                batch_id,
                kind,
                utc_now(),
                json.dumps(counts, ensure_ascii=False, separators=(",", ":")),
                json.dumps(
                    {
                        "items": clean_errors,
                        "truncated": len(errors or []) > _MAX_ERRORS,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                json.dumps(clean_retry, ensure_ascii=False, separators=(",", ":")),
            ),
        )
        return batch_id

    async def list_batches(self, limit: int = 20) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, kind, created_at, counts_json, errors_json, retry_payload_json FROM import_batches ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (max(1, min(limit, 100)),),
        )
        return [_row_to_dict(row) for row in rows]

    async def get(self, batch_id: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, kind, created_at, counts_json, errors_json, retry_payload_json FROM import_batches WHERE id = ?",
            (batch_id,),
        )
        return _row_to_dict(row) if row is not None else None


def _row_to_dict(row: Any) -> dict[str, Any]:
    def _loads(raw: str, fallback: Any) -> Any:
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            return fallback
        return value if value is not None else fallback

    return {
        "id": str(row["id"]),
        "kind": str(row["kind"]),
        "createdAt": str(row["created_at"]),
        "counts": _loads(row["counts_json"], {}),
        "errors": _loads(row["errors_json"], {"items": [], "truncated": False}),
        "retryPayload": _loads(row["retry_payload_json"], []),
    }
