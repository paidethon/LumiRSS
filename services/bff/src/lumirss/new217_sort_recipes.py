"""NEW-217 集合排序配方 —— 为指定集合保存多字段排序 + 固定例外。

- 配方只作用于其所属集合（apply 只写 workspace_items.position），其他
  列表不受影响；
- 字段词表（全部是 Lumi 本地投影可查的键，无上游网络）：
  * title   —— rss 引用查 search_entries.title / library 引用查
               search_library.title（统一小写比较）；
  * source  —— rss 的 feed_title（小写）；非 rss 为空串；
  * added_at —— workspace_items.added_at（ISO 文本字典序即时间序）；
- 固定例外（exceptions）：这些 ref 保持**绝对原位**（position 值不变），
  其余成员按配方排入剩下的槽位——确定性、可预览；
- preview 零写入返回完整新序；apply 单事务写全部 position 并 bump
  工作区 revision（P15 并发语义与既有 reorder 一致）；
- explain：人可读的排序规则说明（分享时随配方一起给出）。
"""

import json
import sqlite3
import uuid
from typing import Any

from lumirss.db_tx import transaction
from lumirss.itemref import parse_item_ref
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_RECIPES_PER_WS = 20
_MAX_FIELDS = 4
_MAX_EXCEPTIONS = 50
_MAX_NAME = 100
_WS_CAPACITY = 5000
_CHUNK = 400

_FIELD_KEYS = ("title", "source", "added_at")
_FIELD_LABELS = {"title": "标题", "source": "来源", "added_at": "加入时间"}
_DIRS = ("asc", "desc")


class SortRecipeInvalid(ValueError):
    """配方载荷非法（名字/字段词表/例外引用），映射 422。"""


class SortRecipeNotFound(Exception):
    """配方不存在（或不属于该集合），映射 404。"""


def _clean_fields(raw: list[dict[str, str]]) -> list[dict[str, str]]:
    if not 1 <= len(raw) <= _MAX_FIELDS:
        raise SortRecipeInvalid(f"排序字段数量必须是 1-{_MAX_FIELDS}。")
    fields: list[dict[str, str]] = []
    for item in raw:
        key = str(item.get("key") or "")
        direction = str(item.get("dir") or "")
        if key not in _FIELD_KEYS:
            raise SortRecipeInvalid(f"不支持的排序字段：{key}（允许：{'、'.join(_FIELD_KEYS)}）。")
        if direction not in _DIRS:
            raise SortRecipeInvalid(f"不支持的排序方向：{direction}。")
        fields.append({"key": key, "dir": direction})
    return fields


def _clean_exceptions(raw: list[str]) -> list[str]:
    cleaned: list[str] = []
    for ref in raw:
        try:
            formatted = parse_item_ref(ref).format()
        except ValueError as exc:
            raise SortRecipeInvalid(f"固定例外的引用非法：{ref}") from exc
        if formatted not in cleaned:
            cleaned.append(formatted)
    if len(cleaned) > _MAX_EXCEPTIONS:
        raise SortRecipeInvalid(f"固定例外最多 {_MAX_EXCEPTIONS} 条。")
    return cleaned


def explain_recipe(fields: list[dict[str, str]], exceptions: int) -> str:
    parts = [
        f"{'、'.join(f'按{_FIELD_LABELS[f['key']]}' + ('升序' if f['dir'] == 'asc' else '降序') for f in fields)}"
    ]
    text = f"{parts[0]}排序"
    if exceptions:
        text += f"；{exceptions} 条固定例外保持原位"
    return text + "。"


class SortRecipeStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self, workspace_id: str, name: str, fields: list[dict[str, str]], exceptions: list[str]
    ) -> dict[str, Any]:
        clean_name = name.strip()
        if not clean_name or len(clean_name) > _MAX_NAME:
            raise SortRecipeInvalid(f"配方名必须是 1-{_MAX_NAME} 个字符。")
        clean_fields = _clean_fields(fields)
        clean_exceptions = _clean_exceptions(exceptions)
        await self._db.migrate()
        ws = await self._db.fetch_one("SELECT id FROM workspaces WHERE id = ?", (workspace_id,))
        if ws is None:
            raise SortRecipeInvalid(f"集合不存在：{workspace_id}。")
        count = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM new217_sort_recipes WHERE workspace_id = ?",
            (workspace_id,),
        )
        if count is not None and int(count["n"]) >= _MAX_RECIPES_PER_WS:
            raise SortRecipeInvalid(f"该集合的配方数量已达上限（{_MAX_RECIPES_PER_WS}）。")
        recipe_id = str(uuid.uuid4())
        await self._db.execute(
            "INSERT INTO new217_sort_recipes (id, workspace_id, name, fields_json, exceptions_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (
                recipe_id,
                workspace_id,
                clean_name,
                json.dumps(clean_fields, ensure_ascii=False),
                json.dumps(clean_exceptions, ensure_ascii=False),
                utc_now(),
            ),
        )
        return self._recipe_row(
            recipe_id, workspace_id, clean_name, clean_fields, clean_exceptions, utc_now()
        )

    def _recipe_row(
        self,
        recipe_id: str,
        workspace_id: str,
        name: str,
        fields: list[dict[str, str]],
        exceptions: list[str],
        created_at: str,
    ) -> dict[str, Any]:
        return {
            "id": recipe_id,
            "workspaceId": workspace_id,
            "name": name,
            "fields": fields,
            "exceptions": exceptions,
            "createdAt": created_at,
            "explain": explain_recipe(fields, len(exceptions)),
        }

    async def list_recipes(self, workspace_id: str) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, workspace_id, name, fields_json, exceptions_json, created_at FROM new217_sort_recipes WHERE workspace_id = ? ORDER BY created_at DESC",
            (workspace_id,),
        )
        items: list[dict[str, Any]] = []
        for row in rows:
            try:
                fields = json.loads(str(row["fields_json"]))
                exceptions = json.loads(str(row["exceptions_json"]))
            except ValueError:
                fields, exceptions = [], []
            items.append(
                self._recipe_row(
                    str(row["id"]),
                    str(row["workspace_id"]),
                    str(row["name"]),
                    fields if isinstance(fields, list) else [],
                    exceptions if isinstance(exceptions, list) else [],
                    str(row["created_at"]),
                )
            )
        return items

    async def _recipe(self, workspace_id: str, recipe_id: str) -> dict[str, Any]:
        items = await self.list_recipes(workspace_id)
        for item in items:
            if item["id"] == recipe_id:
                return item
        raise SortRecipeNotFound(recipe_id)

    def _title_source_maps(
        self, conn: sqlite3.Connection, refs: list[str]
    ) -> tuple[dict[str, str], dict[str, str]]:
        """分块 IN 查询两份本地投影：rss → search_entries（注意投影的
        entry_ref 是裸 entryRef，条目前要去掉 ``rss:``），library →
        search_library（ref 即全量 ItemRef）。"""
        titles: dict[str, str] = {}
        sources: dict[str, str] = {}
        rss_refs = [r[len("rss:") :] for r in refs if r.startswith("rss:")]
        lib_refs = [r for r in refs if r.startswith("library:")]
        for start in range(0, len(rss_refs), _CHUNK):
            chunk = rss_refs[start : start + _CHUNK]
            placeholders = ",".join("?" * len(chunk))
            for row in conn.execute(
                f"SELECT entry_ref, title, feed_title FROM search_entries WHERE entry_ref IN ({placeholders})",
                (*chunk,),
            ).fetchall():
                titles[f"rss:{row['entry_ref']}"] = str(row["title"] or "")
                sources[f"rss:{row['entry_ref']}"] = str(row["feed_title"] or "")
        for start in range(0, len(lib_refs), _CHUNK):
            chunk = lib_refs[start : start + _CHUNK]
            placeholders = ",".join("?" * len(chunk))
            for row in conn.execute(
                f"SELECT ref, title FROM search_library WHERE ref IN ({placeholders})",
                (*chunk,),
            ).fetchall():
                titles[str(row["ref"])] = str(row["title"] or "")
        return titles, sources

    def _compute_order(
        self,
        members: list[dict[str, Any]],
        fields: list[dict[str, str]],
        exceptions: list[str],
        titles: dict[str, str],
        sources: dict[str, str],
    ) -> list[dict[str, Any]]:
        """确定性新序：固定例外保持绝对原位（position 值不变），其余成员
        按配方多字段排入剩下的槽位（槽位升序 = 剩余空位顺序）。"""
        exception_set = set(exceptions)
        fixed_members = [m for m in members if m["ref"] in exception_set]
        movable = [m for m in members if m["ref"] not in exception_set]
        desc_flags = [f["dir"] == "desc" for f in fields]

        def sort_values(member: dict[str, Any]) -> list[str]:
            ref = str(member["ref"])
            values: list[str] = []
            for field in fields:
                if field["key"] == "title":
                    values.append(titles.get(ref, "").lower())
                elif field["key"] == "source":
                    values.append(sources.get(ref, "").lower())
                else:
                    values.append(str(member["added_at"] or ""))
            return values

        movable.sort(
            key=lambda m: tuple(
                _invert(v) if desc else v
                for v, desc in zip(sort_values(m), desc_flags, strict=True)
            )
        )
        fixed_slots = {int(m["position"]): m for m in fixed_members}
        movable_iter = iter(movable)
        movable_next = next(movable_iter, None)
        order: list[dict[str, Any]] = []
        for slot in sorted(int(m["position"]) for m in members):
            fixed_member = fixed_slots.get(slot)
            if fixed_member is not None:
                order.append({"ref": str(fixed_member["ref"]), "position": slot, "fixed": True})
            elif movable_next is not None:
                order.append({"ref": str(movable_next["ref"]), "position": slot, "fixed": False})
                movable_next = next(movable_iter, None)
        return order

    async def preview(self, workspace_id: str, recipe_id: str) -> dict[str, Any]:
        """零写入：返回配方计算出的完整新序（固定例外如实标记）。"""
        await self._db.migrate()
        recipe = await self._recipe(workspace_id, recipe_id)
        rows = await self._db.fetch_all(
            "SELECT item_ref, position, added_at FROM workspace_items WHERE workspace_id = ? ORDER BY position ASC LIMIT ?",
            (workspace_id, _WS_CAPACITY),
        )
        members = [
            {"ref": str(r["item_ref"]), "position": int(r["position"]), "added_at": str(r["added_at"] or "")}
            for r in rows
        ]
        titles, sources = await transaction(
            self._db,
            lambda conn: self._title_source_maps(conn, [m["ref"] for m in members]),
        )
        ordering = self._compute_order(members, recipe["fields"], recipe["exceptions"], titles, sources)
        return {
            "workspaceId": workspace_id,
            "recipeId": recipe_id,
            "explain": recipe["explain"],
            "ordering": ordering,
            "memberCount": len(members),
        }

    async def apply(self, workspace_id: str, recipe_id: str) -> dict[str, Any]:
        preview = await self.preview(workspace_id, recipe_id)

        def _apply(conn: sqlite3.Connection) -> dict[str, Any]:
            conn.execute("BEGIN IMMEDIATE")
            moved = 0
            for entry in preview["ordering"]:
                if entry["fixed"]:
                    continue
                cur = conn.execute(
                    "UPDATE workspace_items SET position = ? WHERE workspace_id = ? AND item_ref = ?",
                    (int(entry["position"]), workspace_id, str(entry["ref"])),
                )
                moved += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
            conn.execute(
                "UPDATE workspaces SET revision = revision + 1 WHERE id = ?",
                (workspace_id,),
            )
            return {
                "workspaceId": workspace_id,
                "recipeId": recipe_id,
                "explain": preview["explain"],
                "moved": moved,
            }

        return await transaction(self._db, _apply)

    async def delete(self, workspace_id: str, recipe_id: str) -> bool:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id FROM new217_sort_recipes WHERE id = ? AND workspace_id = ?",
            (recipe_id, workspace_id),
        )
        if row is None:
            return False
        await self._db.execute(
            "DELETE FROM new217_sort_recipes WHERE id = ? AND workspace_id = ?",
            (recipe_id, workspace_id),
        )
        return True


def _invert(value: Any) -> Any:
    if isinstance(value, str):
        return tuple(-ord(ch) for ch in value)
    return -value
