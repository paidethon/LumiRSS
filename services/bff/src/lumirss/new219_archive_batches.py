"""NEW-219 文章批量归档 —— 两段式（预览清单 → 勾选归档）+ 收据 + 撤销。

归档语义：把文章从未读流清除（FreshRSS set_entry_state read=True，
set 语义）+ 投影镜像——与积压整理助手（F024）同一管线；本模块的增量：
- 归档清单由用户**逐条勾选**（apply 只收勾选的 refs，上限 200）；
- 每批落一行收据（new219_archive_batches）：实际归档的 refs + 逐条
  归档前的 (read, starred) 状态快照；
- 撤销（undo）按收据执行，且只撤「未被后续修改」的部分：
  * 当前 read=0 → 已被改回（跳过，already_unread）；
  * 当前 starred ≠ 快照 starred → 归档后被动过（跳过，modified_since）；
  * 其余 → 恢复 read=0（适配器 + 投影镜像）；
  撤销单向（undone_at），重复撤销 409。
- 加星条目被服务端强制保护：预览不计入、apply 拒绝（即使前端传了）。
"""

import json
import uuid
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

_PREVIEW_SAMPLE = 200
_APPLY_CAP = 200
_RECEIPT_LIST_CAP = 20


class ArchiveBatchInvalid(ValueError):
    """预览/归档载荷非法（refs 数量、形状），映射 422。"""


class ArchiveBatchNotFound(Exception):
    """收据不存在，映射 404。"""


class ArchiveBatchConflict(Exception):
    """收据已撤销过（单向），映射 409。"""


class ArchiveBatchRefused(Exception):
    """勾选里含受保护（加星）条目 → 整批拒绝，映射 409。"""

    def __init__(self, refs: list[str]) -> None:
        super().__init__("starred")
        self.refs = refs


def _build_where(
    *, feed_url: str | None, older_than_days: int | None, include_read: bool
) -> tuple[str, list[Any]]:
    where: list[str] = ["starred = 0"]
    params: list[Any] = []
    if feed_url:
        where.append("feed_url = ?")
        params.append(feed_url)
    if older_than_days is not None:
        from datetime import UTC, datetime, timedelta

        cutoff = (datetime.now(UTC) - timedelta(days=older_than_days)).isoformat()
        where.append("published_at <= ?")
        params.append(cutoff)
    if not include_read:
        where.append("read = 0")
    return " AND ".join(where), params


async def archive_preview(
    db: Database, *, feed_url: str | None, older_than_days: int | None, include_read: bool
) -> dict[str, Any]:
    await db.migrate()
    clause, params = _build_where(
        feed_url=feed_url, older_than_days=older_than_days, include_read=include_read
    )
    count_row = await db.fetch_one(
        f"SELECT COUNT(*) AS n FROM search_entries WHERE {clause}", (*params,)
    )
    rows = await db.fetch_all(
        "SELECT entry_ref, title, feed_title, url, published_at, read, starred FROM search_entries"
        f" WHERE {clause} ORDER BY published_at DESC LIMIT ?",
        (*params, _PREVIEW_SAMPLE + 1),
    )
    sample = rows[:_PREVIEW_SAMPLE]
    return {
        "count": int(count_row["n"]) if count_row is not None else 0,
        "sample": [
            {
                "ref": f"rss:{r['entry_ref']}",
                "title": str(r["title"] or ""),
                "feedTitle": str(r["feed_title"] or ""),
                "url": str(r["url"] or ""),
                "publishedAt": str(r["published_at"] or ""),
                "read": bool(r["read"]),
                "starred": bool(r["starred"]),
            }
            for r in sample
        ],
        "truncated": len(rows) > _PREVIEW_SAMPLE,
        "effectiveExclusions": ["starred"],
    }


class ArchiveBatchStore:
    """收据台账（new219_archive_batches）+ 归档/撤销的 DB 部分。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def snapshot_rows(self, refs: list[str]) -> dict[str, dict[str, Any]]:
        """按全量 ItemRef（rss:…）索引的投影状态快照；投影列 entry_ref 是
        裸 entryRef，查询前去掉 ``rss:`` 前缀。"""
        await self._db.migrate()
        snapshots: dict[str, dict[str, Any]] = {}
        bare = [r[len("rss:") :] for r in refs if r.startswith("rss:")]
        for start in range(0, len(bare), 100):
            chunk = bare[start : start + 100]
            placeholders = ",".join("?" for _ in chunk)
            rows = await self._db.fetch_all(
                f"SELECT entry_ref, read, starred FROM search_entries WHERE entry_ref IN ({placeholders})",
                (*chunk,),
            )
            for row in rows:
                snapshots[f"rss:{row['entry_ref']}"] = {
                    "read": int(row["read"]),
                    "starred": int(row["starred"]),
                }
        return snapshots

    async def refused_starred(self, refs: list[str]) -> list[str]:
        await self._db.migrate()
        snapshots = await self.snapshot_rows(refs)
        return [
            ref
            for ref in refs
            if snapshots.get(ref, {}).get("starred", 0) == 1
        ]

    async def record_batch(
        self,
        *,
        archived: list[str],
        snapshots: dict[str, dict[str, Any]],
        failed: list[dict[str, str]],
    ) -> dict[str, Any]:
        batch_id = str(uuid.uuid4())
        created_at = utc_now()
        await self._db.migrate()
        await self._db.execute(
            "INSERT INTO new219_archive_batches (id, refs_json, snapshots_json, archived_count, failed_json, created_at, undone_at) VALUES (?, ?, ?, ?, ?, ?, NULL)",
            (
                batch_id,
                json.dumps(archived, ensure_ascii=False),
                json.dumps({ref: snapshots[ref] for ref in archived if ref in snapshots}, ensure_ascii=False),
                len(archived),
                json.dumps(failed, ensure_ascii=False),
                created_at,
            ),
        )
        return {
            "batchId": batch_id,
            "archived": archived,
            "failed": failed,
            "createdAt": created_at,
        }

    async def get_batch(self, batch_id: str) -> dict[str, Any]:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, refs_json, snapshots_json, archived_count, failed_json, created_at, undone_at FROM new219_archive_batches WHERE id = ?",
            (batch_id,),
        )
        if row is None:
            raise ArchiveBatchNotFound(batch_id)
        return self._row_to_receipt(row)

    async def list_batches(self) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, refs_json, snapshots_json, archived_count, failed_json, created_at, undone_at FROM new219_archive_batches ORDER BY created_at DESC LIMIT ?",
            (_RECEIPT_LIST_CAP,),
        )
        return [self._row_to_receipt(row) for row in rows]

    def _row_to_receipt(self, row: Any) -> dict[str, Any]:
        try:
            refs = json.loads(str(row["refs_json"]))
            snapshots = json.loads(str(row["snapshots_json"]))
            failed = json.loads(str(row["failed_json"]))
        except ValueError:
            refs, snapshots, failed = [], {}, []
        return {
            "batchId": str(row["id"]),
            "refs": refs if isinstance(refs, list) else [],
            "snapshots": snapshots if isinstance(snapshots, dict) else {},
            "archivedCount": int(row["archived_count"]),
            "failed": failed if isinstance(failed, list) else [],
            "createdAt": str(row["created_at"]),
            "undoneAt": str(row["undone_at"]) if row["undone_at"] is not None else None,
        }

    async def undo_batch(
        self,
        batch_id: str,
        *,
        restore_fn: Any,
    ) -> dict[str, Any]:
        """撤销：逐条状态守卫后调 restore_fn(ref)（适配器 + 投影镜像）。

        restore_fn 由路由注入（需要 adapter/search 服务），失败按单条
        failed 收集，不中断整批。收据单向：undone_at 非空 → 409。
        """
        receipt = await self.get_batch(batch_id)
        if receipt["undoneAt"] is not None:
            raise ArchiveBatchConflict("这批归档已经撤销过。")
        current = await self.snapshot_rows(list(receipt["refs"]))
        restored: list[str] = []
        skipped: list[dict[str, str]] = []
        failed: list[dict[str, str]] = []
        for ref in receipt["refs"]:
            snapshot = receipt["snapshots"].get(ref)
            now = current.get(ref)
            if snapshot is None or now is None:
                skipped.append({"ref": ref, "reason": "not_found"})
                continue
            if now["read"] == 0:
                skipped.append({"ref": ref, "reason": "already_unread"})
                continue
            if now["starred"] != snapshot["starred"]:
                skipped.append({"ref": ref, "reason": "modified_since"})
                continue
            try:
                await restore_fn(ref)
                restored.append(ref)
            except Exception:  # noqa: BLE001 — 单条失败不中断整批
                failed.append({"ref": ref, "reason": "restore_failed"})
        await self._db.execute(
            "UPDATE new219_archive_batches SET undone_at = ? WHERE id = ?",
            (utc_now(), batch_id),
        )
        return {
            "batchId": batch_id,
            "restored": restored,
            "skipped": skipped,
            "failed": failed,
        }
