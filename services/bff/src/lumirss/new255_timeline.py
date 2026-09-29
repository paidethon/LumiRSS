"""NEW-255 事件时间线编辑器 —— 事件发生时间 vs 报道时间。

- event_at：事件发生时间。按用户掌握的精度原文登记（「1997 年」
  「约 2003 年春」都是合法值）——不统一改写成机器时间；
- reported_at：报道时间（可选）——媒体什么时候说的；
- 两者都形如 YYYY-MM-DD 前缀时才计算 reported_days_after；解析不了
  就诚实返回 null，绝不猜时间差；
- item_ref：出处（只引用不复制）。列表按登记顺序返回，排序视图由
  前端按可解析日期呈现（无法解析的行标注 unparseable，绝不排错位）。
"""

import uuid as _uuid
from datetime import date
from typing import Any

from lumirss.new251_research import (
    _clean,
    clean_item_ref,
    require_project,
)
from lumirss.util import utc_now

MAX_TITLE = 300


def _parse_date_prefix(value: str) -> date | None:
    """取 YYYY-MM-DD 前缀解析；不行就 None（诚实，不猜）。"""
    prefix = value[:10]
    if len(prefix) < 10:
        return None
    try:
        return date.fromisoformat(prefix)
    except ValueError:
        return None


def days_between(event_at: str, reported_at: str) -> int | None:
    left = _parse_date_prefix(event_at)
    right = _parse_date_prefix(reported_at)
    if left is None or right is None:
        return None
    return (right - left).days


class TimelineEventNotFound(Exception):
    """时间线事件不存在（映射 404）。"""


class TimelineStore:
    def __init__(self, db: Any) -> None:
        self._db = db

    async def _row(self, event_id: str) -> dict[str, Any]:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT * FROM research_timeline_events WHERE id = ?", (event_id,)
        )
        if row is None:
            raise TimelineEventNotFound(event_id)
        return dict(row)

    @staticmethod
    def _view(row: dict[str, Any]) -> dict[str, Any]:
        event_at = str(row["event_at"])
        reported = row["reported_at"]
        reported_at = None if reported is None else str(reported)
        gap = days_between(event_at, reported_at) if reported_at else None
        return {
            "id": str(row["id"]),
            "projectId": str(row["project_id"]),
            "title": str(row["title"]),
            "eventAt": event_at,
            "reportedAt": reported_at,
            "eventDateParsed": None if _parse_date_prefix(event_at) is None else event_at[:10],
            "reportedDateParsed": (
                None if reported_at is None or _parse_date_prefix(reported_at) is None else reported_at[:10]
            ),
            "reportedDaysAfter": gap,
            "itemRef": row["item_ref"] if row["item_ref"] is None else str(row["item_ref"]),
            "note": row["note"] if row["note"] is None else str(row["note"]),
            "createdAt": str(row["created_at"]),
            "updatedAt": str(row["updated_at"]),
        }

    async def create(
        self,
        project_id: str,
        *,
        title: Any,
        event_at: Any,
        reported_at: Any = None,
        item_ref: Any = None,
        note: Any = None,
    ) -> dict[str, Any]:
        await require_project(self._db, project_id)
        clean_title = _clean(title, label="title", max_len=MAX_TITLE)
        assert clean_title is not None
        clean_event = _clean(event_at, label="eventAt", max_len=60)
        assert clean_event is not None
        clean_reported = _clean(reported_at, label="reportedAt", max_len=60, required=False)
        ref = clean_item_ref(item_ref)
        clean_note = _clean(note, label="note", max_len=1000, required=False)
        event_id = str(_uuid.uuid4())
        now = utc_now()
        await self._db.execute(
            "INSERT INTO research_timeline_events (id, project_id, title, event_at, reported_at, "
            "item_ref, note, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (event_id, project_id, clean_title, clean_event, clean_reported, ref, clean_note, now, now),
        )
        return self._view(await self._row(event_id))

    async def list(self, project_id: str) -> dict[str, Any]:
        await require_project(self._db, project_id)
        rows = await self._db.fetch_all(
            "SELECT id FROM research_timeline_events WHERE project_id = ? "
            "ORDER BY created_at ASC, rowid ASC",
            (project_id,),
        )
        items = [self._view(await self._row(str(row["id"]))) for row in rows]
        unparseable = sum(1 for item in items if item["eventDateParsed"] is None)
        return {
            "projectId": project_id,
            "note": "排序视图按 eventAt 可解析日期呈现；无法解析的行标注为未解析，绝不估位。",
            "unparseableCount": unparseable,
            "items": items,
        }

    async def update(
        self,
        event_id: str,
        *,
        title: Any = None,
        event_at: Any = None,
        reported_at: Any = None,
        item_ref: Any = None,
        note: Any = None,
    ) -> dict[str, Any]:
        row = await self._row(event_id)
        clean_title = (
            _clean(title, label="title", max_len=MAX_TITLE) if title is not None else str(row["title"])
        )
        assert clean_title is not None
        clean_event = (
            _clean(event_at, label="eventAt", max_len=60) if event_at is not None else str(row["event_at"])
        )
        assert clean_event is not None
        clean_reported = (
            _clean(reported_at, label="reportedAt", max_len=60, required=False)
            if reported_at is not None
            else row["reported_at"]
        )
        ref = clean_item_ref(item_ref) if item_ref is not None else row["item_ref"]
        clean_note = (
            _clean(note, label="note", max_len=1000, required=False)
            if note is not None
            else row["note"]
        )
        await self._db.execute(
            "UPDATE research_timeline_events SET title = ?, event_at = ?, reported_at = ?, "
            "item_ref = ?, note = ?, updated_at = ? WHERE id = ?",
            (clean_title, clean_event, clean_reported, ref, clean_note, utc_now(), event_id),
        )
        return self._view(await self._row(event_id))

    async def delete(self, event_id: str) -> None:
        await self._row(event_id)
        await self._db.execute("DELETE FROM research_timeline_events WHERE id = ?", (event_id,))
