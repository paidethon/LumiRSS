"""NEW-288 跨期主题追踪 —— 主题锚点 + 跨期条目链（期次位置保留）。

- 主题 = 用户命名（每用户库内名字唯一；同建同取，幂等）；
- 挂载：把某期里的某条目挂到主题下（期次 + 条目双坐标都存——「保留
  期次位置」）；链上顺序 = 期次确认时间 → 期次内条目位置，后挂的
  就是「后续更新链」；
- 只聚合用户自己显式挂载的条目，绝不自动归类（诚实边界）。

per-user：主题与链在 per-user 库，A 的主题对 B 不可见。
"""

import uuid as _uuid
from typing import Any

from lumirss.new281_briefings import BriefingNotFound
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_NAME = 80


class TopicInvalid(ValueError):
    """主题负载非法（映射 422）。"""


def clean_topic_name(raw: Any) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise TopicInvalid("主题名不能为空。")
    name = raw.strip()
    if len(name) > _MAX_NAME:
        raise TopicInvalid(f"主题名不能超过 {_MAX_NAME} 字符。")
    return name


class TopicStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get_or_create(self, raw_name: Any) -> dict[str, Any]:
        name = clean_topic_name(raw_name)
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, name, created_at FROM briefing_topics WHERE name = ?",
            (name,),
        )
        if row is not None:
            return {"id": str(row["id"]), "name": str(row["name"]), "createdAt": str(row["created_at"]), "created": False}
        topic_id = str(_uuid.uuid4())
        now = utc_now()
        await self._db.execute(
            "INSERT INTO briefing_topics (id, name, created_at) VALUES (?, ?, ?)",
            (topic_id, name, now),
        )
        return {"id": topic_id, "name": name, "createdAt": now, "created": True}

    async def list_topics(self) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT t.id, t.name, t.created_at, COUNT(e.id) AS entry_count"
            " FROM briefing_topics t"
            " LEFT JOIN briefing_topic_entries e ON e.topic_id = t.id"
            " GROUP BY t.id ORDER BY t.created_at ASC"
        )
        return [
            {
                "id": str(row["id"]),
                "name": str(row["name"]),
                "createdAt": str(row["created_at"]),
                "entryCount": int(row["entry_count"]),
            }
            for row in rows
        ]

    async def attach(
        self, topic_id: str, *, briefing_id: str, item_id: str
    ) -> dict[str, Any]:
        """把某期里的条目挂到主题（条目必须真实属于该期）。"""
        await self._db.migrate()
        topic = await self._db.fetch_one(
            "SELECT id, name FROM briefing_topics WHERE id = ?", (topic_id,)
        )
        if topic is None:
            raise BriefingNotFound("主题不存在。")
        item = await self._db.fetch_one(
            "SELECT id, briefing_id, entry_ref, title FROM briefing_items"
            " WHERE id = ? AND briefing_id = ?",
            (item_id, briefing_id),
        )
        if item is None:
            raise BriefingNotFound("期次或条目不存在。")
        existing = await self._db.fetch_one(
            "SELECT id FROM briefing_topic_entries WHERE topic_id = ?"
            " AND briefing_item_id = ?",
            (topic_id, item_id),
        )
        if existing is not None:
            return {"attached": False, "reason": "该条目已在主题链上。"}
        now = utc_now()
        await self._db.execute(
            "INSERT INTO briefing_topic_entries (id, topic_id, briefing_id,"
            " briefing_item_id, entry_ref, noted_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                str(_uuid.uuid4()),
                topic_id,
                briefing_id,
                item_id,
                str(item["entry_ref"]),
                now,
            ),
        )
        return {"attached": True, "topicId": topic_id, "itemId": item_id}

    async def chain(self, topic_id: str) -> dict[str, Any]:
        """跨期链：期次位置（期次标题/确认时间）+ 顺序即后续更新链。"""
        await self._db.migrate()
        topic = await self._db.fetch_one(
            "SELECT id, name, created_at FROM briefing_topics WHERE id = ?",
            (topic_id,),
        )
        if topic is None:
            raise BriefingNotFound("主题不存在。")
        rows = await self._db.fetch_all(
            "SELECT e.id, e.entry_ref, e.briefing_id, e.briefing_item_id,"
            " e.noted_at, bi.title, bi.feed_title, bi.url, bi.excerpt,"
            " bi.section_key, bi.position, b.title AS issue_title,"
            " b.status AS issue_status, b.confirmed_at AS issue_confirmed_at"
            " FROM briefing_topic_entries e"
            " JOIN briefing_items bi ON bi.id = e.briefing_item_id"
            " JOIN briefings b ON b.id = e.briefing_id"
            " WHERE e.topic_id = ?"
            " ORDER BY COALESCE(b.confirmed_at, b.created_at) ASC,"
            " bi.position ASC",
            (topic_id,),
        )
        entries = [
            {
                "entryRef": str(row["entry_ref"]),
                "itemId": str(row["briefing_item_id"]),
                "briefingId": str(row["briefing_id"]),
                "issueTitle": str(row["issue_title"]),
                "issueStatus": str(row["issue_status"]),
                "issueConfirmedAt": str(row["issue_confirmed_at"] or "") or None,
                "sectionKey": str(row["section_key"]),
                "position": int(row["position"]),
                "title": str(row["title"]),
                "feedTitle": str(row["feed_title"]),
                "url": str(row["url"]),
                "excerpt": str(row["excerpt"]),
                "notedAt": str(row["noted_at"]),
            }
            for row in rows
        ]
        return {
            "id": str(topic["id"]),
            "name": str(topic["name"]),
            "createdAt": str(topic["created_at"]),
            "entries": entries,
            "honestyNote": (
                "链上顺序 = 期次确认时间 + 期次内位置；越靠后越是后续更新。"
                "只含你显式挂载的条目，系统绝不自动归类。"
            ),
        }
