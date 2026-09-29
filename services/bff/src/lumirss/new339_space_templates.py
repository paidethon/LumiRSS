"""NEW-339 共读模板 —— 把空间的栏目、角色规则和讨论模板保存为**不含
成员与内容**的模板；创建新空间时可先预览再应用。

安全前提（测试断言）：

- 模板行永远不携带成员清单或任何文章/讨论内容——栏目只存名称与顺序，
  角色规则只存开关（requireApproval 等），讨论模板是模板作者显式编写
  的引导文本；
- 从空间生成模板（管理者专属）：快照 sections + role rules；讨论模板
  必须显式提供（绝不从既有讨论内容抄）；
- 预览（preview）零写入；应用 = 创建新空间 + 重建栏目 + 落角色规则
  + 落讨论模板（不含任何成员——新空间只有创建者一人）。
"""

import json
import uuid as _uuid
from typing import Any

from lumirss.space_core import (
    MAX_DESCRIPTION,
    MAX_NAME,
    SpaceInvalid,
    SpaceStore,
    parse_discussion_templates,
)
from lumirss.storage import Database
from lumirss.util import utc_now


class TemplateExists(Exception):
    """同名模板已存在——409 template_exists。"""


class SpaceTemplateNotFound(Exception):
    """模板不存在——404 template_not_found。"""


class SpaceTemplateStore:
    def __init__(self, control_db: Database, spaces: SpaceStore) -> None:
        self._db = control_db
        self._spaces = spaces

    # -- 视图 -----------------------------------------------------------------

    @staticmethod
    def _view(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "name": str(row["name"]),
            "description": str(row["description"]),
            "sourceSpaceId": row["source_space_id"],
            "sections": json.loads(str(row["sections_json"] or "[]")),
            "roleRules": json.loads(str(row["role_rules_json"] or "{}")),
            "discussionTemplates": json.loads(
                str(row["discussion_templates_json"] or "[]")
            ),
            "createdBy": str(row["created_by"]),
            "createdByUsername": str(row["created_by_username"]),
            "createdAt": str(row["created_at"]),
        }

    async def _row(self, template_id: str) -> dict[str, Any]:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT * FROM space_templates WHERE id = ?", (template_id,)
        )
        if row is None:
            raise SpaceTemplateNotFound(template_id)
        return dict(row)

    # -- 生成模板（管理者专属；不含成员与内容） ---------------------------------

    async def create_from_space(
        self,
        space_id: str,
        *,
        actor_user_id: str,
        actor_username: str,
        name: Any,
        description: Any = "",
        discussion_templates: Any = None,
    ) -> dict[str, Any]:
        await self._spaces.require_manager(space_id, actor_user_id, write=True)
        clean_name = _name(name)
        clean_description = _desc(description)
        templates = parse_discussion_templates(discussion_templates)
        space = await self._spaces.row(space_id)
        sections = await self._spaces.list_sections(space_id)
        snapshot_sections = [
            {"name": section["name"], "position": section["position"]}
            for section in sections
        ]
        role_rules = {
            "requireApproval": bool(space["require_approval"]),
        }
        existing = await self._db.fetch_one(
            "SELECT id FROM space_templates WHERE name = ?", (clean_name,)
        )
        if existing is not None:
            raise TemplateExists(clean_name)
        template_id = str(_uuid.uuid4())
        await self._db.execute(
            "INSERT INTO space_templates (id, name, description, source_space_id, sections_json, role_rules_json, discussion_templates_json, created_by, created_by_username, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                template_id,
                clean_name,
                clean_description,
                space_id,
                json.dumps(snapshot_sections, ensure_ascii=False),
                json.dumps(role_rules, ensure_ascii=False),
                json.dumps(templates, ensure_ascii=False),
                actor_user_id,
                actor_username,
                utc_now(),
            ),
        )
        return self._view(await self._row(template_id))

    # -- 列表 / 预览（零写入） -------------------------------------------------

    async def list_templates(self) -> list[dict[str, Any]]:
        """模板对全部成员可见：构造上不含成员与内容（纯结构 + 显式文本）。"""
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT * FROM space_templates ORDER BY created_at DESC, rowid DESC"
        )
        return [self._view(dict(row)) for row in rows]

    async def preview(self, template_id: str, *, actor_user_id: str) -> dict[str, Any]:
        """创建新空间预览（零写入；认证用户即可预览）。"""
        from lumirss.user_scope import require_user_id

        _ = require_user_id()  # 路由层已校验；此处保持显式
        row = await self._row(template_id)
        view = self._view(row)
        view["previewNote"] = (
            "预览零写入；应用后将创建同名栏目的新空间，并落入这些角色规则与讨论模板（不含任何成员与内容）。"
        )
        return view

    # -- 应用（创建新空间） -----------------------------------------------------

    async def create_space_from_template(
        self,
        template_id: str,
        *,
        actor_user_id: str,
        actor_username: str,
        name: Any,
        description: Any = "",
    ) -> dict[str, Any]:
        row = await self._row(template_id)
        template = self._view(row)
        clean_name = _name(name)
        clean_description = _desc(description)
        space = await self._spaces.create(
            owner_user_id=actor_user_id,
            owner_username=actor_username,
            name=clean_name,
            description=clean_description,
            require_approval=bool(template["roleRules"].get("requireApproval", False)),
            discussion_templates=template["discussionTemplates"],
        )
        ordered = sorted(
            template["sections"], key=lambda item: item.get("position", 0)
        )
        for item in ordered:
            section_name = item.get("name")
            if isinstance(section_name, str) and section_name.strip():
                try:
                    await self._spaces.add_section(
                        space["id"], actor_user_id=actor_user_id, name=section_name
                    )
                except SpaceInvalid:
                    continue  # 同名冲突（防御性）：诚实跳过，不中断创建
        return space


def _name(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SpaceInvalid("name 不能为空。")
    clean = value.strip()
    if len(clean) > MAX_NAME:
        raise SpaceInvalid(f"name 最长 {MAX_NAME} 字符。")
    return clean


def _desc(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise SpaceInvalid("description 必须是字符串。")
    clean = value.strip()
    if len(clean) > MAX_DESCRIPTION:
        raise SpaceInvalid(f"description 最长 {MAX_DESCRIPTION} 字符。")
    return clean
