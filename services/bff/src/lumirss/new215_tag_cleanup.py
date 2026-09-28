"""NEW-215 标签使用清理台 —— 无人使用 / 仅规则引用 / 仍有关联内容 三桶。

诚实口径（每桶都来自服务端真实查询，不是前端猜的）：
- bindings：item_tags 里 active 绑定数（「仍有关联内容」）；
- references：同义词字典 canonical 指向（名字键）+ 互斥组成员（id 键）
  + 合并向导台账里的源名快照（信息性）——这些是「规则依赖」；
- unused：bindings == 0 且 references == 0；
- referenced_only：bindings == 0 但 references > 0；
- in_use：bindings > 0。

删除保护：带引用的标签必须显式 `acknowledgeReferences` 才能删，删除时
同一事务清理其名字键引用（同义词行）与 id 键引用（组成员行）；批量
删除里只要有一条带引用且未确认 → **整批拒绝**（绝不一键误删被规则
依赖的标签）。
"""

import sqlite3
from typing import Any

from lumirss.db_tx import transaction
from lumirss.storage import Database

_MAX_BATCH_DELETE = 50


class TagCleanupBlocked(Exception):
    """删除被清理台保护拦截（带引用未确认），映射 409。

    ``tag_id`` / ``name`` / ``references`` 供响应如实列出拦截原因。
    """

    def __init__(self, tag_id: int, name: str, references: int) -> None:
        super().__init__(name)
        self.tag_id = tag_id
        self.name = name
        self.references = references


class TagCleanupInvalid(ValueError):
    """清理载荷非法（空列表/数量越界/标签不存在），映射 422。"""


class TagCleanupStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def report(self) -> dict[str, Any]:
        await self._db.migrate()
        tags = await self._db.fetch_all("SELECT id, name FROM tags ORDER BY name ASC")
        bindings = await self._db.fetch_all(
            "SELECT tag_id, COUNT(*) AS n FROM item_tags WHERE status = 'active' GROUP BY tag_id"
        )
        binding_by_tag = {int(r["tag_id"]): int(r["n"]) for r in bindings}
        synonym_refs = await self._db.fetch_all(
            "SELECT canonical, COUNT(*) AS n FROM new214_tag_synonyms GROUP BY canonical"
        )
        synonym_by_name = {str(r["canonical"]).lower(): int(r["n"]) for r in synonym_refs}
        group_refs = await self._db.fetch_all(
            "SELECT tag_id, COUNT(*) AS n FROM new213_tag_group_members GROUP BY tag_id"
        )
        group_by_tag = {int(r["tag_id"]): int(r["n"]) for r in group_refs}
        merge_logs = await self._db.fetch_all("SELECT sources_json FROM new211_merge_logs")

        def _merge_log_names() -> set[str]:
            import json

            names: set[str] = set()
            for row in merge_logs:
                try:
                    sources = json.loads(str(row["sources_json"]))
                except ValueError:
                    continue
                for source in sources if isinstance(sources, list) else []:
                    if isinstance(source, dict) and source.get("name"):
                        names.add(str(source["name"]).lower())
            return names

        merge_names = _merge_log_names()
        buckets: dict[str, list[dict[str, Any]]] = {
            "unused": [],
            "referencedOnly": [],
            "inUse": [],
        }
        for tag in tags:
            tag_id = int(tag["id"])
            name = str(tag["name"])
            bound = binding_by_tag.get(tag_id, 0)
            refs = synonym_by_name.get(name.lower(), 0) + group_by_tag.get(tag_id, 0)
            entry = {
                "tagId": tag_id,
                "name": name,
                "bindings": bound,
                "references": {
                    "synonyms": synonym_by_name.get(name.lower(), 0),
                    "groupMemberships": group_by_tag.get(tag_id, 0),
                    "mergeLogs": 1 if name.lower() in merge_names else 0,
                },
            }
            if bound > 0:
                buckets["inUse"].append(entry)
            elif refs > 0:
                buckets["referencedOnly"].append(entry)
            else:
                buckets["unused"].append(entry)
        return {"buckets": buckets}

    async def delete_tags(
        self, tag_ids: list[int], *, acknowledge_references: bool
    ) -> dict[str, Any]:
        """批量删除：整批原子——任一条带引用且未确认 → 全批拒绝。"""
        cleaned: list[int] = []
        for raw in tag_ids:
            value = int(raw)
            if value not in cleaned:
                cleaned.append(value)
        if not 1 <= len(cleaned) <= _MAX_BATCH_DELETE:
            raise TagCleanupInvalid(f"删除数量必须是 1-{_MAX_BATCH_DELETE}。")
        await self._db.migrate()

        def _delete(conn: sqlite3.Connection) -> dict[str, Any]:
            conn.execute("BEGIN IMMEDIATE")
            results: list[dict[str, Any]] = []
            for tag_id in cleaned:
                tag = conn.execute("SELECT id, name FROM tags WHERE id = ?", (tag_id,)).fetchone()
                if tag is None:
                    raise TagCleanupInvalid(f"标签不存在：{tag_id}。")
                name = str(tag["name"])
                bound = conn.execute(
                    "SELECT COUNT(*) AS n FROM item_tags WHERE tag_id = ? AND status = 'active'",
                    (tag_id,),
                ).fetchone()
                synonyms = conn.execute(
                    "SELECT COUNT(*) AS n FROM new214_tag_synonyms WHERE canonical = ? COLLATE NOCASE",
                    (name,),
                ).fetchone()
                groups = conn.execute(
                    "SELECT COUNT(*) AS n FROM new213_tag_group_members WHERE tag_id = ?",
                    (tag_id,),
                ).fetchone()
                ref_count = int(synonyms["n"] or 0) + int(groups["n"] or 0)
                if ref_count > 0 and not acknowledge_references:
                    raise TagCleanupBlocked(tag_id, name, ref_count)
                conn.execute("DELETE FROM item_tags WHERE tag_id = ?", (tag_id,))
                conn.execute(
                    "DELETE FROM new214_tag_synonyms WHERE canonical = ? COLLATE NOCASE", (name,)
                )
                conn.execute("DELETE FROM new213_tag_group_members WHERE tag_id = ?", (tag_id,))
                conn.execute("DELETE FROM tags WHERE id = ?", (tag_id,))
                results.append(
                    {
                        "tagId": tag_id,
                        "name": name,
                        "deletedBindings": int(bound["n"] or 0),
                        "deletedSynonyms": int(synonyms["n"] or 0),
                        "deletedGroupMemberships": int(groups["n"] or 0),
                    }
                )
            return {"deleted": results, "acknowledgedReferences": acknowledge_references}

        try:
            return await transaction(self._db, _delete)
        except sqlite3.Error as exc:
            raise TagCleanupInvalid("删除失败。") from exc
