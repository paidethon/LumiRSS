"""NEW-331 共读会议资料单 —— 成员把明确共享的文章和待讨论问题组成一次
会议资料单，结束后保存结论与出处。

隐私前提：资料项只来自成员的**显式添加**（title/excerpt 快照在添加
时点固化，绝不自动跟随私人库变化）；结论只在会议 closed 之后允许
写入（「结束后保存结论与出处」）；出处是显式填写的 entry_ref/引文
说明，不自动生成。

存储：控制库（跨用户是控制关注点，与 NEW-236 同一先例）；访问控制
复用 space_core 统一守卫。
"""

import uuid as _uuid
from typing import Any

from lumirss.space_core import MAX_NAME, SpaceForbidden, SpaceInvalid, SpaceStore
from lumirss.storage import Database
from lumirss.util import utc_now

MAX_EXCERPT = 4000
MAX_QUESTION = 2000
MAX_SUMMARY = 4000
MAX_ITEMS_PER_MEETING = 100
MAX_OUTCOMES_PER_MEETING = 100


class MeetingNotFound(Exception):
    """会议不存在（或不属于该空间）——404 meeting_not_found。"""


def _clean(value: Any, field: str, limit: int, *, required: bool = True) -> str:
    if value is None:
        if required:
            raise SpaceInvalid(f"{field} 不能为空。")
        return ""
    if not isinstance(value, str):
        raise SpaceInvalid(f"{field} 必须是字符串。")
    clean = value.strip()
    if required and not clean:
        raise SpaceInvalid(f"{field} 不能为空。")
    if len(clean) > limit:
        raise SpaceInvalid(f"{field} 最长 {limit} 字符。")
    return clean


class MeetingStore:
    def __init__(self, control_db: Database, spaces: SpaceStore) -> None:
        self._db = control_db
        self._spaces = spaces

    # -- 行级助手 ----------------------------------------------------------

    async def _meeting(self, space_id: str, meeting_id: str) -> dict[str, Any]:
        row = await self._db.fetch_one(
            "SELECT * FROM space_meetings WHERE id = ? AND space_id = ?",
            (meeting_id, space_id),
        )
        if row is None:
            raise MeetingNotFound(meeting_id)
        return dict(row)

    async def _items(self, meeting_id: str) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT * FROM space_meeting_items WHERE meeting_id = ? ORDER BY created_at ASC, rowid ASC",
            (meeting_id,),
        )
        return [self._item_view(dict(row)) for row in rows]

    @staticmethod
    def _item_view(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "meetingId": str(row["meeting_id"]),
            "entryRef": str(row["entry_ref"]),
            "title": str(row["title"]),
            "excerpt": str(row["excerpt"]),
            "question": row["question"],
            "addedBy": str(row["added_by"]),
            "addedByUsername": str(row["added_by_username"]),
            "createdAt": str(row["created_at"]),
        }

    @staticmethod
    def _view(
        row: dict[str, Any],
        *,
        items: list[dict[str, Any]] | None = None,
        outcomes: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        view = {
            "id": str(row["id"]),
            "spaceId": str(row["space_id"]),
            "title": str(row["title"]),
            "status": str(row["status"]),
            "createdBy": str(row["created_by"]),
            "createdByUsername": str(row["created_by_username"]),
            "closedAt": row["closed_at"],
            "createdAt": str(row["created_at"]),
        }
        if items is not None:
            view["items"] = items
        if outcomes is not None:
            view["outcomes"] = outcomes
        return view

    async def _outcomes(self, meeting_id: str) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT * FROM space_meeting_outcomes WHERE meeting_id = ? ORDER BY created_at ASC, rowid ASC",
            (meeting_id,),
        )
        return [
            {
                "id": str(row["id"]),
                "meetingId": str(row["meeting_id"]),
                "entryRef": row["entry_ref"],
                "summary": str(row["summary"]),
                "createdBy": str(row["created_by"]),
                "createdByUsername": str(row["created_by_username"]),
                "createdAt": str(row["created_at"]),
            }
            for row in rows
        ]

    # -- 会议 ---------------------------------------------------------------

    async def create(
        self, space_id: str, *, actor_user_id: str, actor_username: str, title: Any
    ) -> dict[str, Any]:
        await self._spaces.require_member(space_id, actor_user_id, write=True)
        clean = _clean(title, "title", MAX_NAME)
        now = utc_now()
        meeting_id = str(_uuid.uuid4())
        await self._db.execute(
            "INSERT INTO space_meetings (id, space_id, title, status, created_by, created_by_username, closed_at, created_at) "
            "VALUES (?, ?, ?, 'open', ?, ?, NULL, ?)",
            (meeting_id, space_id, clean, actor_user_id, actor_username, now),
        )
        return self._view(await self._meeting(space_id, meeting_id), items=[], outcomes=[])

    async def get(self, space_id: str, meeting_id: str, *, actor_user_id: str) -> dict[str, Any]:
        await self._spaces.require_member(space_id, actor_user_id)
        row = await self._meeting(space_id, meeting_id)
        return self._view(
            row, items=await self._items(meeting_id), outcomes=await self._outcomes(meeting_id)
        )

    async def list_for_space(self, space_id: str, *, actor_user_id: str) -> list[dict[str, Any]]:
        await self._spaces.require_member(space_id, actor_user_id)
        rows = await self._db.fetch_all(
            "SELECT * FROM space_meetings WHERE space_id = ? ORDER BY created_at DESC, rowid DESC",
            (space_id,),
        )
        return [self._view(dict(row)) for row in rows]

    # -- 资料项（显式共享快照） ---------------------------------------------

    async def add_item(
        self,
        space_id: str,
        meeting_id: str,
        *,
        actor_user_id: str,
        actor_username: str,
        entry_ref: Any,
        title: Any,
        excerpt: Any = "",
        question: Any = None,
    ) -> dict[str, Any]:
        await self._spaces.require_member(space_id, actor_user_id, write=True)
        row = await self._meeting(space_id, meeting_id)
        if str(row["status"]) != "open":
            raise SpaceInvalid("会议已结束，不能再添加资料项。")
        ref = _clean(entry_ref, "entryRef", 200)
        clean_title = _clean(title, "title", MAX_NAME)
        clean_excerpt = _clean(excerpt, "excerpt", MAX_EXCERPT, required=False)
        clean_question = (
            _clean(question, "question", MAX_QUESTION, required=False) or None
        )
        count = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM space_meeting_items WHERE meeting_id = ?",
            (meeting_id,),
        )
        if count is not None and int(count["n"]) >= MAX_ITEMS_PER_MEETING:
            raise SpaceInvalid(f"单次会议资料项最多 {MAX_ITEMS_PER_MEETING} 条。")
        now = utc_now()
        item_id = str(_uuid.uuid4())
        await self._db.execute(
            "INSERT INTO space_meeting_items (id, meeting_id, space_id, entry_ref, title, excerpt, question, added_by, added_by_username, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                item_id,
                meeting_id,
                space_id,
                ref,
                clean_title,
                clean_excerpt,
                clean_question,
                actor_user_id,
                actor_username,
                now,
            ),
        )
        item = await self._db.fetch_one(
            "SELECT * FROM space_meeting_items WHERE id = ?", (item_id,)
        )
        assert item is not None
        return self._item_view(dict(item))

    async def remove_item(
        self, space_id: str, meeting_id: str, item_id: str, *, actor_user_id: str
    ) -> None:
        membership = await self._spaces.require_member(space_id, actor_user_id, write=True)
        meeting = await self._meeting(space_id, meeting_id)
        if str(meeting["status"]) != "open":
            raise SpaceInvalid("会议已结束，资料项已固化。")
        item = await self._db.fetch_one(
            "SELECT * FROM space_meeting_items WHERE id = ? AND meeting_id = ?",
            (item_id, meeting_id),
        )
        if item is None:
            raise MeetingNotFound(item_id)
        item = dict(item)
        is_manager = str(membership["role"]) == "manager"
        if str(item["added_by"]) != actor_user_id and not is_manager:
            raise SpaceInvalid("只能移除自己添加的资料项。")
        await self._db.execute(
            "DELETE FROM space_meeting_items WHERE id = ?", (item_id,)
        )

    # -- 结束与结论 -----------------------------------------------------------

    async def close(
        self, space_id: str, meeting_id: str, *, actor_user_id: str
    ) -> dict[str, Any]:
        membership = await self._spaces.require_member(space_id, actor_user_id, write=True)
        row = await self._meeting(space_id, meeting_id)
        if str(row["status"]) == "closed":
            return self._view(row)
        is_manager = str(membership["role"]) == "manager"
        if str(row["created_by"]) != actor_user_id and not is_manager:
            raise SpaceForbidden(space_id)
        now = utc_now()
        await self._db.execute(
            "UPDATE space_meetings SET status = 'closed', closed_at = ? WHERE id = ?",
            (now, meeting_id),
        )
        return self._view(await self._meeting(space_id, meeting_id))

    async def add_outcome(
        self,
        space_id: str,
        meeting_id: str,
        *,
        actor_user_id: str,
        actor_username: str,
        summary: Any,
        entry_ref: Any = None,
    ) -> dict[str, Any]:
        """结束后保存结论与出处（会议 open 时拒绝——「结束后保存」）。"""
        await self._spaces.require_member(space_id, actor_user_id, write=True)
        row = await self._meeting(space_id, meeting_id)
        if str(row["status"]) != "closed":
            raise SpaceInvalid("会议结束后才能保存结论。")
        clean_summary = _clean(summary, "summary", MAX_SUMMARY)
        clean_ref = _clean(entry_ref, "entryRef", 200, required=False) or None
        count = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM space_meeting_outcomes WHERE meeting_id = ?",
            (meeting_id,),
        )
        if count is not None and int(count["n"]) >= MAX_OUTCOMES_PER_MEETING:
            raise SpaceInvalid(f"单次会议结论最多 {MAX_OUTCOMES_PER_MEETING} 条。")
        now = utc_now()
        outcome_id = str(_uuid.uuid4())
        await self._db.execute(
            "INSERT INTO space_meeting_outcomes (id, meeting_id, entry_ref, summary, created_by, created_by_username, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (outcome_id, meeting_id, clean_ref, clean_summary, actor_user_id, actor_username, now),
        )
        return await self.get(space_id, meeting_id, actor_user_id=actor_user_id)
