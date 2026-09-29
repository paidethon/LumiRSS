"""NEW-230 队列重复主题提醒 —— 用户自选主题的集中度提示。

- 主题是**用户手动标注**的自选标签（挂在今日队列成员上）——服务端
  绝不自动推断、绝不预填兴趣；
- 集中度报告只在用户主动整理时计算（``GET report``）：每主题的
  成员数、在队列中的位置、以及「主题内成员互相隔了多远」
  （minGap，按队列 position）——纯建议性数据；
- 「允许调换位置」= 用户用既有 PUT /queue/today/order 手动重排；
  本模块没有任何写队列顺序的路径，绝不自动替用户决定兴趣。
"""

import uuid
from typing import Any

from lumirss.itemref import InvalidItemRef, parse_item_ref
from lumirss.reading_queue import today_queue_date
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_TOPICS_PER_ITEM = 5
_MAX_TOPIC_LENGTH = 30
_MAX_REPORT_ITEMS = 200


class TopicInvalid(Exception):
    """主题载荷非法——422 invalid_queue_topic。"""


def validate_topic(topic: str) -> str:
    if not isinstance(topic, str):
        raise TopicInvalid("topic 必须是字符串。")
    clean = topic.strip()
    if not clean:
        raise TopicInvalid("topic 不能为空（清除请整体 set 空表）。")
    if len(clean) > _MAX_TOPIC_LENGTH:
        raise TopicInvalid(f"topic 最长 {_MAX_TOPIC_LENGTH} 字符。")
    return clean


def validate_ref(value: str) -> str:
    try:
        parse_item_ref(value)
    except InvalidItemRef as exc:
        raise TopicInvalid(f"itemRef 不合法：{exc}") from exc
    return value


class QueueTopicStore:
    """Persistence for queue_topic_marks."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def set_topics(self, item_ref: str, topics: list[str]) -> dict[str, Any]:
        """整体替换该成员今日的主题标注（set 语义；空表 = 清除）。"""
        await self._db.migrate()
        validate_ref(item_ref)
        if not isinstance(topics, list) or len(topics) > _MAX_TOPICS_PER_ITEM:
            raise TopicInvalid(f"topics 最多 {_MAX_TOPICS_PER_ITEM} 个。")
        cleaned: list[str] = []
        for topic in topics:
            clean = validate_topic(topic)
            if clean not in cleaned:
                cleaned.append(clean)
        day = today_queue_date()

        from lumirss.db_tx import transaction

        def _tx(conn: Any) -> None:
            conn.execute(
                "DELETE FROM queue_topic_marks WHERE queue_date = ? AND item_ref = ?",
                (day, item_ref),
            )
            for clean in cleaned:
                conn.execute(
                    "INSERT INTO queue_topic_marks (id, queue_date, item_ref,"
                    " topic, created_at) VALUES (?, ?, ?, ?, ?)",
                    (f"qtop-{uuid.uuid4().hex}", day, item_ref, clean, utc_now()),
                )

        await transaction(self._db, _tx)
        return {"itemRef": item_ref, "queueDate": day, "topics": cleaned}

    async def get_topics(self, item_ref: str) -> dict[str, Any]:
        await self._db.migrate()
        validate_ref(item_ref)
        rows = await self._db.fetch_all(
            "SELECT topic FROM queue_topic_marks"
            " WHERE queue_date = ? AND item_ref = ? ORDER BY created_at ASC",
            (today_queue_date(), item_ref),
        )
        return {
            "itemRef": item_ref,
            "topics": [str(row["topic"]) for row in rows],
        }

    async def report(self) -> dict[str, Any]:
        """今日队列的自选主题集中度（advisory；用户主动整理时看）。"""
        await self._db.migrate()
        day = today_queue_date()
        rows = await self._db.fetch_all(
            "SELECT q.entry_ref AS item_ref, q.position, q.status, q.segment,"
            " t.topic FROM reading_queue q"
            " JOIN queue_topic_marks t ON t.queue_date = q.queue_date"
            "  AND t.item_ref = q.entry_ref"
            " WHERE q.queue_date = ? AND q.status != 'removed'"
            " ORDER BY q.position ASC, q.rowid ASC"
            f" LIMIT {_MAX_REPORT_ITEMS}",
            (day,),
        )
        by_topic: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            topic = str(row["topic"])
            by_topic.setdefault(topic, []).append(
                {
                    "itemRef": str(row["item_ref"]),
                    "position": int(row["position"]),
                    "segment": row["segment"],
                    "status": str(row["status"]),
                }
            )
        topics = []
        for topic, members in by_topic.items():
            positions = sorted(member["position"] for member in members)
            # 相邻位置差（positions[1:] 恒比 positions 短一，strict 必须 False）
            min_gap = (
                min(b - a for a, b in zip(positions, positions[1:], strict=False))
                if len(positions) > 1
                else None
            )
            segments = sorted(
                {str(member["segment"]) for member in members if member["segment"]}
            )
            topics.append(
                {
                    "topic": topic,
                    "itemCount": len(members),
                    "positions": positions,
                    "minGap": min_gap,
                    "segments": segments,
                    "members": members,
                }
            )
        topics.sort(key=lambda entry: (-entry["itemCount"], entry["topic"]))
        duplicated = [entry for entry in topics if entry["itemCount"] > 1]
        return {
            "queueDate": day,
            "topics": topics,
            "duplicatedTopics": duplicated,
            "advisory": True,
            "note": (
                "主题集中度只是提示：要不要调换位置、怎么调，由你手动决定"
                "（拖拽 / PUT /queue/today/order）；服务端绝不自动重排。"
            ),
        }
