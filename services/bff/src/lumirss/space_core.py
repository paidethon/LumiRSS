"""NEW-331..340 共读空间基底 —— 控制库上的最小显式共享面（space_core）。

隐私前提（硬规则）：空间内容一律**显式共享**——管理者显式添加成员、
成员显式投稿/共享条目；私人阅读状态绝不自动进入空间视图。跨用户行
放控制库（NEW-236 批注共享串 / NEW-229 控制面同一先例：跨用户是控制
关注点）。

访问模型（全组统一，测试逐一断言）：

- 非成员（含从未被添加、被移除、**已到期**的账户）访问任何空间面 →
  ``SpaceNotFound``（统一 404，不泄露空间存在性）；
- 成员做管理者专属动作 → ``SpaceForbidden``（403；成员身份已知，
  只是越权）；
- 归档空间（NEW-340）的一切写动作 → ``SpaceArchived``（409 只读）；
  读取不受影响。

成员有效性 = revoked_at IS NULL 且（role='manager' 或 expires_at 为
空或未到期）。到期语义与邀请一致（expires_at 即失效），到期只撤销
空间权限，绝不触碰成员的个人账户。
"""

import json
import uuid as _uuid
from datetime import UTC, datetime
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

MAX_NAME = 120
MAX_DESCRIPTION = 2000
MAX_SECTION_NAME = 60
MAX_SECTIONS_PER_SPACE = 50
MAX_DISCUSSION_TEMPLATES = 20
MAX_DISCUSSION_TEMPLATE_LEN = 500


class SpaceInvalid(ValueError):
    """空间载荷非法（名称/描述/栏目/模板）——422 invalid_space。"""


class SpaceNotFound(Exception):
    """空间不存在，或调用者不是有效成员（统一 404，不泄露存在性）。"""


class SpaceForbidden(Exception):
    """调用者是成员但无权执行该动作（管理者专属）——403。"""


class SpaceArchived(Exception):
    """空间已归档（只读）——409 space_archived。"""


class MemberExists(Exception):
    """该用户已是空间成员——409 space_member_exists。"""


class MemberNotFound(Exception):
    """空间成员行不存在——404 space_member_not_found。"""


def normalize_expiry(value: Any) -> str | None:
    """到期时间规范化：ISO 字符串 → 统一 UTC ISO；null = 清除到期。

    与邀请 expires_at 同语义（到期即失效）；解析失败 → SpaceInvalid。
    """
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise SpaceInvalid("expiresAt 必须是 ISO 时间戳或 null。")
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise SpaceInvalid("expiresAt 必须是 ISO 时间戳或 null。") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat(timespec="seconds")


def _clean_text(value: Any, field: str, limit: int, *, required: bool = True) -> str:
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


def parse_discussion_templates(value: Any) -> list[str]:
    """讨论模板文本列表（NEW-339 创建/应用时校验；纯作者显式文本）。"""
    if value is None:
        return []
    if not isinstance(value, list):
        raise SpaceInvalid("discussionTemplates 必须是字符串数组。")
    templates: list[str] = []
    for item in value:
        clean = _clean_text(item, "讨论模板", MAX_DISCUSSION_TEMPLATE_LEN, required=False)
        if clean:
            templates.append(clean)
    if len(templates) > MAX_DISCUSSION_TEMPLATES:
        raise SpaceInvalid(f"讨论模板最多 {MAX_DISCUSSION_TEMPLATES} 条。")
    return templates


def member_is_active(row: dict[str, Any], now: str | None = None) -> bool:
    """成员行当前是否有效（未撤销、未到期；管理者行永不过期）。"""
    if row.get("revoked_at") is not None:
        return False
    if str(row.get("role")) == "manager":
        return True
    expires_at = row.get("expires_at")
    if not expires_at:
        return True
    return str(expires_at) > (now or utc_now())


class SpaceStore:
    """空间基底：空间 / 显式成员 / 栏目（NEW-331..340 共用）。"""

    def __init__(self, control_db: Database) -> None:
        self._db = control_db

    # -- 行级助手 ------------------------------------------------------------

    async def row(self, space_id: str) -> dict[str, Any]:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT * FROM space_spaces WHERE id = ?", (space_id,)
        )
        if row is None:
            raise SpaceNotFound(space_id)
        return dict(row)

    async def membership(self, space_id: str, user_id: str) -> dict[str, Any] | None:
        """调用者在空间内的成员行（含已撤销/已到期——调用方决定语义）。"""
        row = await self._db.fetch_one(
            "SELECT * FROM space_members WHERE space_id = ? AND user_id = ?",
            (space_id, user_id),
        )
        return dict(row) if row is not None else None

    async def member_row_by_id(self, space_id: str, member_id: str) -> dict[str, Any]:
        row = await self._db.fetch_one(
            "SELECT * FROM space_members WHERE space_id = ? AND id = ?",
            (space_id, member_id),
        )
        if row is None:
            raise MemberNotFound(member_id)
        return dict(row)

    # -- 统一守卫 ------------------------------------------------------------

    async def require_member(
        self, space_id: str, user_id: str, *, write: bool = False
    ) -> dict[str, Any]:
        """有效成员守卫：非成员/已到期 → SpaceNotFound（404 统一，
        不泄露存在性）；归档空间写动作 → SpaceArchived（只读）。"""
        membership = await self.membership(space_id, user_id)
        if membership is None or not member_is_active(membership):
            raise SpaceNotFound(space_id)
        if write:
            space = await self.row(space_id)
            if space["archived_at"] is not None:
                raise SpaceArchived(space_id)
        return membership

    async def require_manager(
        self, space_id: str, user_id: str, *, write: bool = False
    ) -> dict[str, Any]:
        membership = await self.require_member(space_id, user_id, write=write)
        if str(membership["role"]) != "manager":
            raise SpaceForbidden(space_id)
        return membership

    # -- 视图 -----------------------------------------------------------------

    @staticmethod
    def member_view(row: dict[str, Any], now: str | None = None) -> dict[str, Any]:
        expired = (
            row.get("expires_at") is not None
            and str(row["role"]) != "manager"
            and str(row["expires_at"]) <= (now or utc_now())
        )
        return {
            "id": str(row["id"]),
            "spaceId": str(row["space_id"]),
            "userId": str(row["user_id"]),
            "username": str(row["username"]),
            "role": str(row["role"]),
            "expiresAt": row["expires_at"],
            "revokedAt": row["revoked_at"],
            "active": member_is_active(row, now),
            "expired": expired and row.get("revoked_at") is None,
            "createdAt": str(row["created_at"]),
        }

    def space_view(
        self, row: dict[str, Any], *, my_role: str | None = None
    ) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "name": str(row["name"]),
            "description": str(row["description"]),
            "ownerUserId": str(row["owner_user_id"]),
            "requireApproval": bool(row["require_approval"]),
            "discussionTemplates": json.loads(
                str(row["discussion_templates_json"] or "[]")
            ),
            "archivedAt": row["archived_at"],
            "createdAt": str(row["created_at"]),
            "updatedAt": str(row["updated_at"]),
            "myRole": my_role,
        }

    # -- 空间 -----------------------------------------------------------------

    async def create(
        self,
        *,
        owner_user_id: str,
        owner_username: str,
        name: Any,
        description: Any = "",
        require_approval: Any = False,
        discussion_templates: Any = None,
    ) -> dict[str, Any]:
        clean_name = _clean_text(name, "name", MAX_NAME)
        clean_description = _clean_text(
            description, "description", MAX_DESCRIPTION, required=False
        )
        templates = parse_discussion_templates(discussion_templates)
        now = utc_now()
        space_id = str(_uuid.uuid4())
        await self._db.execute(
            "INSERT INTO space_spaces (id, name, description, owner_user_id, require_approval, discussion_templates_json, archived_at, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?)",
            (
                space_id,
                clean_name,
                clean_description,
                owner_user_id,
                1 if require_approval else 0,
                json.dumps(templates, ensure_ascii=False),
                now,
                now,
            ),
        )
        await self._db.execute(
            "INSERT INTO space_members (id, space_id, user_id, username, role, expires_at, revoked_at, created_at) "
            "VALUES (?, ?, ?, ?, 'manager', NULL, NULL, ?)",
            (str(_uuid.uuid4()), space_id, owner_user_id, owner_username, now),
        )
        row = await self.row(space_id)
        return self.space_view(row, my_role="manager")

    async def list_for_user(self, user_id: str) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT s.*, m.role AS my_role FROM space_spaces s "
            "JOIN space_members m ON m.space_id = s.id AND m.user_id = ? "
            "WHERE m.revoked_at IS NULL ORDER BY s.created_at DESC, s.rowid DESC",
            (user_id,),
        )
        return [
            self.space_view(dict(row), my_role=str(row["my_role"])) for row in rows
        ]

    async def detail(self, space_id: str, user_id: str) -> dict[str, Any]:
        """空间详情（含成员与栏目）；仅有效成员可见。"""
        membership = await self.require_member(space_id, user_id)
        space = await self.row(space_id)
        view = self.space_view(space, my_role=str(membership["role"]))
        view["members"] = await self.list_members(space_id)
        view["sections"] = await self.list_sections(space_id)
        return view

    # -- 成员 -----------------------------------------------------------------

    async def list_members(self, space_id: str) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT * FROM space_members WHERE space_id = ? "
            "ORDER BY CASE role WHEN 'manager' THEN 0 ELSE 1 END, created_at ASC, rowid ASC",
            (space_id,),
        )
        return [self.member_view(dict(row)) for row in rows]

    async def add_member(
        self,
        space_id: str,
        *,
        actor_user_id: str,
        user_id: str,
        username: str,
    ) -> dict[str, Any]:
        """管理者显式添加成员（NEW-334 可随后指定 expires_at）。"""
        await self.require_manager(space_id, actor_user_id, write=True)
        existing = await self.membership(space_id, user_id)
        if existing is not None:
            raise MemberExists(username)
        now = utc_now()
        member_id = str(_uuid.uuid4())
        await self._db.execute(
            "INSERT INTO space_members (id, space_id, user_id, username, role, expires_at, revoked_at, created_at) "
            "VALUES (?, ?, ?, ?, 'member', NULL, NULL, ?)",
            (member_id, space_id, user_id, username, now),
        )
        return self.member_view(await self.member_row_by_id(space_id, member_id))

    async def remove_member(
        self, space_id: str, *, actor_user_id: str, member_id: str
    ) -> None:
        """管理者移除成员；成员也可自行退出（自己是那行）。到期撤销
        只影响空间权限，绝不触碰成员的个人账户。"""
        target = await self.member_row_by_id(space_id, member_id)
        if str(target["role"]) == "manager":
            raise SpaceForbidden(space_id)  # 管理者行不可移除（空间锚点）
        if str(target["user_id"]) != actor_user_id:
            await self.require_manager(space_id, actor_user_id, write=True)
        else:
            await self.require_member(space_id, actor_user_id, write=True)
        await self._db.execute(
            "UPDATE space_members SET revoked_at = ? WHERE id = ?",
            (utc_now(), member_id),
        )

    async def set_member_expiry(
        self, space_id: str, *, actor_user_id: str, member_id: str, expires_at: Any
    ) -> dict[str, Any]:
        """NEW-334：管理者设定/清除成员权限到期（normalized ISO / null）。"""
        await self.require_manager(space_id, actor_user_id, write=True)
        target = await self.member_row_by_id(space_id, member_id)
        if str(target["role"]) == "manager":
            raise SpaceForbidden(space_id)
        normalized = normalize_expiry(expires_at)
        await self._db.execute(
            "UPDATE space_members SET expires_at = ? WHERE id = ?",
            (normalized, member_id),
        )
        return self.member_view(await self.member_row_by_id(space_id, member_id))

    # -- 栏目 -----------------------------------------------------------------

    async def list_sections(self, space_id: str) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT * FROM space_sections WHERE space_id = ? ORDER BY position ASC, rowid ASC",
            (space_id,),
        )
        return [
            {
                "id": str(row["id"]),
                "spaceId": str(row["space_id"]),
                "name": str(row["name"]),
                "position": int(row["position"]),
                "createdAt": str(row["created_at"]),
            }
            for row in rows
        ]

    async def add_section(
        self, space_id: str, *, actor_user_id: str, name: Any
    ) -> dict[str, Any]:
        await self.require_manager(space_id, actor_user_id, write=True)
        clean = _clean_text(name, "栏目名", MAX_SECTION_NAME)
        count = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM space_sections WHERE space_id = ?", (space_id,)
        )
        if count is not None and int(count["n"]) >= MAX_SECTIONS_PER_SPACE:
            raise SpaceInvalid(f"栏目最多 {MAX_SECTIONS_PER_SPACE} 个。")
        existing = await self._db.fetch_one(
            "SELECT id FROM space_sections WHERE space_id = ? AND name = ?",
            (space_id, clean),
        )
        if existing is not None:
            raise SpaceInvalid("同名栏目已存在。")
        now = utc_now()
        section_id = str(_uuid.uuid4())
        await self._db.execute(
            "INSERT INTO space_sections (id, space_id, name, position, created_at) VALUES (?, ?, ?, ?, ?)",
            (section_id, space_id, clean, int(count["n"]) if count else 0, now),
        )
        row = await self._db.fetch_one(
            "SELECT * FROM space_sections WHERE id = ?", (section_id,)
        )
        assert row is not None
        return {
            "id": str(row["id"]),
            "spaceId": str(row["space_id"]),
            "name": str(row["name"]),
            "position": int(row["position"]),
            "createdAt": str(row["created_at"]),
        }

    # -- 设置（NEW-332 用） ----------------------------------------------------

    async def set_require_approval(
        self, space_id: str, *, actor_user_id: str, require_approval: Any
    ) -> dict[str, Any]:
        await self.require_manager(space_id, actor_user_id, write=True)
        if not isinstance(require_approval, bool):
            raise SpaceInvalid("requireApproval 必须是布尔值。")
        now = utc_now()
        await self._db.execute(
            "UPDATE space_spaces SET require_approval = ?, updated_at = ? WHERE id = ?",
            (1 if require_approval else 0, now, space_id),
        )
        return self.space_view(await self.row(space_id))

    async def set_discussion_templates(
        self, space_id: str, *, actor_user_id: str, templates: Any
    ) -> dict[str, Any]:
        await self.require_manager(space_id, actor_user_id, write=True)
        clean = parse_discussion_templates(templates)
        await self._db.execute(
            "UPDATE space_spaces SET discussion_templates_json = ?, updated_at = ? WHERE id = ?",
            (json.dumps(clean, ensure_ascii=False), utc_now(), space_id),
        )
        return self.space_view(await self.row(space_id))
