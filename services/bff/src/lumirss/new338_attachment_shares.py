"""NEW-338 共享附件访问清单 —— 空间管理者查看哪些附件通过空间共享，
逐项撤销授权；不删除所有者的私人文件。

模型与诚实边界：

- 所有者把**自己的**附件以元数据快照（ref/名称/类型/大小）显式共享进
  空间——共享行由所有者本人写入（各写各的）；
- 清单对成员可见（共享面本来就该透明）；撤销 = 管理者或原所有者把
  授权行标记 revoked（保留台账历史，绝不删除）；
- 附件字节永远留在所有者 per-user 库/资产根里，本表面只承载元数据
  台账，绝不跨用户复制内容——撤销授权即空间内不再可用，所有者的
  私人文件毫发无损（本模块根本没有触碰它们的路径）。
"""

import uuid as _uuid
from typing import Any

from lumirss.space_core import SpaceInvalid, SpaceStore
from lumirss.storage import Database
from lumirss.util import utc_now

MAX_NAME = 200
MAX_REF = 200


class AttachmentShareNotFound(Exception):
    """附件共享行不存在（或不属于该空间）——404。"""


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


class AttachmentShareStore:
    def __init__(self, control_db: Database, spaces: SpaceStore) -> None:
        self._db = control_db
        self._spaces = spaces

    @staticmethod
    def _view(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "spaceId": str(row["space_id"]),
            "ownerUserId": str(row["owner_user_id"]),
            "ownerUsername": str(row["owner_username"]),
            "attachmentRef": str(row["attachment_ref"]),
            "name": str(row["name"]),
            "mimeType": str(row["mime_type"]),
            "sizeBytes": row["size_bytes"],
            "createdAt": str(row["created_at"]),
            "revokedAt": row["revoked_at"],
            "revokedBy": row["revoked_by"],
            "revokedByUsername": row["revoked_by_username"],
        }

    async def _row(self, space_id: str, share_id: str) -> dict[str, Any]:
        row = await self._db.fetch_one(
            "SELECT * FROM space_attachment_shares WHERE id = ? AND space_id = ?",
            (share_id, space_id),
        )
        if row is None:
            raise AttachmentShareNotFound(share_id)
        return dict(row)

    # -- 动作 -----------------------------------------------------------------

    async def share(
        self,
        space_id: str,
        *,
        actor_user_id: str,
        actor_username: str,
        attachment_ref: Any,
        name: Any,
        mime_type: Any = "",
        size_bytes: Any = None,
    ) -> dict[str, Any]:
        """所有者把自己的附件元数据显式共享进空间（各写各的行）。"""
        await self._spaces.require_member(space_id, actor_user_id, write=True)
        ref = _clean(attachment_ref, "attachmentRef", MAX_REF)
        clean_name = _clean(name, "name", MAX_NAME)
        clean_mime = _clean(mime_type, "mimeType", 120, required=False)
        clean_size: int | None = None
        if size_bytes is not None:
            if not isinstance(size_bytes, int) or isinstance(size_bytes, bool) or size_bytes < 0:
                raise SpaceInvalid("sizeBytes 必须是非负整数或 null。")
            clean_size = size_bytes
        share_id = str(_uuid.uuid4())
        await self._db.execute(
            "INSERT INTO space_attachment_shares (id, space_id, owner_user_id, owner_username, attachment_ref, name, mime_type, size_bytes, created_at, revoked_at, revoked_by, revoked_by_username) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL)",
            (share_id, space_id, actor_user_id, actor_username, ref, clean_name, clean_mime, clean_size, utc_now()),
        )
        return self._view(await self._row(space_id, share_id))

    async def list_for_space(
        self, space_id: str, *, actor_user_id: str, include_revoked: bool = False
    ) -> list[dict[str, Any]]:
        await self._spaces.require_member(space_id, actor_user_id)
        rows = await self._db.fetch_all(
            "SELECT * FROM space_attachment_shares WHERE space_id = ? ORDER BY created_at DESC, rowid DESC",
            (space_id,),
        )
        views = [self._view(dict(row)) for row in rows]
        if not include_revoked:
            views = [view for view in views if view["revokedAt"] is None]
        return views

    async def revoke(
        self, space_id: str, share_id: str, *, actor_user_id: str, actor_username: str
    ) -> dict[str, Any]:
        """逐项撤销授权（管理者或原所有者；幂等）。台账行保留。"""
        membership = await self._spaces.require_member(space_id, actor_user_id, write=True)
        row = await self._row(space_id, share_id)
        is_manager = str(membership["role"]) == "manager"
        is_owner = str(row["owner_user_id"]) == actor_user_id
        if not (is_manager or is_owner):
            raise SpaceInvalid("只有管理者或附件所有者能撤销该授权。")
        if row["revoked_at"] is not None:
            return self._view(row)
        now = utc_now()
        await self._db.execute(
            "UPDATE space_attachment_shares SET revoked_at = ?, revoked_by = ?, revoked_by_username = ? WHERE id = ?",
            (now, actor_user_id, actor_username, share_id),
        )
        return self._view(await self._row(space_id, share_id))
