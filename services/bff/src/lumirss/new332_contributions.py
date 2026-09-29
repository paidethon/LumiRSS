"""NEW-332 共享内容审批队列 —— 空间开启投稿审批后的秩序层。

不变量（测试逐一断言）：

- 开启审批（requireApproval）后，成员投稿先落 pending；pending 只对
  **投稿者本人与管理者**可见，绝不公开给全体成员；
- 管理者批准 / 退回（退回必须写明原因）；投稿者能看到自己的待审与
  退回原因；
- 未开启审批时投稿直接 approved（立即对全体成员可见）——显式投稿
  本身就是共享动作；
- 审批只改变空间内可见性：投稿者是把自己显式提交的内容放进空间，
  私人阅读状态不参与。
"""

import uuid as _uuid
from typing import Any

from lumirss.space_core import MAX_NAME, SpaceInvalid, SpaceStore
from lumirss.storage import Database
from lumirss.util import utc_now

MAX_EXCERPT = 4000
MAX_NOTE = 1000
MAX_REVIEW_NOTE = 1000


class ContributionNotFound(Exception):
    """投稿不存在（或调用者不可见——统一 404）。"""


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


class ContributionStore:
    def __init__(self, control_db: Database, spaces: SpaceStore) -> None:
        self._db = control_db
        self._spaces = spaces

    @staticmethod
    def _view(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "spaceId": str(row["space_id"]),
            "entryRef": str(row["entry_ref"]),
            "title": str(row["title"]),
            "excerpt": str(row["excerpt"]),
            "note": row["note"],
            "sectionId": row["section_id"],
            "status": str(row["status"]),
            "reviewNote": row["review_note"],
            "reviewedBy": row["reviewed_by"],
            "reviewedByUsername": row["reviewed_by_username"],
            "reviewedAt": row["reviewed_at"],
            "submittedBy": str(row["submitted_by"]),
            "submittedByUsername": str(row["submitted_by_username"]),
            "createdAt": str(row["created_at"]),
        }

    async def _row(self, space_id: str, contribution_id: str) -> dict[str, Any]:
        row = await self._db.fetch_one(
            "SELECT * FROM space_contributions WHERE id = ? AND space_id = ?",
            (contribution_id, space_id),
        )
        if row is None:
            raise ContributionNotFound(contribution_id)
        return dict(row)

    async def submit(
        self,
        space_id: str,
        *,
        actor_user_id: str,
        actor_username: str,
        entry_ref: Any,
        title: Any,
        excerpt: Any = "",
        note: Any = None,
        section_id: Any = None,
    ) -> dict[str, Any]:
        await self._spaces.require_member(space_id, actor_user_id, write=True)
        space = await self._spaces.row(space_id)
        ref = _clean(entry_ref, "entryRef", 200)
        clean_title = _clean(title, "title", MAX_NAME)
        clean_excerpt = _clean(excerpt, "excerpt", MAX_EXCERPT, required=False)
        clean_note = _clean(note, "note", MAX_NOTE, required=False) or None
        clean_section = _clean(section_id, "sectionId", 64, required=False) or None
        if clean_section is not None:
            found = await self._db.fetch_one(
                "SELECT id FROM space_sections WHERE id = ? AND space_id = ?",
                (clean_section, space_id),
            )
            if found is None:
                raise SpaceInvalid("栏目不存在。")
        status = "pending" if bool(space["require_approval"]) else "approved"
        contribution_id = str(_uuid.uuid4())
        now = utc_now()
        await self._db.execute(
            "INSERT INTO space_contributions (id, space_id, entry_ref, title, excerpt, note, section_id, status, review_note, reviewed_by, reviewed_by_username, reviewed_at, submitted_by, submitted_by_username, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, ?, ?, ?)",
            (
                contribution_id,
                space_id,
                ref,
                clean_title,
                clean_excerpt,
                clean_note,
                clean_section,
                status,
                actor_user_id,
                actor_username,
                now,
            ),
        )
        return self._view(await self._row(space_id, contribution_id))

    async def list_for_space(
        self, space_id: str, *, actor_user_id: str, scope: str = "visible"
    ) -> list[dict[str, Any]]:
        """成员默认视图 = approved + 自己的全部投稿；管理者额外看到
        全部 pending。scope=mine 只看自己的投稿（含待审/退回原因）。"""
        membership = await self._spaces.require_member(space_id, actor_user_id)
        is_manager = str(membership["role"]) == "manager"
        rows = await self._db.fetch_all(
            "SELECT * FROM space_contributions WHERE space_id = ? ORDER BY created_at DESC, rowid DESC",
            (space_id,),
        )
        items = [self._view(dict(row)) for row in rows]
        if scope == "mine":
            return [item for item in items if item["submittedBy"] == actor_user_id]
        visible: list[dict[str, Any]] = []
        for item in items:
            if item["status"] == "approved" or item["submittedBy"] == actor_user_id or is_manager:
                visible.append(item)
            # 其余 pending：对非管理者不存在（不公开给全体）。
        return visible

    async def review(
        self,
        space_id: str,
        contribution_id: str,
        *,
        actor_user_id: str,
        actor_username: str,
        approve: Any,
        review_note: Any = None,
    ) -> dict[str, Any]:
        await self._spaces.require_manager(space_id, actor_user_id, write=True)
        if not isinstance(approve, bool):
            raise SpaceInvalid("approve 必须是布尔值。")
        row = await self._row(space_id, contribution_id)
        if str(row["status"]) != "pending":
            raise SpaceInvalid("该投稿已审结（只审一次）。")
        note = _clean(review_note, "reviewNote", MAX_REVIEW_NOTE, required=False) or None
        if not approve and not note:
            raise SpaceInvalid("退回必须写明原因（reviewNote）。")
        now = utc_now()
        await self._db.execute(
            "UPDATE space_contributions SET status = ?, review_note = ?, reviewed_by = ?, reviewed_by_username = ?, reviewed_at = ? WHERE id = ?",
            (
                "approved" if approve else "rejected",
                note,
                actor_user_id,
                actor_username,
                now,
                contribution_id,
            ),
        )
        return self._view(await self._row(space_id, contribution_id))

    async def get_visible(
        self, space_id: str, contribution_id: str, *, actor_user_id: str
    ) -> dict[str, Any]:
        """单条投稿：approved 全员可见；pending/rejected 只有投稿者与
        管理者可见（其他成员 → 404，与列表同口径）。"""
        membership = await self._spaces.require_member(space_id, actor_user_id)
        row = await self._row(space_id, contribution_id)
        is_manager = str(membership["role"]) == "manager"
        if (
            str(row["status"]) != "approved"
            and str(row["submitted_by"]) != actor_user_id
            and not is_manager
        ):
            raise ContributionNotFound(contribution_id)
        return self._view(row)
