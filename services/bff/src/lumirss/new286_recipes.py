"""NEW-286 简报栏目配方 —— 栏目顺序 + 字数预算 + 选择规则的可复用配方。

sections_json = [{key,label,rule,budget,feedUrl?}]：
- rule ∈ starred(已标星) / recent(最新 N 条) / feed(指定来源)；
- budget = 该栏目字数预算（摘录字符计，40..5000；生成器按预算截取
  条数≈预算/摘录均长——确定性折算，绝不假装精确排版）；
- 顺序即栏目顺序；下一期生成 (284) 直接吃配方，建稿后仍可微调。

per-user：配方在 per-user 库，A 的配方对 B 不可见。
"""

import json
import uuid as _uuid
from typing import Any

from lumirss.new281_briefings import BriefingInvalid
from lumirss.storage import Database
from lumirss.util import utc_now

RULES = ("starred", "recent", "feed")
_MAX_SECTIONS = 12
_MAX_NAME = 100
_BUDGET_BOUNDS = (40, 5000)


class RecipeNotFound(Exception):
    """配方不存在（映射 404）。"""


def clean_recipe_sections(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list) or not raw:
        raise BriefingInvalid("sections 必须是非空数组。")
    if len(raw) > _MAX_SECTIONS:
        raise BriefingInvalid(f"栏目不能超过 {_MAX_SECTIONS} 个。")
    seen: set[str] = set()
    sections: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise BriefingInvalid("sections 元素必须是对象。")
        key = entry.get("key")
        label = entry.get("label")
        rule = entry.get("rule", "recent")
        budget = entry.get("budget", 400)
        if not isinstance(key, str) or not key.strip():
            raise BriefingInvalid("栏目 key 不能为空。")
        key = key.strip()
        if len(key) > 40 or any(ch in key for ch in ' \t"\'<>&/'):
            raise BriefingInvalid("栏目 key 非法（≤40 字符且不含空白与 <>&\"'/）。")
        if key in seen:
            raise BriefingInvalid(f"栏目 key 重复：{key}。")
        seen.add(key)
        if not isinstance(label, str) or not label.strip():
            raise BriefingInvalid(f"栏目 {key} 的 label 不能为空。")
        if len(label.strip()) > 60:
            raise BriefingInvalid(f"栏目 {key} 的 label 过长。")
        if rule not in RULES:
            raise BriefingInvalid(f"栏目 {key} 的 rule 必须是 {'、'.join(RULES)} 之一。")
        if rule == "feed":
            feed_url = entry.get("feedUrl")
            if not isinstance(feed_url, str) or not feed_url.strip():
                raise BriefingInvalid(f"栏目 {key} 规则为 feed 时 feedUrl 必填。")
        if isinstance(budget, bool) or not isinstance(budget, int):
            raise BriefingInvalid(f"栏目 {key} 的 budget 必须是整数。")
        if not _BUDGET_BOUNDS[0] <= budget <= _BUDGET_BOUNDS[1]:
            raise BriefingInvalid(
                f"栏目 {key} 的 budget 必须在 {_BUDGET_BOUNDS[0]}.."
                f"{_BUDGET_BOUNDS[1]} 之间（摘录字符）。"
            )
        sections.append(
            {
                "key": key,
                "label": label.strip(),
                "rule": rule,
                "budget": budget,
                "feedUrl": str(entry.get("feedUrl") or "") if rule == "feed" else "",
            }
        )
    return sections


def recipe_to_issue_sections(sections: list[dict[str, Any]]) -> list[dict[str, str]]:
    """配方栏目 → 期次栏目定义（284 生成 + apply-recipe 共用口径）。"""
    return [{"key": s["key"], "label": s["label"]} for s in sections]


class RecipeStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(self, *, name: Any, sections: Any) -> dict[str, Any]:
        if not isinstance(name, str) or not name.strip():
            raise BriefingInvalid("name 不能为空。")
        clean_name = name.strip()
        if len(clean_name) > _MAX_NAME:
            raise BriefingInvalid(f"name 不能超过 {_MAX_NAME} 字符。")
        clean_secs = clean_recipe_sections(sections)
        await self._db.migrate()
        recipe_id = str(_uuid.uuid4())
        now = utc_now()
        await self._db.execute(
            "INSERT INTO briefing_recipes (id, name, sections_json,"
            " created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (
                recipe_id,
                clean_name,
                json.dumps(clean_secs, ensure_ascii=False),
                now,
                now,
            ),
        )
        return await self.get(recipe_id)

    async def get(self, recipe_id: str) -> dict[str, Any]:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, name, sections_json, created_at, updated_at"
            " FROM briefing_recipes WHERE id = ?",
            (recipe_id,),
        )
        if row is None:
            raise RecipeNotFound("配方不存在。")
        return self._row(row)

    async def list_recipes(self) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, name, sections_json, created_at, updated_at"
            " FROM briefing_recipes ORDER BY updated_at DESC"
        )
        return [self._row(row) for row in rows]

    async def update(
        self, recipe_id: str, *, name: Any = None, sections: Any = None
    ) -> dict[str, Any]:
        await self.get(recipe_id)  # 404 语义
        now = utc_now()
        if name is not None:
            if not isinstance(name, str) or not name.strip():
                raise BriefingInvalid("name 不能为空。")
            clean_name = name.strip()
            if len(clean_name) > _MAX_NAME:
                raise BriefingInvalid(f"name 不能超过 {_MAX_NAME} 字符。")
            await self._db.execute(
                "UPDATE briefing_recipes SET name = ?, updated_at = ? WHERE id = ?",
                (clean_name, now, recipe_id),
            )
        if sections is not None:
            clean_secs = clean_recipe_sections(sections)
            await self._db.execute(
                "UPDATE briefing_recipes SET sections_json = ?, updated_at = ?"
                " WHERE id = ?",
                (json.dumps(clean_secs, ensure_ascii=False), now, recipe_id),
            )
        return await self.get(recipe_id)

    async def delete(self, recipe_id: str) -> bool:
        await self.get(recipe_id)
        await self._db.execute(
            "DELETE FROM briefing_recipes WHERE id = ?", (recipe_id,)
        )
        return True

    def _row(self, row: Any) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "name": str(row["name"]),
            "sections": json.loads(str(row["sections_json"] or "[]")),
            "createdAt": str(row["created_at"]),
            "updatedAt": str(row["updated_at"]),
        }
