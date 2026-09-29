"""NEW-214 标签同义词字典 —— 为个人标签登记别名；录入/搜索时提示规范标签。

- alias 全库唯一（NOCASE）：同一别名绝不指向两个规范标签；
- canonical 必须是**已存在**的标签名（为「个人标签」登记别名）；
- alias 与 canonical 相同没有意义 → 拒绝；
- 解析（resolve）：精确命中别名 → 规范标签；前缀命中 → 候选规范标签
  （上限 8）。若输入本身已是标签名，直接就是规范标签；
- 本字典只影响提示，**绝不改写文章原文**（没有任何写内容路径）。
"""

import sqlite3
from typing import Any

from lumirss.db_tx import transaction
from lumirss.storage import Database
from lumirss.tags import normalize_tag_name
from lumirss.util import utc_now

_MAX_ALIASES = 500
_SUGGESTION_LIMIT = 8


class TagSynonymInvalid(ValueError):
    """别名登记非法（空名/与规范名相同/规范标签不存在），映射 422。"""


class TagSynonymConflict(Exception):
    """别名已被登记（唯一索引），映射 409。"""


class TagSynonymNotFound(Exception):
    """没有这条别名，映射 404。"""


class TagSynonymStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(self, alias: str, canonical: str) -> dict[str, Any]:
        alias_clean = normalize_tag_name(alias)
        canonical_clean = normalize_tag_name(canonical)
        if alias_clean.lower() == canonical_clean.lower():
            raise TagSynonymInvalid("别名与规范标签相同，没有登记意义。")
        await self._db.migrate()
        tag = await self._db.fetch_one(
            "SELECT id FROM tags WHERE name = ? COLLATE NOCASE", (canonical_clean,)
        )
        if tag is None:
            raise TagSynonymInvalid(f"规范标签「{canonical_clean}」不存在。")
        count = await self._db.fetch_one("SELECT COUNT(*) AS n FROM new214_tag_synonyms")
        if count is not None and int(count["n"]) >= _MAX_ALIASES:
            raise TagSynonymInvalid(f"别名数量已达上限（{_MAX_ALIASES}）。")

        def _create(conn: sqlite3.Connection) -> dict[str, Any]:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT id, canonical FROM new214_tag_synonyms WHERE alias = ? COLLATE NOCASE",
                (alias_clean,),
            ).fetchone()
            if existing is not None:
                raise sqlite3.IntegrityError("alias taken")
            cur = conn.execute(
                "INSERT INTO new214_tag_synonyms (alias, canonical, created_at) VALUES (?, ?, ?)",
                (alias_clean, canonical_clean, utc_now()),
            )
            return {
                "id": int(cur.lastrowid),
                "alias": alias_clean,
                "canonical": canonical_clean,
            }

        try:
            return await transaction(self._db, _create)
        except sqlite3.IntegrityError as exc:
            raise TagSynonymConflict(alias_clean) from exc

    async def delete(self, entry_id: int) -> bool:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id FROM new214_tag_synonyms WHERE id = ?", (entry_id,)
        )
        if row is None:
            return False
        await self._db.execute("DELETE FROM new214_tag_synonyms WHERE id = ?", (entry_id,))
        return True

    async def list_entries(self, *, q: str | None = None) -> list[dict[str, Any]]:
        await self._db.migrate()
        if q and q.strip():
            needle = f"%{q.strip()}%"
            rows = await self._db.fetch_all(
                "SELECT id, alias, canonical, created_at FROM new214_tag_synonyms WHERE alias LIKE ? OR canonical LIKE ? ORDER BY id DESC LIMIT 200",
                (needle, needle),
            )
        else:
            rows = await self._db.fetch_all(
                "SELECT id, alias, canonical, created_at FROM new214_tag_synonyms ORDER BY id DESC LIMIT 200"
            )
        return [
            {
                "id": int(r["id"]),
                "alias": str(r["alias"]),
                "canonical": str(r["canonical"]),
                "createdAt": str(r["created_at"]),
            }
            for r in rows
        ]

    async def resolve_input(self, raw_input: str) -> dict[str, Any]:
        """录入/搜索提示：精确别名命中 → 规范标签；前缀 → 候选集。"""
        value = normalize_tag_name(raw_input)
        await self._db.migrate()
        exact = await self._db.fetch_one(
            "SELECT canonical FROM new214_tag_synonyms WHERE alias = ? COLLATE NOCASE",
            (value,),
        )
        if exact is not None:
            return {
                "input": value,
                "exact": True,
                "canonical": str(exact["canonical"]),
                "suggestions": [],
            }
        is_tag = await self._db.fetch_one(
            "SELECT name FROM tags WHERE name = ? COLLATE NOCASE", (value,)
        )
        if is_tag is not None:
            return {
                "input": value,
                "exact": True,
                "canonical": str(is_tag["name"]),
                "suggestions": [],
            }
        like = f"{value}%"
        rows = await self._db.fetch_all(
            "SELECT DISTINCT canonical FROM new214_tag_synonyms WHERE alias LIKE ? COLLATE NOCASE LIMIT ?",
            (like, _SUGGESTION_LIMIT),
        )
        # 前缀提示同时覆盖规范标签名本身（录入时按名字前缀补全）。
        tag_rows = await self._db.fetch_all(
            "SELECT name FROM tags WHERE name LIKE ? COLLATE NOCASE LIMIT ?",
            (like, _SUGGESTION_LIMIT),
        )
        suggestions: list[str] = []
        seen: set[str] = set()

        def _push(name: str) -> bool:
            if name.lower() in seen:
                return False
            seen.add(name.lower())
            suggestions.append(name)
            return len(suggestions) >= _SUGGESTION_LIMIT

        for row in rows:
            if _push(str(row["canonical"])):
                break
        for row in tag_rows:
            if _push(str(row["name"])):
                break
        return {"input": value, "exact": False, "canonical": None, "suggestions": suggestions}
