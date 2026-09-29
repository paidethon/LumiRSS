"""NEW-220 个人收件箱处理记录 —— 整理轨迹台账（从哪里移到哪里 + 原因）。

每次整理（收件箱归类、批量搬移等）由调用方落一条记录：
- from_location / to_location：自由位置标签（如「收件箱」「工作区:调研」
  「稍后读」），记录语义而非强约束——台账的价值在诚实记录用户自己
  声称的移动；
- refs：涉及的 ItemRef（形状校验，最多 200；允许此刻已失效的引用——
  整理记录是历史事实，不做解析门禁）；
- reason：用户给出的原因（≤500 字符，原样保存）；
- 查询：按日期（YYYY-MM-DD，UTC）过滤 + 位置包含过滤，按时间倒序，
  服务端按日分组返回（有界 200 行/页）。
"""

import json
import uuid
from typing import Any

from lumirss.itemref import parse_item_ref
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_REFS = 200
_MAX_LOCATION = 60
_MAX_REASON = 500
_PAGE_LIMIT = 200


class TriageJournalInvalid(ValueError):
    """台账载荷非法（位置/引用形状/原因长度），映射 422。"""


class TriageJournalNotFound(Exception):
    """记录不存在，映射 404。"""


class TriageJournalStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self, *, from_location: str, to_location: str, refs: list[str], reason: str
    ) -> dict[str, Any]:
        clean_from = from_location.strip()
        clean_to = to_location.strip()
        if not clean_from or len(clean_from) > _MAX_LOCATION:
            raise TriageJournalInvalid(f"from_location 必须是 1-{_MAX_LOCATION} 个字符。")
        if not clean_to or len(clean_to) > _MAX_LOCATION:
            raise TriageJournalInvalid(f"to_location 必须是 1-{_MAX_LOCATION} 个字符。")
        if clean_from == clean_to:
            raise TriageJournalInvalid("from_location 与 to_location 相同，不是一次移动。")
        cleaned_refs: list[str] = []
        for ref in refs:
            try:
                formatted = parse_item_ref(ref).format()
            except ValueError as exc:
                raise TriageJournalInvalid(f"引用形状非法：{ref}") from exc
            if formatted not in cleaned_refs:
                cleaned_refs.append(formatted)
        if not 1 <= len(cleaned_refs) <= _MAX_REFS:
            raise TriageJournalInvalid(f"refs 数量必须是 1-{_MAX_REFS}。")
        clean_reason = reason.strip()
        if len(clean_reason) > _MAX_REASON:
            raise TriageJournalInvalid(f"原因最多 {_MAX_REASON} 个字符。")
        entry_id = str(uuid.uuid4())
        created_at = utc_now()
        await self._db.migrate()
        await self._db.execute(
            "INSERT INTO new220_triage_journal (id, from_location, to_location, refs_json, reason, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                entry_id,
                clean_from,
                clean_to,
                json.dumps(cleaned_refs, ensure_ascii=False),
                clean_reason,
                created_at,
            ),
        )
        return {
            "id": entry_id,
            "fromLocation": clean_from,
            "toLocation": clean_to,
            "refs": cleaned_refs,
            "reason": clean_reason,
            "createdAt": created_at,
        }

    async def delete(self, entry_id: str) -> bool:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id FROM new220_triage_journal WHERE id = ?", (entry_id,)
        )
        if row is None:
            return False
        await self._db.execute(
            "DELETE FROM new220_triage_journal WHERE id = ?", (entry_id,)
        )
        return True

    async def list_entries(
        self,
        *,
        date: str | None = None,
        location: str | None = None,
        limit: int = _PAGE_LIMIT,
    ) -> dict[str, Any]:
        """按时间倒序的有界分页；date=YYYY-MM-DD（UTC）精确过滤；
        location 是 from/to 的包含匹配。返回按日分组的轨迹。"""
        await self._db.migrate()
        where: list[str] = []
        params: list[Any] = []
        if date:
            if len(date) != 10 or date[4] != "-" or date[7] != "-":
                raise TriageJournalInvalid("date 必须是 YYYY-MM-DD（UTC）。")
            where.append("created_at >= ? AND created_at < ?")
            params.extend([f"{date}T00:00:00", f"{date}~"])  # '~' > 任何同日前缀字符
        if location and location.strip():
            needle = f"%{location.strip()}%"
            where.append("(from_location LIKE ? OR to_location LIKE ?)")
            params.extend([needle, needle])
        clause = f" WHERE {' AND '.join(where)}" if where else ""
        rows = await self._db.fetch_all(
            "SELECT id, from_location, to_location, refs_json, reason, created_at FROM new220_triage_journal"
            f"{clause} ORDER BY created_at DESC LIMIT ?",
            (*params, max(1, min(limit, _PAGE_LIMIT))),
        )
        entries: list[dict[str, Any]] = []
        for row in rows:
            try:
                refs = json.loads(str(row["refs_json"]))
            except ValueError:
                refs = []
            created_at = str(row["created_at"])
            entries.append(
                {
                    "id": str(row["id"]),
                    "fromLocation": str(row["from_location"]),
                    "toLocation": str(row["to_location"]),
                    "refs": refs if isinstance(refs, list) else [],
                    "reason": str(row["reason"] or ""),
                    "createdAt": created_at,
                }
            )
        days: list[dict[str, Any]] = []
        by_day: dict[str, list[dict[str, Any]]] = {}
        for entry in entries:
            by_day.setdefault(entry["createdAt"][:10], []).append(entry)
        for day in sorted(by_day, reverse=True):
            days.append({"date": day, "entries": by_day[day]})
        return {"days": days, "count": len(entries)}
