"""NEW-236 批注回复提醒 —— 明确共享批注上的回复串（控制库）。

隐私前提（硬规则）：私人标注绝不自动进入共享面。线程行存在的唯一
路径是批注所有者的**显式 share 动作**（指定收件成员）；快照
（excerpt/note/entry_ref）在共享时点固化，作为收件人可见的
「原上下文」，不自动跟随后续编辑。收件人可以：

- 查看原上下文与全部回复（查看即清未读）；
- 在串内回复；
- **关闭该串提醒**（dismiss；owner 再次显式 share 才会重开）。

存储：控制库表（跨用户是控制关注点，与 ai_usage 同一先例）；迁移
0146 建表。访问控制：只有 owner_user_id 与 shared_with_user_id 能
读写一个串——任何其他账户 404（不泄露串的存在）。
"""

import uuid as _uuid
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

MAX_BODY = 2000
MAX_REPLIES_PER_THREAD = 200


class ShareThreadNotFound(Exception):
    """线程不存在（或调用者不是成员——统一 404，不泄露存在性）。"""


class ShareThreadForbidden(Exception):
    """调用者无权执行该动作（如收件人以外的 dismiss）。"""


class ShareThreadFull(Exception):
    """串内回复已达上限（200）。"""


class ShareThreadStore:
    def __init__(self, control_db: Database) -> None:
        self._db = control_db

    # -- 内部 --------------------------------------------------------------

    async def _thread_row(self, thread_id: str) -> dict[str, Any]:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT * FROM annotation_share_threads WHERE id = ?", (thread_id,)
        )
        if row is None:
            raise ShareThreadNotFound(thread_id)
        return dict(row)

    @staticmethod
    def _view(row: dict[str, Any], replies: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        view = {
            "id": str(row["id"]),
            "annotationId": str(row["annotation_id"]),
            "entryRef": str(row["entry_ref"]),
            "excerpt": str(row["excerpt"] or ""),
            "note": str(row["note"] or ""),
            "sharedWithUserId": str(row["shared_with_user_id"]),
            "sharedWithUsername": str(row["shared_with_username"]),
            "createdAt": str(row["created_at"]),
            "updatedAt": str(row["updated_at"]),
            "dismissedAt": row["dismissed_at"],
            "unreadForRecipient": int(row["unread_for_recipient"]),
            "replyCount": int(row.get("reply_count") or 0),
        }
        if replies is not None:
            view["replies"] = replies
        return view

    async def _replies(self, thread_id: str) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT id, author_user_id, author_username, body, created_at FROM annotation_share_replies "
            "WHERE thread_id = ? ORDER BY created_at ASC, rowid ASC",
            (thread_id,),
        )
        return [
            {
                "id": str(row["id"]),
                "authorUserId": str(row["author_user_id"]),
                "authorUsername": str(row["author_username"]),
                "body": str(row["body"]),
                "createdAt": str(row["created_at"]),
            }
            for row in rows
        ]

    # -- owner 侧 ----------------------------------------------------------

    async def share(
        self,
        *,
        owner_user_id: str,
        annotation_id: str,
        entry_ref: str,
        excerpt: str,
        note: str,
        recipient_user_id: str,
        recipient_username: str,
    ) -> dict[str, Any]:
        """显式共享（幂等 upsert）：已共享 → 刷新快照并重开提醒
        （dismissed 清空，未读不变——重开是显式动作，不伪造未读）。"""
        await self._db.migrate()
        existing = await self._db.fetch_one(
            "SELECT id FROM annotation_share_threads WHERE annotation_id = ? AND shared_with_user_id = ?",
            (annotation_id, recipient_user_id),
        )
        now = utc_now()
        if existing is not None:
            thread_id = str(existing["id"])
            await self._db.execute(
                "UPDATE annotation_share_threads SET entry_ref = ?, excerpt = ?, note = ?, updated_at = ?, dismissed_at = NULL WHERE id = ?",
                (entry_ref, excerpt, note, now, thread_id),
            )
        else:
            thread_id = str(_uuid.uuid4())
            await self._db.execute(
                "INSERT INTO annotation_share_threads (id, owner_user_id, annotation_id, entry_ref, excerpt, note, shared_with_user_id, shared_with_username, created_at, updated_at, dismissed_at, unread_for_recipient) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, 0)",
                (
                    thread_id,
                    owner_user_id,
                    annotation_id,
                    entry_ref,
                    excerpt,
                    note,
                    recipient_user_id,
                    recipient_username,
                    now,
                    now,
                ),
            )
        row = await self._thread_row(thread_id)
        replies = await self._replies(thread_id)
        return self._view(row, replies)

    async def revoke(self, thread_id: str, owner_user_id: str) -> bool:
        """owner 撤销共享（串与回复一并删除——撤销后共享面不再存在）。"""
        row = await self._thread_row(thread_id)
        if str(row["owner_user_id"]) != owner_user_id:
            raise ShareThreadNotFound(thread_id)
        await self._db.execute(
            "DELETE FROM annotation_share_replies WHERE thread_id = ?", (thread_id,)
        )
        await self._db.execute(
            "DELETE FROM annotation_share_threads WHERE id = ?", (thread_id,)
        )
        return True

    async def list_for_owner(self, owner_user_id: str) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT t.*, (SELECT COUNT(*) FROM annotation_share_replies r WHERE r.thread_id = t.id) AS reply_count "
            "FROM annotation_share_threads t WHERE t.owner_user_id = ? ORDER BY t.updated_at DESC, t.rowid DESC",
            (owner_user_id,),
        )
        return [self._view(dict(row)) for row in rows]

    # -- 共同面 --------------------------------------------------------------

    async def get_thread(
        self, thread_id: str, user_id: str, *, mark_seen: bool = False
    ) -> dict[str, Any]:
        """串详情（上下文快照 + 全部回复）。非成员 → ShareThreadNotFound
        （统一 404，不泄露存在性）。收件人且 mark_seen → 清未读。"""
        row = await self._thread_row(thread_id)
        is_owner = str(row["owner_user_id"]) == user_id
        is_recipient = str(row["shared_with_user_id"]) == user_id
        if not (is_owner or is_recipient):
            raise ShareThreadNotFound(thread_id)
        replies = await self._replies(thread_id)
        if mark_seen and is_recipient and int(row["unread_for_recipient"]) != 0:
            await self._db.execute(
                "UPDATE annotation_share_threads SET unread_for_recipient = 0 WHERE id = ?",
                (thread_id,),
            )
            row["unread_for_recipient"] = 0
        return self._view(row, replies)

    async def add_reply(
        self,
        thread_id: str,
        *,
        author_user_id: str,
        author_username: str,
        body: str,
    ) -> dict[str, Any]:
        row = await self._thread_row(thread_id)
        is_owner = str(row["owner_user_id"]) == author_user_id
        is_recipient = str(row["shared_with_user_id"]) == author_user_id
        if not (is_owner or is_recipient):
            raise ShareThreadNotFound(thread_id)
        clean = str(body or "").strip()
        if not clean:
            raise ValueError("回复内容不能为空。")
        if len(clean) > MAX_BODY:
            raise ValueError(f"回复内容过长（≤{MAX_BODY} 字符）。")
        count = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM annotation_share_replies WHERE thread_id = ?",
            (thread_id,),
        )
        if count is not None and int(count["n"]) >= MAX_REPLIES_PER_THREAD:
            raise ShareThreadFull()
        now = utc_now()
        reply_id = str(_uuid.uuid4())
        await self._db.execute(
            "INSERT INTO annotation_share_replies (id, thread_id, author_user_id, author_username, body, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (reply_id, thread_id, author_user_id, author_username, clean, now),
        )
        unread_bump = 0 if is_recipient else 1
        await self._db.execute(
            "UPDATE annotation_share_threads SET updated_at = ?, unread_for_recipient = unread_for_recipient + ?, dismissed_at = NULL WHERE id = ?",
            (now, unread_bump, thread_id),
        )
        # owner 回复会把串重新顶起（重开提醒）：dismissed 清空即重开。
        row = await self._thread_row(thread_id)
        replies = await self._replies(thread_id)
        return self._view(row, replies)

    # -- 收件人侧 --------------------------------------------------------------

    async def list_for_recipient(
        self, recipient_user_id: str, *, include_dismissed: bool = False
    ) -> list[dict[str, Any]]:
        """收件人的提醒箱：默认只含未关闭串（提醒语义）；历史用
        include_dismissed=true。"""
        await self._db.migrate()
        where = "WHERE t.shared_with_user_id = ?"
        if not include_dismissed:
            where += " AND t.dismissed_at IS NULL"
        rows = await self._db.fetch_all(
            f"SELECT t.*, (SELECT COUNT(*) FROM annotation_share_replies r WHERE r.thread_id = t.id) AS reply_count "
            f"FROM annotation_share_threads t {where} ORDER BY t.updated_at DESC, t.rowid DESC",
            (recipient_user_id,),
        )
        return [self._view(dict(row)) for row in rows]

    async def dismiss(self, thread_id: str, recipient_user_id: str) -> None:
        """收件人关闭该串提醒（只有收件人能关）。非成员 → NotFound（不
        泄露存在性）；owner（非收件人）→ Forbidden。"""
        row = await self._thread_row(thread_id)
        is_owner = str(row["owner_user_id"]) == recipient_user_id
        is_recipient = str(row["shared_with_user_id"]) == recipient_user_id
        if not (is_owner or is_recipient):
            raise ShareThreadNotFound(thread_id)
        if not is_recipient:
            raise ShareThreadForbidden()
        await self._db.execute(
            "UPDATE annotation_share_threads SET dismissed_at = ?, unread_for_recipient = 0 WHERE id = ?",
            (utc_now(), thread_id),
        )
