"""N199 自定义多步快捷操作 —— 具名 2-3 步 SAFE 动作序列（定义存储）。

本模块只存「定义」与校验。执行永远在 Web 端逐步调用各动作的
NORMAL 端点（每步都过它原本的鉴权/确认路径，无服务端旁路）；服务
端能保证的是：步骤词表是 SAFE 白名单、序列长度 2-3、params 是对象。

SAFE 白名单（client 侧 runner 一一对应；只收不需要正文上下文的
导航/队列类动作）：
- add_to_queue      params: {entryRef}        加入阅读队列
- open_reader       params: {}                打开阅读器
- open_section      params: {section}         跳转分区（home/bookmarks/workspaces/…）
- open_search       params: {query}           打开搜索页并填入关键词
写动作（add_to_queue）在 client runner 里仍走它原本的确认/防抖
路径；服务端拒绝任何白名单之外的动作定义。
"""

import json
import uuid as _uuid
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

MAX_NAME = 100
MAX_ACTIONS_PER_USER = 50
MIN_STEPS = 2
MAX_STEPS = 3

# SAFE 动作词表（与模块 docstring 一一对应；新增需同步 client runner）。
SAFE_ACTIONS: dict[str, set[str]] = {
    "add_to_queue": {"entryRef"},
    "open_reader": set(),
    "open_section": {"section"},
    "open_search": {"query"},
}


class QuickActionInvalid(ValueError):
    """动作定义非法（名字/步骤数/白名单外动作/params 形状），映射 422。"""


def validate_steps(steps: Any) -> list[dict[str, Any]]:
    """校验 stepsJson：2-3 步、动作在白名单内、params 键 ⊆ 允许集。"""
    if not isinstance(steps, list):
        raise QuickActionInvalid("steps 必须是数组。")
    if not MIN_STEPS <= len(steps) <= MAX_STEPS:
        raise QuickActionInvalid(f"步骤数量必须是 {MIN_STEPS}-{MAX_STEPS} 步。")
    cleaned: list[dict[str, Any]] = []
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            raise QuickActionInvalid(f"第 {index + 1} 步必须是对象。")
        action = step.get("action")
        if action not in SAFE_ACTIONS:
            raise QuickActionInvalid(f"第 {index + 1} 步的动作「{action}」不在 SAFE 白名单内。")
        params = step.get("params", {})
        if params is None:
            params = {}
        if not isinstance(params, dict):
            raise QuickActionInvalid(f"第 {index + 1} 步的 params 必须是对象。")
        allowed = SAFE_ACTIONS[str(action)]
        unknown = set(params) - allowed
        if unknown:
            raise QuickActionInvalid(
                f"第 {index + 1} 步的 params 含不允许的键：{', '.join(sorted(map(str, unknown)))}。"
            )
        clean_params = {str(k): params[k] for k in allowed if k in params}
        cleaned.append({"action": str(action), "params": clean_params})
    return cleaned


def _row_to_action(row: Any) -> dict[str, Any]:
    try:
        steps = json.loads(str(row["steps_json"]))
    except (json.JSONDecodeError, TypeError):
        steps = []
    if not isinstance(steps, list):
        steps = []
    return {
        "id": str(row["id"]),
        "name": str(row["name"]),
        "steps": steps,
        "createdAt": str(row["created_at"]),
        "updatedAt": str(row["updated_at"]),
    }


class QuickActionStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(self, *, name: str, steps: list[dict[str, Any]]) -> dict[str, Any]:
        clean_name = str(name or "").strip()
        if not clean_name:
            raise QuickActionInvalid("名称不能为空。")
        if len(clean_name) > MAX_NAME:
            raise QuickActionInvalid(f"名称过长（≤{MAX_NAME} 字符）。")
        clean_steps = validate_steps(steps)
        await self._db.migrate()
        count_row = await self._db.fetch_one("SELECT COUNT(*) AS n FROM quick_actions")
        if count_row is not None and int(count_row["n"]) >= MAX_ACTIONS_PER_USER:
            raise QuickActionInvalid(f"最多 {MAX_ACTIONS_PER_USER} 个快捷操作。")
        action_id = str(_uuid.uuid4())
        now = utc_now()
        await self._db.execute(
            "INSERT INTO quick_actions (id, name, steps_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (action_id, clean_name, json.dumps(clean_steps, ensure_ascii=False, separators=(",", ":")), now, now),
        )
        return {
            "id": action_id,
            "name": clean_name,
            "steps": clean_steps,
            "createdAt": now,
            "updatedAt": now,
        }

    async def list_actions(self) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, name, steps_json, created_at, updated_at FROM quick_actions ORDER BY created_at ASC, id ASC"
        )
        return [_row_to_action(row) for row in rows]

    async def get(self, action_id: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, name, steps_json, created_at, updated_at FROM quick_actions WHERE id = ?",
            (action_id,),
        )
        return _row_to_action(row) if row is not None else None

    async def delete(self, action_id: str) -> bool:
        await self._db.migrate()
        changed = await self._db.execute("DELETE FROM quick_actions WHERE id = ?", (action_id,))
        return bool(changed)
