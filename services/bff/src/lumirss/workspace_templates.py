"""F083 工作区模板 —— 保存 / 列表 / 删除 / 从模板创建。

模板 config 只携带非机密配置（name/description 等工作区设置），
绝不包含条目内容或凭据；example items 以 ref 引用进新工作区
（不复制内容；失效 ref 诚实跳过）。重复创建模板名 → TemplateExists
（409）；同名模板可反复创建工作区（生成两个独立工作区是文档化语义）。

本文件直接写站点 2 处（模板 INSERT / DELETE）。
"""

import json
import uuid as _uuid
from typing import Any

from lumirss.itemref import parse_item_ref
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_TEMPLATES = 200


class TemplateInvalid(ValueError):
    """模板载荷非法（名称长度/示例引用数量），映射 422。"""


class TemplateExists(Exception):
    """同名模板已存在，映射 409。"""


class TemplateNotFound(Exception):
    """模板不存在，映射 404。"""


def _template_config(summary: Any) -> dict[str, Any]:
    """工作区 → 非机密配置快照（刻意不含条目、不含凭据）。"""
    return {
        "description": getattr(summary, "description", "") or "",
    }


class WorkspaceTemplateStore:
    def __init__(self, db: Database, workspace_store: Any) -> None:
        self._db = db
        self._workspaces = workspace_store

    async def save_as_template(self, workspace_id: str, name: str) -> dict[str, Any]:
        clean = str(name or "").strip()
        if not clean or len(clean) > 50:
            raise TemplateInvalid("模板名必须为 1–50 个字符。")
        summary = await self._workspaces.get_workspace(workspace_id)
        if summary is None:
            raise TemplateInvalid("工作区不存在。")
        await self._db.migrate()
        existing = await self._db.fetch_one(
            "SELECT id FROM workspace_templates WHERE name = ?", (clean,)
        )
        if existing is not None:
            raise TemplateExists(clean)
        count_row = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM workspace_templates"
        )
        if count_row is not None and int(count_row["n"]) >= _MAX_TEMPLATES:
            raise TemplateInvalid(f"模板数量已达上限（{_MAX_TEMPLATES}）。")
        template_id = str(_uuid.uuid4())
        config = _template_config(summary)
        await self._db.execute(
            "INSERT INTO workspace_templates (id, name, config_json, created_at) VALUES (?, ?, ?, ?)",
            (template_id, clean, json.dumps(config, ensure_ascii=False), utc_now()),
        )
        return {
            "id": template_id,
            "name": clean,
            "config": config,
            "createdAt": utc_now(),
        }

    async def list_templates(self) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, name, config_json, created_at FROM workspace_templates ORDER BY created_at DESC, id ASC"
        )
        result = []
        for row in rows:
            try:
                config = json.loads(str(row["config_json"] or "{}"))
            except json.JSONDecodeError:
                config = {}
            result.append(
                {
                    "id": str(row["id"]),
                    "name": str(row["name"]),
                    "config": config if isinstance(config, dict) else {},
                    "createdAt": str(row["created_at"]),
                }
            )
        return result

    async def get_template(self, template_id: str) -> dict[str, Any] | None:
        for template in await self.list_templates():
            if template["id"] == template_id:
                return template
        return None

    async def delete_template(self, template_id: str) -> bool:
        await self._db.migrate()

        def _tx(conn: Any) -> int:
            cursor = conn.execute(
                "DELETE FROM workspace_templates WHERE id = ?", (template_id,)
            )
            return cursor.rowcount

        from lumirss.db_tx import transaction as _transaction

        return bool(await _transaction(self._db, _tx))

    async def create_from_template(
        self,
        *,
        template_id: str,
        name: str,
        include_example_items: bool,
        example_refs: list[str],
    ) -> dict[str, Any]:
        template = await self.get_template(template_id)
        if template is None:
            raise TemplateNotFound(template_id)
        if len(example_refs) > 5:
            raise TemplateInvalid("示例条目最多 5 个。")
        clean_description = str(template["config"].get("description") or "")
        workspace = await self._workspaces.create_workspace(name, clean_description)
        added: list[str] = []
        skipped: list[str] = []
        if include_example_items:
            for ref in example_refs:
                try:
                    parse_item_ref(ref)
                except ValueError:
                    skipped.append(ref)
                    continue
                try:
                    await self._workspaces.add_item(workspace.id, ref)
                    added.append(ref)
                except Exception:  # noqa: BLE001 — 失效 ref 诚实跳过
                    skipped.append(ref)
        return {
            "workspace": workspace,
            "addedExampleRefs": added,
            "skippedExampleRefs": skipped,
        }
