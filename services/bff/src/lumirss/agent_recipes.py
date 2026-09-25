"""N170 Agent 任务配方 —— 可复用的任务模板（save / list / run）。

- 配方 = {name, input, toolWhitelist, scope}：name 唯一（≤100 字），
  input 是运行时作为首条用户消息发送的文本，toolWhitelist 必须 ⊆
  工具注册表白名单（unknown → 422 拒绝；绝不支持「注册表之外」的
  提权），scope 复用 F094 范围结构（validate_scope）。
- 运行 = 用配方创建新会话：scope 落成会话 scope_json，whitelist 落成
  会话 toolPolicy.allowedTools —— 执行期的服务端 evaluate_policy
  拒绝越权工具（非 UI 隐藏），然后发送首条消息并启动回合。
- 预览（preview before run）：运行前返回将创建的会话设置与首条消息
  概要，零写入。

纯存储 + 校验模块：SQL 单行内联（repo 约定）。
"""

import json
import uuid as _uuid
from typing import Any

from lumirss.agent_session import validate_scope
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_INPUT_CHARS = 4000
_MAX_WHITELIST_TOOLS = 50


class RecipeInvalid(ValueError):
    """配方非法（名称/输入/白名单/范围），映射 422。"""


class RecipeNotFound(Exception):
    """配方不存在，映射 404。"""


class RecipeNameConflict(Exception):
    """配方重名，映射 409。"""


def validate_recipe(
    *, name: Any, input_text: Any, tool_whitelist: Any, scope: Any
) -> dict[str, Any]:
    """Pure validation → clean recipe fields (route + tests share it)."""
    clean_name = str(name or "").strip()
    if not clean_name or len(clean_name) > 100:
        raise RecipeInvalid("配方名称必须是非空且不超过 100 字。")
    clean_input = str(input_text or "").strip()
    if not clean_input:
        raise RecipeInvalid("配方输入不能为空。")
    if len(clean_input) > _MAX_INPUT_CHARS:
        raise RecipeInvalid(f"配方输入过长（≤{_MAX_INPUT_CHARS} 字符）。")
    if not isinstance(tool_whitelist, list) or not tool_whitelist:
        raise RecipeInvalid("toolWhitelist 必须是非空工具名列表。")
    cleaned: list[str] = []
    for tool in tool_whitelist:
        if not isinstance(tool, str) or not tool.strip():
            raise RecipeInvalid("toolWhitelist 必须是字符串列表。")
        tool_name = tool.strip()
        if tool_name not in cleaned:
            cleaned.append(tool_name)
    if len(cleaned) > _MAX_WHITELIST_TOOLS:
        raise RecipeInvalid(f"toolWhitelist 过长（≤{_MAX_WHITELIST_TOOLS} 个工具）。")
    try:
        clean_scope = validate_scope(scope)
    except Exception as exc:
        raise RecipeInvalid(f"scope 非法：{exc}") from exc
    return {
        "name": clean_name,
        "input": clean_input,
        "toolWhitelist": cleaned,
        "scope": clean_scope,
    }


class AgentRecipeStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create_recipe(
        self, *, name: str, input_text: str, tool_whitelist: list[str], scope: Any
    ) -> dict[str, Any]:
        await self._db.migrate()
        existing = await self._db.fetch_one(
            "SELECT id FROM agent_recipes WHERE name = ?", (name,)
        )
        if existing is not None:
            raise RecipeNameConflict(f"配方名称已存在：{name}")
        recipe_id = str(_uuid.uuid4())
        now = utc_now()
        await self._db.execute(
            "INSERT INTO agent_recipes (id, name, input, tool_whitelist_json, scope_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                recipe_id,
                name,
                input_text,
                json.dumps(tool_whitelist, ensure_ascii=False),
                json.dumps(scope, ensure_ascii=False) if scope else None,
                now,
                now,
            ),
        )
        return await self.get_recipe(recipe_id)

    async def list_recipes(self, limit: int = 50) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, name, input, tool_whitelist_json, scope_json, created_at, updated_at FROM agent_recipes ORDER BY created_at DESC LIMIT ?",
            (max(1, min(limit, 200)),),
        )
        return [self._row_to_recipe(row) for row in rows]

    async def get_recipe(self, recipe_id: str) -> dict[str, Any]:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, name, input, tool_whitelist_json, scope_json, created_at, updated_at FROM agent_recipes WHERE id = ?",
            (recipe_id,),
        )
        if row is None:
            raise RecipeNotFound("配方不存在。")
        return self._row_to_recipe(row)

    async def delete_recipe(self, recipe_id: str) -> bool:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id FROM agent_recipes WHERE id = ?", (recipe_id,)
        )
        if row is None:
            return False
        await self._db.execute("DELETE FROM agent_recipes WHERE id = ?", (recipe_id,))
        return True

    @staticmethod
    def _row_to_recipe(row: Any) -> dict[str, Any]:
        def _load(raw: Any, fallback: Any) -> Any:
            if not raw:
                return fallback
            try:
                return json.loads(str(raw))
            except json.JSONDecodeError:
                return fallback

        return {
            "id": str(row["id"]),
            "name": str(row["name"]),
            "input": str(row["input"]),
            "toolWhitelist": _load(row["tool_whitelist_json"], []),
            "scope": _load(row["scope_json"], None),
            "createdAt": str(row["created_at"]),
            "updatedAt": str(row["updated_at"]),
        }
