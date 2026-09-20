"""F102 日报手工候选素材池 —— SQL 唯一入口。

一份配置一个池：用户显式指定的条目在生成时并入候选（preview 标
source="manual"），成功发布后标记 used_issue_key 并移出待用；原文删除
（引用解析失败）→ 预览/生成如实标注失效并跳过。

- 重复添加 → DigestPoolDuplicate（路由映射 409）；
- 排序 = position（升序），PATCH reorder 全量提交顺序；
- 删除配置级联清池（delete_config 显式删除——SQLite 未开外键级联）。

每文件 SQL 写站点 ≤4：INSERT（add）/ UPDATE（reorder 循环内、mark_used）/
DELETE（remove + delete_for_config 共 2 处字面量）。读站点不受限。
"""

import sqlite3
from typing import Any

from lumirss.db_tx import transaction
from lumirss.storage import Database
from lumirss.util import utc_now


class DigestPoolDuplicate(Exception):
    """同配置重复添加同一 entry_ref（路由映射 409）。"""


class DigestPoolEntryNotFound(Exception):
    """池条目不存在（或属于其他配置）。"""


_MAX_POOL_PER_CONFIG = 100
_MAX_REF_LEN = 512


class DigestMaterialPoolStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def add_entry(self, config_id: int, entry_ref: str) -> dict[str, Any]:
        """加入池（重复 → DigestPoolDuplicate）；position 追加到末尾。"""
        await self._db.migrate()
        clean = str(entry_ref or "").strip()[:_MAX_REF_LEN]
        if not clean:
            raise ValueError("entry_ref 不能为空。")
        count = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM digest_material_pool WHERE config_id = ? AND used_issue_key IS NULL",
            (config_id,),
        )
        if count is not None and int(count["n"]) >= _MAX_POOL_PER_CONFIG:
            raise ValueError(f"素材池已满（上限 {_MAX_POOL_PER_CONFIG}）。")
        row = await self._db.fetch_one(
            "SELECT COALESCE(MAX(position), -1) AS p FROM digest_material_pool WHERE config_id = ?",
            (config_id,),
        )
        try:
            row_id = await self._db.execute(
                "INSERT INTO digest_material_pool (config_id, entry_ref, added_at, position) VALUES (?, ?, ?, ?)",
                (config_id, clean, utc_now(), int(row["p"]) + 1 if row else 0),
            )
        except sqlite3.IntegrityError as exc:
            raise DigestPoolDuplicate(entry_ref) from exc
        return {
            "id": int(row_id) if row_id else None,
            "configId": config_id,
            "entryRef": clean,
            "usedIssueKey": None,
        }

    async def list_entries(self, config_id: int) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, config_id, entry_ref, added_at, position, used_issue_key FROM digest_material_pool WHERE config_id = ? ORDER BY position ASC, id ASC",
            (config_id,),
        )
        return [
            {
                "id": int(r["id"]),
                "configId": int(r["config_id"]),
                "entryRef": str(r["entry_ref"]),
                "addedAt": str(r["added_at"]),
                "position": int(r["position"]),
                "usedIssueKey": r["used_issue_key"],
            }
            for r in rows
        ]

    async def remove_entry(self, config_id: int, entry_id: int) -> bool:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id FROM digest_material_pool WHERE id = ? AND config_id = ?",
            (entry_id, config_id),
        )
        if row is None:
            return False
        await self._db.execute(
            "DELETE FROM digest_material_pool WHERE id = ? AND config_id = ?",
            (entry_id, config_id),
        )
        return True

    async def reorder(self, config_id: int, ordered_ids: list[int]) -> None:
        """全量提交顺序（未知 id 忽略；缺失 id 保持原相对顺序靠后）。"""
        await self._db.migrate()

        def _run(connection: Any) -> None:
            for index, entry_id in enumerate(ordered_ids):
                connection.execute(
                    "UPDATE digest_material_pool SET position = ? WHERE id = ? AND config_id = ?",
                    (index, int(entry_id), config_id),
                )

        await transaction(self._db, _run)

    async def pending_refs(self, config_id: int) -> list[dict[str, Any]]:
        """待用条目（used_issue_key IS NULL），position 升序。"""
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, entry_ref FROM digest_material_pool WHERE config_id = ? AND used_issue_key IS NULL ORDER BY position ASC, id ASC LIMIT ?",
            (config_id, _MAX_POOL_PER_CONFIG),
        )
        return [
            {"id": int(r["id"]), "entryRef": str(r["entry_ref"])} for r in rows
        ]

    async def mark_used(self, config_id: int, entry_refs: list[str], issue_key: str) -> int:
        """成功发布后把本轮实际消费的池条目标记 used_issue_key。

        只更新仍待用的行（并发/重复发布幂等）；返回更新行数。"""
        if not entry_refs:
            return 0
        await self._db.migrate()
        updated = 0
        for entry_ref in entry_refs[:_MAX_POOL_PER_CONFIG]:
            row = await self._db.fetch_one(
                "SELECT id FROM digest_material_pool WHERE config_id = ? AND entry_ref = ? AND used_issue_key IS NULL",
                (config_id, str(entry_ref)),
            )
            if row is None:
                continue
            await self._db.execute(
                "UPDATE digest_material_pool SET used_issue_key = ? WHERE id = ?",
                (issue_key, int(row["id"])),
            )
            updated += 1
        return updated

    async def delete_for_config(self, config_id: int) -> None:
        await self._db.migrate()
        await self._db.execute(
            "DELETE FROM digest_material_pool WHERE config_id = ?",
            (config_id,),
        )
