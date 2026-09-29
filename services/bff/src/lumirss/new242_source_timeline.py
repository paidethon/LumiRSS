"""NEW-242 来源时间轴 —— 发表 / 接收 / 更新 / 个人保存四类时间 + 出处说明。

语义边界（模块存在的理由）：

- 时间轴是**派生读**：查询时从既有事实表聚合，绝不 shadow-copy：
  * published：search_entries.published_at —— 上游 feed 声明的发表
    时间（经 FreshRSS 中转），Lumi 无法独立验证；
  * received：search_entries.fetched_at —— 本实例抓取成功的时间；
  * updated：entry_revisions 最新一条 captured_at —— N031 摄取历史
    里最近一次检测到内容变动的时刻（没有修订记录 ≠ 没有更新过，
    诚实显示未知）；
  * saved：library_bookmarks（item_type='rss'，rss_item_ref 匹配）
    的 created_at —— 用户把该文存入书签的时刻；未保存 → 未知。
- 每个时间都带 source 字段说明它从哪来；缺失的时间 available=false
  并说明原因（资料缺失 ≠ 事件没发生）；
- 用户备注：source_time_annotations 每类时间至多一条（用户对时间
  出处的个人说明 / 修正记录），per-user 隔离。

search_entries 投影中没有该文 → available 全部为 false + 诚实说明
（不编造时间）。
"""

import uuid as _uuid
from datetime import UTC, datetime
from typing import Any

from lumirss.db_tx import transaction
from lumirss.storage import Database
from lumirss.util import utc_now

_KINDS = ("published", "received", "updated", "saved")

_KIND_LABELS = {
    "published": "发表",
    "received": "接收",
    "updated": "更新",
    "saved": "个人保存",
}


class TimelineInvalid(ValueError):
    """时间备注负载非法（映射 422）。"""


def _epoch_to_iso(value: Any) -> str | None:
    try:
        seconds = int(value)
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    return datetime.fromtimestamp(seconds, tz=UTC).isoformat(timespec="seconds")


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class SourceTimelineStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    # -- 时间轴（派生读） --------------------------------------------------

    async def build_timeline(self, entry_ref: str) -> dict[str, Any]:
        await self._db.migrate()
        entry_row = await self._db.fetch_one(
            "SELECT published_at, fetched_at FROM search_entries WHERE entry_ref = ?",
            (entry_ref,),
        )
        revision_row = await self._db.fetch_one(
            "SELECT captured_at FROM entry_revisions WHERE entry_ref = ? "
            "ORDER BY id DESC LIMIT 1",
            (entry_ref,),
        )
        saved_row = await self._db.fetch_one(
            "SELECT b.created_at FROM library_bookmarks b WHERE b.item_type = 'rss' AND b.rss_item_ref = ?",
            (f"rss:{entry_ref}",),
        )
        projection_known = entry_row is not None

        published_raw = _clean_text(entry_row["published_at"]) if entry_row is not None else None
        received_iso = _epoch_to_iso(entry_row["fetched_at"]) if entry_row is not None else None
        updated_iso = _clean_text(revision_row["captured_at"]) if revision_row is not None else None
        saved_iso = _clean_text(saved_row["created_at"]) if saved_row is not None else None

        items: list[dict[str, Any]] = [
            {
                "kind": "published",
                "label": _KIND_LABELS["published"],
                "time": published_raw,
                "available": published_raw is not None,
                "source": (
                    "上游 feed 声明的发表时间（经 FreshRSS 中转；Lumi 未独立验证）"
                    if published_raw is not None
                    else "投影中没有这篇文章的发表时间（未同步或上游未提供）"
                ),
            },
            {
                "kind": "received",
                "label": _KIND_LABELS["received"],
                "time": received_iso,
                "available": received_iso is not None,
                "source": (
                    "本实例抓取成功的时间（search_entries.fetched_at）"
                    if received_iso is not None
                    else "投影中没有这篇文章的抓取时间（未同步或已清理）"
                ),
            },
            {
                "kind": "updated",
                "label": _KIND_LABELS["updated"],
                "time": updated_iso,
                "available": updated_iso is not None,
                "source": (
                    "摄取历史最近一次检测到内容变动的时刻（entry_revisions）；没有记录不等于没更新过"
                    if updated_iso is not None
                    else "摄取历史没有该文的修订记录——不代表上游没有更新，只是未观测到"
                ),
            },
            {
                "kind": "saved",
                "label": _KIND_LABELS["saved"],
                "time": saved_iso,
                "available": saved_iso is not None,
                "source": (
                    "你把该文存入书签的时刻（library_bookmarks）"
                    if saved_iso is not None
                    else "你还没有把该文存入书签——没有个人保存时间"
                ),
            },
        ]
        return {"entryRef": entry_ref, "projectionKnown": projection_known, "items": items}

    # -- 用户备注 ----------------------------------------------------------

    @staticmethod
    def _validate_kind(kind: Any) -> str:
        if kind not in _KINDS:
            raise TimelineInvalid("kind 必须是 published/received/updated/saved 之一。")
        return str(kind)

    @staticmethod
    def _validate_note(note: Any) -> str:
        if not isinstance(note, str) or not 1 <= len(note.strip()) <= 500:
            raise TimelineInvalid("备注必须是 1-500 个字符。")
        return note.strip()

    async def put_annotation(self, entry_ref: str, kind: str, note: str) -> dict[str, Any]:
        """写（或改写）某类时间上的个人备注。"""
        clean_kind = self._validate_kind(kind)
        clean_note = self._validate_note(note)
        annotation_id = str(_uuid.uuid4())
        now = utc_now()

        def _tx(conn: Any) -> None:
            existing = conn.execute(
                "SELECT id FROM source_time_annotations WHERE entry_ref = ? AND kind = ?",
                (entry_ref, clean_kind),
            ).fetchone()
            if existing is None:
                conn.execute(
                    "INSERT INTO source_time_annotations (id, entry_ref, kind, note, created_at) VALUES (?, ?, ?, ?, ?)",
                    (annotation_id, entry_ref, clean_kind, clean_note, now),
                )
            else:
                conn.execute(
                    "UPDATE source_time_annotations SET note = ? WHERE id = ?",
                    (clean_note, str(existing["id"])),
                )

        await transaction(self._db, _tx)
        return {"entryRef": entry_ref, "kind": clean_kind, "note": clean_note}

    async def list_annotations(self, entry_ref: str) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT kind, note, created_at FROM source_time_annotations "
            "WHERE entry_ref = ? ORDER BY created_at DESC",
            (entry_ref,),
        )
        return [
            {
                "kind": str(row["kind"]),
                "label": _KIND_LABELS.get(str(row["kind"]), str(row["kind"])),
                "note": str(row["note"]),
                "createdAt": str(row["created_at"]),
            }
            for row in rows
        ]
