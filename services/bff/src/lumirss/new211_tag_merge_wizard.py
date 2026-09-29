"""NEW-211 标签合并向导 —— 多个个人标签 → 单一目标标签的原子合并。

与 N150（单行槽位、双源合并）的分工：
- 本模块面向「向导」场景：一次选多个源标签（1-20 个），预览受影响
  文章与受影响的引用（同义词字典 canonical 指向、互斥组成员），确认后
  在**单个事务**内完成：快照 → 去重折叠 → 绑定改指 → 删除源标签 →
  引用同步 → 落一行可撤销映射记录（new211_merge_logs，保留最近 10 条）；
- 撤销（undo）按 log id 定向、24h 窗口内有效：原子重建全部源标签并
  原样恢复其绑定（含被折叠的重复绑定——目标保留合并来的绑定，两侧
  语义都与合并前一致）；任一源名已被重建占用 → 整体拒绝（409）；
- 只碰 Lumi 自有的 item_tags/tags 及本组引用表，FreshRSS 类目零接触。

无 AI / 无网络：全部操作落在 per-user 库本地表上。
"""

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from typing import Any

from lumirss.db_tx import transaction
from lumirss.storage import Database
from lumirss.tags import normalize_tag_name
from lumirss.util import utc_now

_MAX_SOURCES = 20
_MAX_LOGS = 10
_UNDO_TTL = 24 * 3600


class MergeWizardInvalid(ValueError):
    """合并请求非法（源/目标重叠、数量越界、标签不存在），映射 422。"""


class MergeLogNotFound(Exception):
    """没有这条合并记录（或已超出 24h 撤销窗口），映射 404。"""


class MergeUndoConflict(Exception):
    """撤销冲突：某源标签名已被重新占用（含上一次 undo 的重建），映射 409。"""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.name = name


def _clean_sources(source_ids: list[int]) -> list[int]:
    cleaned: list[int] = []
    for raw in source_ids:
        value = int(raw)
        if value not in cleaned:
            cleaned.append(value)
    if not 1 <= len(cleaned) <= _MAX_SOURCES:
        raise MergeWizardInvalid(f"源标签数量必须是 1-{_MAX_SOURCES} 个。")
    return cleaned


class TagMergeWizardStore:
    """new211_merge_logs + item_tags/tags + 本组引用表的原子合并。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    # -- 预览 ---------------------------------------------------------------

    async def preview(self, source_ids: list[int], target_id: int) -> dict[str, Any]:
        """只读预览：逐源绑定数/与目标重复数、受影响文章（去重后）、
        会被同步的引用计数（同义词 canonical / 互斥组成员）。"""
        sources = _clean_sources(source_ids)
        if target_id in sources:
            raise MergeWizardInvalid("目标标签不能同时在源标签列表中。")
        await self._db.migrate()
        all_ids = (*sources, target_id)
        placeholders = ",".join("?" for _ in all_ids)
        id_rows = await self._db.fetch_all(
            f"SELECT id, name FROM tags WHERE id IN ({placeholders})",
            (*all_ids,),
        )
        by_id = {int(r["id"]): str(r["name"]) for r in id_rows}
        missing = [sid for sid in (*sources, target_id) if sid not in by_id]
        if missing:
            raise MergeWizardInvalid(f"标签不存在：{', '.join(map(str, missing))}。")

        per_source: list[dict[str, Any]] = []
        affected_refs: set[str] = set()
        for sid in sources:
            counts = await self._db.fetch_one(
                "SELECT COUNT(*) AS n,"
                " SUM(CASE WHEN EXISTS (SELECT 1 FROM item_tags b WHERE b.item_ref = a.item_ref AND b.tag_id = ?) THEN 1 ELSE 0 END) AS overlaps"
                " FROM item_tags a WHERE a.tag_id = ?",
                (target_id, sid),
            )
            bindings = int(counts["n"]) if counts is not None else 0
            overlaps = int(counts["overlaps"] or 0) if counts is not None else 0
            refs = await self._db.fetch_all(
                "SELECT item_ref FROM item_tags WHERE tag_id = ? LIMIT 500",
                (sid,),
            )
            affected_refs.update(str(r["item_ref"]) for r in refs)
            per_source.append(
                {
                    "tagId": sid,
                    "name": by_id[sid],
                    "bindings": bindings,
                    "overlaps": overlaps,
                    "willMove": bindings - overlaps,
                }
            )
        source_names = [by_id[sid] for sid in sources]
        name_placeholders = ",".join("?" for _ in source_names)
        synonyms = await self._db.fetch_one(
            f"SELECT COUNT(*) AS n FROM new214_tag_synonyms WHERE canonical IN ({name_placeholders})",
            (*source_names,),
        )
        id_placeholders = ",".join("?" for _ in sources)
        group_members = await self._db.fetch_one(
            f"SELECT COUNT(*) AS n FROM new213_tag_group_members WHERE tag_id IN ({id_placeholders})",
            (*sources,),
        )
        return {
            "target": {"tagId": target_id, "name": by_id[target_id]},
            "sources": per_source,
            "affectedArticles": len(affected_refs),
            "references": {
                "synonyms": int(synonyms["n"]) if synonyms is not None else 0,
                "groupMemberships": int(group_members["n"]) if group_members is not None else 0,
            },
        }

    # -- 原子合并 ------------------------------------------------------------

    async def apply_merge(self, source_ids: list[int], target_id: int) -> dict[str, Any]:
        """单事务：快照 → 折叠重复 → 改指 → 删源 → 引用同步 → 落台账。"""
        preview = await self.preview(source_ids, target_id)  # 共享校验

        def _merge(conn: sqlite3.Connection) -> dict[str, Any]:
            conn.execute("BEGIN IMMEDIATE")
            sources_payload: list[dict[str, Any]] = []
            synonyms_synced = 0
            # 引用计数必须在删除源标签之前取（组成员行随 tag FK 级联消失）。
            source_ids_pre = [int(s["tagId"]) for s in preview["sources"]]
            group_placeholders_pre = ",".join("?" for _ in source_ids_pre)
            group_rows = conn.execute(
                f"SELECT COUNT(*) AS n FROM new213_tag_group_members WHERE tag_id IN ({group_placeholders_pre})",
                (*source_ids_pre,),
            ).fetchone()
            for source in preview["sources"]:
                sid = int(source["tagId"])
                rows = conn.execute(
                    "SELECT item_ref, origin, status, created_at FROM item_tags WHERE tag_id = ?",
                    (sid,),
                ).fetchall()
                bindings = [
                    {
                        "itemRef": str(row["item_ref"]),
                        "origin": str(row["origin"]),
                        "status": str(row["status"]),
                        "createdAt": str(row["created_at"]),
                    }
                    for row in rows
                ]
                sources_payload.append(
                    {"tagId": sid, "name": str(source["name"]), "bindings": bindings}
                )
                # 引用同步 1：同义词字典 canonical 指向源名 → 改指目标名。
                cur = conn.execute(
                    "UPDATE new214_tag_synonyms SET canonical = ? WHERE canonical = ?",
                    (preview["target"]["name"], str(source["name"])),
                )
                synonyms_synced += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
                # 折叠重复 → 改指 → 删除源标签（与 N150 同序）。
                conn.execute(
                    "DELETE FROM item_tags WHERE tag_id = ? AND item_ref IN (SELECT item_ref FROM item_tags WHERE tag_id = ?)",
                    (sid, target_id),
                )
                conn.execute("UPDATE item_tags SET tag_id = ? WHERE tag_id = ?", (target_id, sid))
                conn.execute("DELETE FROM tags WHERE id = ?", (sid,))
                # 引用同步 2：互斥组成员行随 tag FK 级联消失（数量已在删除
                # 前计数；绝不擅自把目标塞进组——那是用户意图，预览已呈现）。
            log_id = str(uuid.uuid4())
            conn.execute(
                "INSERT INTO new211_merge_logs (id, target_tag_id, target_name, sources_json, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    log_id,
                    target_id,
                    str(preview["target"]["name"]),
                    json.dumps(sources_payload, ensure_ascii=False),
                    utc_now(),
                ),
            )
            conn.execute(
                "DELETE FROM new211_merge_logs WHERE id NOT IN (SELECT id FROM new211_merge_logs ORDER BY created_at DESC LIMIT ?)",
                (_MAX_LOGS,),
            )
            return {
                "logId": log_id,
                "targetTagId": target_id,
                "targetName": str(preview["target"]["name"]),
                "mergedSources": [
                    {"tagId": int(s["tagId"]), "name": str(s["name"]), "bindings": len(s["bindings"])}
                    for s in sources_payload
                ],
                "synonymsSynced": synonyms_synced,
                "groupMembershipsReleased": int(group_rows["n"]) if group_rows is not None else 0,
            }

        return await transaction(self._db, _merge)

    # -- 撤销 ----------------------------------------------------------------

    async def undo(self, log_id: str) -> dict[str, Any]:
        """按 log id 撤销（24h 窗口）：原子重建全部源标签 + 原样恢复绑定。"""
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT target_tag_id, target_name, sources_json, created_at FROM new211_merge_logs WHERE id = ?",
            (log_id,),
        )
        if row is None:
            raise MergeLogNotFound("没有这条合并记录。")
        try:
            created_at = datetime.fromisoformat(str(row["created_at"]))
        except ValueError as exc:
            raise MergeLogNotFound("合并记录时间戳无效。") from exc
        if (datetime.now(UTC) - created_at).total_seconds() > _UNDO_TTL:
            raise MergeLogNotFound("合并撤销窗口（24 小时）已过期。")
        try:
            sources = json.loads(str(row["sources_json"]))
        except ValueError as exc:
            raise MergeLogNotFound("合并记录数据损坏。") from exc
        if not isinstance(sources, list) or not sources:
            raise MergeLogNotFound("合并记录数据损坏。")

        # 冲突预检：任一源名已存在（含上一次 undo 的重建）→ 整体拒绝。
        for source in sources:
            name = normalize_tag_name(str(source.get("name") or ""))
            existing = await self._db.fetch_one(
                "SELECT id FROM tags WHERE name = ? COLLATE NOCASE", (name,)
            )
            if existing is not None:
                raise MergeUndoConflict(name)

        def _undo(conn: sqlite3.Connection) -> dict[str, Any]:
            conn.execute("BEGIN IMMEDIATE")
            restored_sources: list[dict[str, Any]] = []
            for source in sources:
                name = normalize_tag_name(str(source.get("name") or ""))
                cur = conn.execute("INSERT INTO tags (name) VALUES (?)", (name,))
                new_id = int(cur.lastrowid)
                restored = 0
                for binding in source.get("bindings") or []:
                    if not isinstance(binding, dict):
                        continue
                    item_ref = str(binding.get("itemRef") or "")
                    origin = str(binding.get("origin") or "manual")
                    status = str(binding.get("status") or "active")
                    created = str(binding.get("createdAt") or utc_now())
                    if not item_ref or origin not in ("manual", "source", "ai"):
                        continue
                    conn.execute(
                        "INSERT INTO item_tags (item_ref, tag_id, origin, status, created_at) VALUES (?, ?, ?, ?, ?)",
                        (item_ref, new_id, origin, status, created),
                    )
                    restored += 1
                restored_sources.append({"tagId": new_id, "name": name, "restoredBindings": restored})
            conn.execute("DELETE FROM new211_merge_logs WHERE id = ?", (log_id,))
            return {
                "undoneLogId": log_id,
                "targetTagId": int(row["target_tag_id"]),
                "targetName": str(row["target_name"]),
                "restoredSources": restored_sources,
            }

        return await transaction(self._db, _undo)

    async def list_logs(self, *, limit: int = 10) -> list[dict[str, Any]]:
        """可撤销映射记录（新→旧；含已超窗的，undo 时如实报 404）。"""
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, target_tag_id, target_name, sources_json, created_at FROM new211_merge_logs ORDER BY created_at DESC LIMIT ?",
            (max(1, min(limit, _MAX_LOGS)),),
        )
        items: list[dict[str, Any]] = []
        for row in rows:
            try:
                sources = json.loads(str(row["sources_json"]))
            except ValueError:
                sources = []
            items.append(
                {
                    "logId": str(row["id"]),
                    "targetTagId": int(row["target_tag_id"]),
                    "targetName": str(row["target_name"]),
                    "sources": [
                        {"tagId": int(s.get("tagId") or 0), "name": str(s.get("name") or ""), "bindings": len(s.get("bindings") or [])}
                        for s in sources
                        if isinstance(s, dict)
                    ],
                    "createdAt": str(row["created_at"]),
                }
            )
        return items
