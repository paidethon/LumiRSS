"""NEW-334 空间成员到期管理 —— 邀请成员时可指定权限到期时间；到期
撤销空间权限而不删除其个人账户（复用邀请 expires_at 的到期语义）。

模型：

- 事实源 = space_members.expires_at（space_core.member_is_active 即时
  判定；到期行不删除——续期即恢复，历史可查）；
- 到期撤销的只是**空间权限**：到期成员访问空间 → 404（与 non-member
  同口径，不泄露存在性）；其个人账户、自己的数据完全不受影响
  （per-user 库天然隔离）；
- 本模块提供显式 sweep（管理者触发）：把已到期但尚未记录的成员写进
  审计台账（space_member_expiry_log），幂等；设置/清除/续期同样入账。
"""

import uuid as _uuid
from typing import Any

from lumirss.space_core import (
    SpaceStore,
    normalize_expiry,
)
from lumirss.storage import Database
from lumirss.util import utc_now

_ACTIONS = {"expiry_set", "expiry_cleared", "expired", "renewed"}


class MemberExpiryStore:
    def __init__(self, control_db: Database, spaces: SpaceStore) -> None:
        self._db = control_db
        self._spaces = spaces

    async def _log(
        self,
        space_id: str,
        *,
        user_id: str,
        username: str,
        action: str,
        actor_user_id: str,
        detail: str,
    ) -> None:
        await self._db.execute(
            "INSERT INTO space_member_expiry_log (id, space_id, user_id, username, action, actor_user_id, detail, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(_uuid.uuid4()),
                space_id,
                user_id,
                username,
                action,
                actor_user_id,
                detail,
                utc_now(),
            ),
        )

    async def set_expiry(
        self,
        space_id: str,
        member_id: str,
        *,
        actor_user_id: str,
        expires_at: Any,
    ) -> dict[str, Any]:
        """管理者设定/清除成员到期。之前的值参与动作归类（续期 vs 设定）。"""
        target = await self._spaces.member_row_by_id(space_id, member_id)
        previous = target.get("expires_at")
        normalized = normalize_expiry(expires_at)
        view = await self._spaces.set_member_expiry(
            space_id,
            actor_user_id=actor_user_id,
            member_id=member_id,
            expires_at=normalized,
        )
        now = utc_now()
        if normalized is None:
            action = "expiry_cleared"
        elif previous and str(previous) < normalized:
            action = "renewed"
        else:
            action = "expiry_set"
        await self._log(
            space_id,
            user_id=str(target["user_id"]),
            username=str(target["username"]),
            action=action,
            actor_user_id=actor_user_id,
            detail=f"previous={previous or 'null'} expiresAt={normalized or 'null'} now={now}",
        )
        return view

    async def sweep(self, space_id: str, *, actor_user_id: str) -> dict[str, Any]:
        """显式到期清扫（管理者）：为每个已到期成员补一条 'expired'
        台账（幂等——已有台账的跳过）。权限判定不依赖 sweep：读取时
        即时判定；sweep 只是审计显式化。"""
        await self._spaces.require_manager(space_id, actor_user_id, write=True)
        now = utc_now()
        rows = await self._db.fetch_all(
            "SELECT * FROM space_members WHERE space_id = ? AND role = 'member' "
            "AND revoked_at IS NULL AND expires_at IS NOT NULL AND expires_at <= ?",
            (space_id, now),
        )
        expired: list[dict[str, Any]] = []
        for row in rows:
            row = dict(row)
            seen = await self._db.fetch_one(
                "SELECT id FROM space_member_expiry_log WHERE space_id = ? AND user_id = ? AND action = 'expired'",
                (space_id, str(row["user_id"])),
            )
            if seen is not None:
                continue
            await self._log(
                space_id,
                user_id=str(row["user_id"]),
                username=str(row["username"]),
                action="expired",
                actor_user_id=actor_user_id,
                detail=f"expiresAt={row['expires_at']} now={now}",
            )
            expired.append(
                {
                    "userId": str(row["user_id"]),
                    "username": str(row["username"]),
                    "expiresAt": row["expires_at"],
                }
            )
        return {"expired": expired}

    async def list_log(
        self, space_id: str, *, actor_user_id: str
    ) -> list[dict[str, Any]]:
        await self._spaces.require_member(space_id, actor_user_id)
        rows = await self._db.fetch_all(
            "SELECT * FROM space_member_expiry_log WHERE space_id = ? ORDER BY created_at DESC, rowid DESC",
            (space_id,),
        )
        return [
            {
                "id": str(row["id"]),
                "spaceId": str(row["space_id"]),
                "userId": str(row["user_id"]),
                "username": str(row["username"]),
                "action": str(row["action"]),
                "actorUserId": str(row["actor_user_id"]),
                "detail": str(row["detail"]),
                "createdAt": str(row["created_at"]),
            }
            for row in rows
        ]
