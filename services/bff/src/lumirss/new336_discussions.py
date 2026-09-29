"""NEW-336 讨论标记待答与已解答 —— 发起者把讨论标为问题，选中有用
回复后标记解决；完整讨论永远保留。

不变量：

- 创建讨论即创建问题（question 必填）——「发起者把讨论标为问题」；
- 「有用」与「解决」都是发起者（asked_by）的 set 语义显式动作，管理
  者不越权代替；任何人都不能删除回复——解决只是状态位 + 选中回复
  引用，讨论全文保留。
"""

import uuid as _uuid
from typing import Any

from lumirss.space_core import MAX_NAME, SpaceForbidden, SpaceInvalid, SpaceStore
from lumirss.storage import Database
from lumirss.util import utc_now

MAX_QUESTION = 2000
MAX_BODY = 2000
MAX_REPLIES = 200


class DiscussionNotFound(Exception):
    """讨论不存在（或不属于该空间）——404。"""


class ReplyNotFound(Exception):
    """回复不存在——404。"""


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


class DiscussionStore:
    def __init__(self, control_db: Database, spaces: SpaceStore) -> None:
        self._db = control_db
        self._spaces = spaces

    async def _row(self, space_id: str, discussion_id: str) -> dict[str, Any]:
        row = await self._db.fetch_one(
            "SELECT * FROM space_discussions WHERE id = ? AND space_id = ?",
            (discussion_id, space_id),
        )
        if row is None:
            raise DiscussionNotFound(discussion_id)
        return dict(row)

    async def _replies(self, discussion_id: str) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT * FROM space_discussion_replies WHERE discussion_id = ? ORDER BY created_at ASC, rowid ASC",
            (discussion_id,),
        )
        return [self._reply_view(dict(row)) for row in rows]

    @staticmethod
    def _reply_view(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "discussionId": str(row["discussion_id"]),
            "authorUserId": str(row["author_user_id"]),
            "authorUsername": str(row["author_username"]),
            "body": str(row["body"]),
            "helpful": bool(row["helpful"]),
            "createdAt": str(row["created_at"]),
        }

    async def _view(
        self, row: dict[str, Any], *, with_replies: bool = True
    ) -> dict[str, Any]:
        view = {
            "id": str(row["id"]),
            "spaceId": str(row["space_id"]),
            "entryRef": row["entry_ref"],
            "title": str(row["title"]),
            "question": str(row["question"]),
            "status": str(row["status"]),
            "resolvedReplyId": row["resolved_reply_id"],
            "resolvedAt": row["resolved_at"],
            "askedBy": str(row["asked_by"]),
            "askedByUsername": str(row["asked_by_username"]),
            "createdAt": str(row["created_at"]),
        }
        if with_replies:
            view["replies"] = await self._replies(str(row["id"]))
        return view

    # -- 动作 -----------------------------------------------------------------

    async def ask(
        self,
        space_id: str,
        *,
        actor_user_id: str,
        actor_username: str,
        title: Any,
        question: Any,
        entry_ref: Any = None,
    ) -> dict[str, Any]:
        await self._spaces.require_member(space_id, actor_user_id, write=True)
        clean_title = _clean(title, "title", MAX_NAME)
        clean_question = _clean(question, "question", MAX_QUESTION)
        ref = _clean(entry_ref, "entryRef", 200, required=False) or None
        now = utc_now()
        discussion_id = str(_uuid.uuid4())
        await self._db.execute(
            "INSERT INTO space_discussions (id, space_id, entry_ref, title, question, status, resolved_reply_id, resolved_at, asked_by, asked_by_username, created_at) "
            "VALUES (?, ?, ?, ?, ?, 'open', NULL, NULL, ?, ?, ?)",
            (discussion_id, space_id, ref, clean_title, clean_question, actor_user_id, actor_username, now),
        )
        return await self._view(await self._row(space_id, discussion_id))

    async def get(
        self, space_id: str, discussion_id: str, *, actor_user_id: str
    ) -> dict[str, Any]:
        await self._spaces.require_member(space_id, actor_user_id)
        return await self._view(await self._row(space_id, discussion_id))

    async def list_for_space(
        self, space_id: str, *, actor_user_id: str, status: str | None = None
    ) -> list[dict[str, Any]]:
        await self._spaces.require_member(space_id, actor_user_id)
        if status is not None and status not in ("open", "resolved"):
            raise SpaceInvalid("status 只能是 open / resolved。")
        rows = await self._db.fetch_all(
            "SELECT * FROM space_discussions WHERE space_id = ? ORDER BY created_at DESC, rowid DESC",
            (space_id,),
        )
        views = [await self._view(dict(row), with_replies=False) for row in rows]
        if status is not None:
            views = [view for view in views if view["status"] == status]
        return views

    async def reply(
        self,
        space_id: str,
        discussion_id: str,
        *,
        actor_user_id: str,
        actor_username: str,
        body: Any,
    ) -> dict[str, Any]:
        await self._spaces.require_member(space_id, actor_user_id, write=True)
        await self._row(space_id, discussion_id)
        clean_body = _clean(body, "body", MAX_BODY)
        count = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM space_discussion_replies WHERE discussion_id = ?",
            (discussion_id,),
        )
        if count is not None and int(count["n"]) >= MAX_REPLIES:
            raise SpaceInvalid(f"单个讨论回复最多 {MAX_REPLIES} 条。")
        reply_id = str(_uuid.uuid4())
        await self._db.execute(
            "INSERT INTO space_discussion_replies (id, discussion_id, space_id, entry_ref, author_user_id, author_username, body, helpful, created_at) "
            "SELECT ?, ?, space_id, entry_ref, ?, ?, ?, 0, ? FROM space_discussions WHERE id = ?",
            (reply_id, discussion_id, actor_user_id, actor_username, clean_body, utc_now(), discussion_id),
        )
        return await self._view(await self._row(space_id, discussion_id))

    async def set_helpful(
        self,
        space_id: str,
        discussion_id: str,
        reply_id: str,
        *,
        actor_user_id: str,
        helpful: Any,
    ) -> dict[str, Any]:
        """发起者选中「有用」回复（set 语义；不影响解决状态）。"""
        await self._spaces.require_member(space_id, actor_user_id, write=True)
        row = await self._row(space_id, discussion_id)
        if str(row["asked_by"]) != actor_user_id:
            raise SpaceForbidden(space_id)
        if not isinstance(helpful, bool):
            raise SpaceInvalid("helpful 必须是布尔值。")
        reply = await self._db.fetch_one(
            "SELECT * FROM space_discussion_replies WHERE id = ? AND discussion_id = ?",
            (reply_id, discussion_id),
        )
        if reply is None:
            raise ReplyNotFound(reply_id)
        await self._db.execute(
            "UPDATE space_discussion_replies SET helpful = ? WHERE id = ?",
            (1 if helpful else 0, reply_id),
        )
        return await self._view(await self._row(space_id, discussion_id))

    async def resolve(
        self,
        space_id: str,
        discussion_id: str,
        *,
        actor_user_id: str,
        reply_id: Any,
    ) -> dict[str, Any]:
        """发起者标记解决（必须选中有用回复）；已解决可重新打开
        （replyId=null），完整讨论始终保留。"""
        await self._spaces.require_member(space_id, actor_user_id, write=True)
        row = await self._row(space_id, discussion_id)
        if str(row["asked_by"]) != actor_user_id:
            raise SpaceForbidden(space_id)
        if reply_id is None:
            await self._db.execute(
                "UPDATE space_discussions SET status = 'open', resolved_reply_id = NULL, resolved_at = NULL WHERE id = ?",
                (discussion_id,),
            )
            return await self._view(await self._row(space_id, discussion_id))
        clean_reply = _clean(reply_id, "replyId", 64)
        reply = await self._db.fetch_one(
            "SELECT * FROM space_discussion_replies WHERE id = ? AND discussion_id = ?",
            (clean_reply, discussion_id),
        )
        if reply is None:
            raise ReplyNotFound(clean_reply)
        now = utc_now()
        await self._db.execute(
            "UPDATE space_discussions SET status = 'resolved', resolved_reply_id = ?, resolved_at = ? WHERE id = ?",
            (clean_reply, now, discussion_id),
        )
        return await self._view(await self._row(space_id, discussion_id))
