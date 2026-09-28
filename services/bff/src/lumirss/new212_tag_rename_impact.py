"""NEW-212 标签改名影响图 —— 改名前列出引用，确认后同步更新。

诚实边界：本代码库里**真正**引用一个标签的表面是：
- 同义词字典（new214_tag_synonyms.canonical 按名字引用）→ 名字键，必须改写；
- 互斥组成员（new213_tag_group_members 按 tag_id 引用）→ id 键，改名自动跟随
  （影响图如实列出，不需要也不应该改写）；
- item_tags 绑定（按 tag_id）→ 自动跟随，影响图给出受影响文章数；
- 合并向导台账（new211_merge_logs 里的源名快照）→ 信息性列出。
保存搜索的 query 是全文关键词、集合（工作区）成员是内容引用——它们都
**不引用标签**，绝不伪造「标签引用」。（无 AI / 无网络，纯本地表。）
"""

import sqlite3
from typing import Any

from lumirss.db_tx import transaction
from lumirss.storage import Database
from lumirss.tags import TagInvalid, normalize_tag_name


class TagRenameImpactStore:
    """改名影响图 + 确认后同步（单事务改名 + 名字键引用改写）。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def impact(self, tag_id: int, new_name: str) -> dict[str, Any]:
        clean = normalize_tag_name(new_name)
        await self._db.migrate()
        tag = await self._db.fetch_one("SELECT id, name FROM tags WHERE id = ?", (tag_id,))
        if tag is None:
            raise TagInvalid("标签不存在。")
        old_name = str(tag["name"])
        dupe = await self._db.fetch_one(
            "SELECT id FROM tags WHERE name = ? COLLATE NOCASE AND id != ?",
            (clean, tag_id),
        )
        if dupe is not None:
            raise TagInvalid("同名标签已存在。")
        synonyms = await self._db.fetch_all(
            "SELECT id, alias, canonical FROM new214_tag_synonyms WHERE canonical = ? COLLATE NOCASE",
            (old_name,),
        )
        groups = await self._db.fetch_all(
            "SELECT g.id, g.name FROM new213_tag_group_members m JOIN new213_tag_groups g ON g.id = m.group_id WHERE m.tag_id = ?",
            (tag_id,),
        )
        bindings = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM item_tags WHERE tag_id = ? AND status = 'active'",
            (tag_id,),
        )
        merge_logs = await self._db.fetch_all(
            "SELECT id, target_name, created_at FROM new211_merge_logs WHERE sources_json LIKE ? LIMIT 20",
            (f"%{old_name}%",),
        )
        return {
            "tagId": tag_id,
            "oldName": old_name,
            "newName": clean,
            "willRewrite": [
                {
                    "kind": "synonym",
                    "id": int(r["id"]),
                    "alias": str(r["alias"]),
                    "canonicalFrom": str(r["canonical"]),
                    "canonicalTo": clean,
                }
                for r in synonyms
            ],
            "autoFollow": [
                {"kind": "group", "id": int(r["id"]), "name": str(r["name"])}
                for r in groups
            ]
            + [
                {"kind": "merge_log", "id": str(r["id"]), "targetName": str(r["target_name"]), "createdAt": str(r["created_at"])}
                for r in merge_logs
            ],
            "bindings": int(bindings["n"]) if bindings is not None else 0,
        }

    async def rename_with_sync(self, tag_id: int, new_name: str) -> dict[str, Any]:
        """单事务：改名 + 同步名字键引用（同义词 canonical 改指新名）。"""
        impact = await self.impact(tag_id, new_name)  # 共享校验

        def _rename(conn: sqlite3.Connection) -> dict[str, Any]:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("UPDATE tags SET name = ? WHERE id = ?", (impact["newName"], tag_id))
            cur = conn.execute(
                "UPDATE new214_tag_synonyms SET canonical = ? WHERE canonical = ? COLLATE NOCASE",
                (impact["newName"], impact["oldName"]),
            )
            return {
                "tagId": tag_id,
                "oldName": impact["oldName"],
                "newName": impact["newName"],
                "synonymsRewritten": cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0,
                "autoFollowKept": len(impact["autoFollow"]),
                "bindingsFollowed": impact["bindings"],
            }

        try:
            return await transaction(self._db, _rename)
        except sqlite3.IntegrityError as exc:
            raise TagInvalid("改名冲突。") from exc
