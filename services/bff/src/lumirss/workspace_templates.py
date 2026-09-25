"""F083 工作区模板 —— 保存 / 列表 / 删除 / 从模板创建。

模板 config 只携带非机密配置（name/description 等工作区设置），
绝不包含条目内容或凭据；example items 以 ref 引用进新工作区
（不复制内容；失效 ref 诚实跳过）。重复创建模板名 → TemplateExists
（409）；同名模板可反复创建工作区（生成两个独立工作区是文档化语义）。

N117 结构承载（includeStructure）：config 可附 ``structure`` 快照——
组顺序（N101 group_order）+ 分节大纲（N113 标题/序，无成员）+ 看板
状态列（N112 固定枚举回显）+ 收集规则条件快照（N118，仅条件/上限/
开关，不含 addedCount 与任何条目）。应用时只恢复「空壳结构」：分节
建空分节、组序直接写入 group_order_json（组在成员加入后自然显形）、
收集规则按条件重建（addedCount 归零）；条目内容绝不复制。

本文件直接写站点 2 处（模板 INSERT / DELETE）；应用结构时经由
WorkspaceSectionStore / WorkspaceCollectRuleStore 的既有写站点。
"""

import json
import uuid as _uuid
from typing import Any

from lumirss.itemref import parse_item_ref
from lumirss.storage import Database
from lumirss.util import utc_now
from lumirss.workspace_board import BOARD_STATUSES

_MAX_TEMPLATES = 200
_MAX_STRUCTURE_SECTIONS = 100
_MAX_STRUCTURE_RULES = 20


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

    async def save_as_template(
        self,
        workspace_id: str,
        name: str,
        *,
        include_structure: bool = False,
    ) -> dict[str, Any]:
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
        if include_structure:
            config["structure"] = await self._capture_structure(workspace_id)
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
        include_structure: bool = False,
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
        structure = (
            template["config"].get("structure")
            if isinstance(template["config"], dict)
            else None
        )
        structure_restored: dict[str, Any] | None = None
        if include_structure and isinstance(structure, dict):
            structure_restored = await self._apply_structure(
                workspace.id, structure
            )
        return {
            "workspace": workspace,
            "addedExampleRefs": added,
            "skippedExampleRefs": skipped,
            "structure": structure_restored,
        }

    # -- N117 结构快照 / 恢复 -------------------------------------------------

    async def _capture_structure(self, workspace_id: str) -> dict[str, Any]:
        """结构快照：组顺序 + 分节大纲 + 看板状态列 + 收集规则条件。

        刻意只存「形」不存「实」：无 item_ref、无条目内容、无凭据；
        收集规则只存条件/上限/开关（addedCount 不进模板）。"""
        from lumirss.workspace_collect_rules import WorkspaceCollectRuleStore
        from lumirss.workspace_sections import WorkspaceSectionStore

        group_order = await self._workspaces._stored_group_order(workspace_id)  # noqa: SLF001 — 同域协作
        sections = await WorkspaceSectionStore(
            self._db, self._workspaces
        ).list_sections(workspace_id)
        rules = await WorkspaceCollectRuleStore(
            self._db, self._workspaces
        ).list_rules(workspace_id)
        return {
            "groupOrder": [str(name) for name in group_order],
            "sections": [
                {"title": section["title"], "sortIndex": section["sortIndex"]}
                for section in sections[:_MAX_STRUCTURE_SECTIONS]
            ],
            "boardColumns": list(BOARD_STATUSES),
            "collectRules": [
                {
                    "feedUrl": rule["feedUrl"],
                    "tag": rule["tag"],
                    "keyword": rule["keyword"],
                    "maxItems": rule["maxItems"],
                    "enabled": rule["enabled"],
                }
                for rule in rules[:_MAX_STRUCTURE_RULES]
            ],
        }

    async def _apply_structure(
        self, workspace_id: str, structure: dict[str, Any]
    ) -> dict[str, Any]:
        """把模板结构恢复为「空壳」（绝不复制任何条目内容）：

        - 分节 → 逐个建空分节（成员列表为空；非法标题诚实跳过）；
        - 组顺序 → 直接写 group_order_json（组是呈现层派生标签，成员
          加入同名组后自然显形；不经 set_group_order 的「组必须已有
          成员」校验——空壳正是本特性的语义）；
        - 收集规则 → 按条件重建（addedCount 归零；非法条件诚实跳过）；
        - 看板状态列 → 固定五状态枚举（N112），无需落库——快照回显
          供模板自描述，应用侧无需写入。"""
        from lumirss.workspace_collect_rules import WorkspaceCollectRuleStore
        from lumirss.workspace_sections import WorkspaceSectionStore

        section_store = WorkspaceSectionStore(self._db, self._workspaces)
        sections_created = 0
        raw_sections = structure.get("sections")
        if isinstance(raw_sections, list):
            for section in raw_sections[:_MAX_STRUCTURE_SECTIONS]:
                if not isinstance(section, dict):
                    continue
                title = section.get("title")
                if not isinstance(title, str):
                    continue
                try:
                    await section_store.create_section(workspace_id, title)
                    sections_created += 1
                except Exception:  # noqa: BLE001 — 非法分节诚实跳过
                    continue

        group_order: list[str] = []
        raw_groups = structure.get("groupOrder")
        if isinstance(raw_groups, list):
            for name in raw_groups:
                if isinstance(name, str) and name.strip() and name not in group_order:
                    group_order.append(name.strip())
                if len(group_order) >= 100:
                    break
        if group_order:
            await self._db.execute(
                "UPDATE workspaces SET group_order_json = ? WHERE id = ?",
                (json.dumps(group_order, ensure_ascii=False), workspace_id),
            )

        rule_store = WorkspaceCollectRuleStore(self._db, self._workspaces)
        rules_created = 0
        raw_rules = structure.get("collectRules")
        if isinstance(raw_rules, list):
            for rule in raw_rules[:_MAX_STRUCTURE_RULES]:
                if not isinstance(rule, dict):
                    continue
                try:
                    await rule_store.create_rule(
                        workspace_id,
                        feed_url=rule.get("feedUrl"),
                        tag=rule.get("tag"),
                        keyword=rule.get("keyword"),
                        max_items=rule.get("maxItems", 100),
                        enabled=bool(rule.get("enabled", True)),
                    )
                    rules_created += 1
                except Exception:  # noqa: BLE001 — 非法条件诚实跳过
                    continue
        return {
            "sectionsCreated": sections_created,
            "groupOrderRestored": len(group_order),
            "collectRulesCreated": rules_created,
            "boardColumns": list(BOARD_STATUSES),
        }
