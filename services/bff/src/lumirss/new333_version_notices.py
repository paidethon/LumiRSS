"""NEW-333 共读内容版本通知 —— 共享文章版本改变时通知相关讨论参与者。

流程（全部显式，无后台爬虫、无网络依赖）：

1. 成员在自己的阅读器里发现某共享条目有新版本，**显式报告**到空间
   （entryRef + versionLabel + 摘要）；
2. 系统解析「相关讨论参与者」= 本空间内对该 entry_ref 有过显式讨论
   行为的账户（NEW-336 提问者 + 回复者），**排除报告人本人**，逐人
   建待核对提醒（acks 行）；
3. 参与者查看提醒并标记「已重新核对」（ack，幂等）。

诚实边界：新版本正文不跨用户库复制（per-user 分库）；通知只携带
ref / 版本标签 / 报告人摘要——接收方在自己的库里重新核对引用。
"""

import uuid as _uuid
from typing import Any

from lumirss.space_core import SpaceInvalid, SpaceStore
from lumirss.storage import Database
from lumirss.util import utc_now

MAX_SUMMARY = 1000
MAX_LABEL = 120


class VersionNoticeNotFound(Exception):
    """版本通知不存在（或调用者不在该空间）——404。"""


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


class VersionNoticeStore:
    def __init__(self, control_db: Database, spaces: SpaceStore) -> None:
        self._db = control_db
        self._spaces = spaces

    # -- 视图 -----------------------------------------------------------------

    @staticmethod
    def _view(
        row: dict[str, Any], acks: list[dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        view = {
            "id": str(row["id"]),
            "spaceId": str(row["space_id"]),
            "entryRef": str(row["entry_ref"]),
            "versionLabel": str(row["version_label"]),
            "summary": str(row["summary"]),
            "reportedBy": str(row["reported_by"]),
            "reportedByUsername": str(row["reported_by_username"]),
            "createdAt": str(row["created_at"]),
        }
        if acks is not None:
            view["acks"] = acks
        return view

    async def _notice(self, space_id: str, notice_id: str) -> dict[str, Any]:
        row = await self._db.fetch_one(
            "SELECT * FROM space_version_notices WHERE id = ? AND space_id = ?",
            (notice_id, space_id),
        )
        if row is None:
            raise VersionNoticeNotFound(notice_id)
        return dict(row)

    async def _acks(self, notice_id: str) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT * FROM space_version_notice_acks WHERE notice_id = ? ORDER BY created_at ASC, rowid ASC",
            (notice_id,),
        )
        return [
            {
                "noticeId": str(row["notice_id"]),
                "userId": str(row["user_id"]),
                "acknowledgedAt": row["acknowledged_at"],
                "createdAt": str(row["created_at"]),
            }
            for row in rows
        ]

    # -- 参与者解析 -----------------------------------------------------------

    async def _discussion_participants(self, space_id: str, entry_ref: str) -> set[str]:
        """本空间内对该条目有过显式讨论行为的账户（提问者 + 回复者）。

        来源只有 NEW-336 的显式讨论行——绝不从私人阅读状态推断。"""
        participants: set[str] = set()
        ask_rows = await self._db.fetch_all(
            "SELECT asked_by FROM space_discussions WHERE space_id = ? AND entry_ref = ?",
            (space_id, entry_ref),
        )
        for row in ask_rows:
            participants.add(str(row["asked_by"]))
        reply_rows = await self._db.fetch_all(
            "SELECT DISTINCT author_user_id FROM space_discussion_replies WHERE space_id = ? AND entry_ref = ?",
            (space_id, entry_ref),
        )
        for row in reply_rows:
            participants.add(str(row["author_user_id"]))
        return participants

    # -- 动作 -----------------------------------------------------------------

    async def report(
        self,
        space_id: str,
        *,
        actor_user_id: str,
        actor_username: str,
        entry_ref: Any,
        version_label: Any,
        summary: Any = "",
    ) -> dict[str, Any]:
        """显式报告新版本；为本空间的讨论参与者逐人建待核对提醒。"""
        await self._spaces.require_member(space_id, actor_user_id, write=True)
        ref = _clean(entry_ref, "entryRef", 200)
        label = _clean(version_label, "versionLabel", MAX_LABEL)
        clean_summary = _clean(summary, "summary", MAX_SUMMARY, required=False)
        now = utc_now()
        notice_id = str(_uuid.uuid4())
        await self._db.execute(
            "INSERT INTO space_version_notices (id, space_id, entry_ref, version_label, summary, reported_by, reported_by_username, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (notice_id, space_id, ref, label, clean_summary, actor_user_id, actor_username, now),
        )
        # 参与者逐人建提醒行（排除报告人本人——报告人自己无「待核对」）。
        participants = await self._discussion_participants(space_id, ref)
        participants.discard(actor_user_id)
        for user_id in sorted(participants):
            await self._db.execute(
                "INSERT OR IGNORE INTO space_version_notice_acks (notice_id, space_id, entry_ref, user_id, acknowledged_at, created_at) "
                "VALUES (?, ?, ?, ?, NULL, ?)",
                (notice_id, space_id, ref, user_id, now),
            )
        return self._view(await self._notice(space_id, notice_id), acks=await self._acks(notice_id))

    async def get(
        self, space_id: str, notice_id: str, *, actor_user_id: str
    ) -> dict[str, Any]:
        await self._spaces.require_member(space_id, actor_user_id)
        return self._view(
            await self._notice(space_id, notice_id),
            acks=await self._acks(notice_id),
        )

    async def list_for_space(
        self, space_id: str, *, actor_user_id: str, scope: str = "all"
    ) -> list[dict[str, Any]]:
        """scope=pending：我的待核对（提醒语义，含未 ack 的我的行）；
        scope=all：全空间通知（成员面）。"""
        await self._spaces.require_member(space_id, actor_user_id)
        if scope == "pending":
            rows = await self._db.fetch_all(
                "SELECT n.* FROM space_version_notices n "
                "JOIN space_version_notice_acks a ON a.notice_id = n.id AND a.user_id = ? "
                "WHERE n.space_id = ? AND a.acknowledged_at IS NULL "
                "ORDER BY n.created_at DESC, n.rowid DESC",
                (actor_user_id, space_id),
            )
            views = []
            for row in rows:
                item = self._view(dict(row))
                mine = await self._db.fetch_one(
                    "SELECT acknowledged_at FROM space_version_notice_acks WHERE notice_id = ? AND user_id = ?",
                    (str(row["id"]), actor_user_id),
                )
                item["myAcknowledgedAt"] = dict(mine)["acknowledged_at"] if mine else None
                views.append(item)
            return views
        rows = await self._db.fetch_all(
            "SELECT * FROM space_version_notices WHERE space_id = ? ORDER BY created_at DESC, rowid DESC",
            (space_id,),
        )
        return [self._view(dict(row)) for row in rows]

    async def acknowledge(
        self, space_id: str, notice_id: str, *, actor_user_id: str
    ) -> dict[str, Any]:
        """参与者标记「已重新核对」（幂等 set 语义）。只有被提醒人能 ack。"""
        await self._spaces.require_member(space_id, actor_user_id, write=True)
        await self._notice(space_id, notice_id)
        existing = await self._db.fetch_one(
            "SELECT acknowledged_at FROM space_version_notice_acks WHERE notice_id = ? AND user_id = ?",
            (notice_id, actor_user_id),
        )
        if existing is None:
            raise VersionNoticeNotFound(notice_id)  # 未被提醒 → 不存在该待办
        if dict(existing)["acknowledged_at"] is None:
            await self._db.execute(
                "UPDATE space_version_notice_acks SET acknowledged_at = ? WHERE notice_id = ? AND user_id = ?",
                (utc_now(), notice_id, actor_user_id),
            )
        view = self._view(await self._notice(space_id, notice_id), acks=await self._acks(notice_id))
        return view
