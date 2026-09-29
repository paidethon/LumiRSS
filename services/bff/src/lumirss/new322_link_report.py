"""NEW-322 Obsidian 链接解析报告 —— 明确 / 歧义 / 失效 + 逐项纠正。

口径：

- 数据源是只读投影 ``obsidian_notes`` 的 wikilink_raws 索引；解析键
  规则与反链（obsidian_backlinks）一致：rel_path（忽略 .md/大小写）
  精确命中优先，其次 basename 短链与标题；
- 分类：``resolved``（唯一候选）、``ambiguous``（同名 stem/标题多候选
  ——投影按 FIX-334 最近路径确定性解析，但报告如实列出全部候选）、
  ``broken``（无候选或路径越出 Vault）、``corrected``（用户已为该条
  链接显式指定导入映射目标）；
- 纠正（correction）：(note_uuid, raw) → 指定目标笔记，报告重算时
  作为该条链接的覆盖裁决；目标不存在 → 纠正不生效（broken，原因
  如实）；
- 范围（scope）：用户选定 noteUuids，缺省 = 全部投影笔记（有界）。

per-user：报告与纠正都在 per-user 库；投影是 owner 的 Vault 面
（路由层 owner 门槛），A 的纠正对 B 不可见。
"""

import json
from typing import Any

from lumirss.obsidian_backlinks import parse_wikilink
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_REPORT_ITEMS = 500
_MAX_CANDIDATES = 5
_MAX_RAW_LENGTH = 200


def _normalize_key(rel_path: str) -> str:
    return rel_path.strip().lower().removesuffix(".md")


class LinkReportStore:
    """NEW-322 报告计算 + 纠正 CRUD（per-user）。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def build_report(
        self, note_uuids: list[str] | None = None
    ) -> dict[str, Any]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT item_uuid, rel_path, title, wikilink_raws, wikilinks FROM obsidian_notes"
            " ORDER BY rel_path ASC LIMIT 5000"
        )
        notes = [
            {
                "uuid": str(row["item_uuid"]),
                "rel_path": str(row["rel_path"]),
                "title": str(row["title"] or ""),
                "raws": self._load_raws(row),
            }
            for row in rows
        ]
        by_uuid = {note["uuid"]: note for note in notes}
        scope = notes
        unknown_scope: list[str] = []
        if note_uuids:
            wanted = [uuid.strip() for uuid in note_uuids if uuid.strip()]
            scope = [by_uuid[uuid] for uuid in wanted if uuid in by_uuid]
            unknown_scope = [uuid for uuid in wanted if uuid not in by_uuid]
        index = self._build_index(notes)
        corrections = {
            (str(row["note_uuid"]), str(row["raw"])): str(row["target_uuid"])
            for row in await self._db.fetch_all(
                "SELECT note_uuid, raw, target_uuid FROM obsidian_link_corrections"
            )
        }
        known_uuids = {note["uuid"] for note in notes}
        items: list[dict[str, Any]] = []
        counts = {"resolved": 0, "ambiguous": 0, "broken": 0, "corrected": 0}
        for note in scope:
            for raw in note["raws"]:
                if len(items) >= _MAX_REPORT_ITEMS:
                    break
                item = self._classify(
                    note, raw, index, corrections, known_uuids
                )
                counts[item["status"]] = counts.get(item["status"], 0) + 1
                items.append(item)
        return {
            "counts": counts,
            "items": items,
            "truncated": sum(counts.values()) > _MAX_REPORT_ITEMS,
            "unknownNoteUuids": unknown_scope,
            "honestyNote": "报告是只读计算；歧义项在投影中按最近路径确定性解析，纠正可逐项覆盖导入映射。",
        }

    @staticmethod
    def _load_raws(row: Any) -> list[str]:
        try:
            raws = json.loads(str(row["wikilink_raws"] or "[]"))
        except json.JSONDecodeError:
            raws = []
        if not isinstance(raws, list) or not raws:
            try:
                raws = json.loads(str(row["wikilinks"] or "[]"))
            except json.JSONDecodeError:
                raws = []
        return [
            str(raw)[:_MAX_RAW_LENGTH]
            for raw in (raws if isinstance(raws, list) else [])
            if str(raw).strip()
        ]

    @staticmethod
    def _build_index(
        notes: list[dict[str, Any]],
    ) -> dict[str, list[tuple[str, str]]]:
        """键 → [(rel_path, uuid)]；同名键保留全部候选（歧义判定用）。

        同一笔记的 stem 与标题相同时只记一次（否则会把唯一的候选数成
        两份、把 resolved 误判成 ambiguous）。"""
        index: dict[str, list[tuple[str, str]]] = {}

        def _add(key: str, rel_path: str, uuid: str) -> None:
            bucket = index.setdefault(key, [])
            if (rel_path, uuid) not in bucket:
                bucket.append((rel_path, uuid))

        for note in notes:
            rel_path = note["rel_path"]
            uuid = note["uuid"]
            key = _normalize_key(rel_path)
            if key:
                _add(key, rel_path, uuid)
            stem = key.rsplit("/", 1)[-1]
            if stem and stem != key:
                _add(stem, rel_path, uuid)
            title = note["title"].strip()
            if title:
                _add(title, rel_path, uuid)
        return index

    def _classify(
        self,
        note: dict[str, Any],
        raw: str,
        index: dict[str, list[tuple[str, str]]],
        corrections: dict[tuple[str, str], str],
        known_uuids: set[str],
    ) -> dict[str, Any]:
        parsed = parse_wikilink(raw)
        base = {
            "noteUuid": note["uuid"],
            "noteRelPath": note["rel_path"],
            "raw": raw,
            "target": parsed.target,
        }
        correction_target = corrections.get((note["uuid"], raw))
        if correction_target is not None:
            if correction_target in known_uuids:
                return {
                    **base,
                    "status": "corrected",
                    "targetUuid": correction_target,
                    "candidates": [],
                }
            return {
                **base,
                "status": "broken",
                "reason": "correction_target_missing",
                "candidates": [],
            }
        if parsed.escaped_vault:
            return {**base, "status": "broken", "reason": "path_escaped_vault", "candidates": []}
        if not parsed.target:
            return {**base, "status": "broken", "reason": "empty_target", "candidates": []}
        direct = index.get(_normalize_key(parsed.target), [])
        candidates = direct or index.get(parsed.target, [])
        if len(candidates) == 1:
            return {
                **base,
                "status": "resolved",
                "targetUuid": candidates[0][1],
                "candidates": [candidates[0][0]],
            }
        if len(candidates) > 1:
            return {
                **base,
                "status": "ambiguous",
                "candidates": [rel for rel, _ in candidates[:_MAX_CANDIDATES]],
            }
        return {**base, "status": "broken", "reason": "unresolved", "candidates": []}

    # ------------------------------------------------------------------
    # 纠正 CRUD
    # ------------------------------------------------------------------

    async def put_correction(
        self, note_uuid: str, raw: str, target_uuid: str
    ) -> dict[str, Any]:
        await self._db.migrate()
        clean_note = note_uuid.strip()
        clean_raw = raw.strip()[:_MAX_RAW_LENGTH]
        clean_target = target_uuid.strip()
        if not clean_note or not clean_raw or not clean_target:
            raise ValueError("noteUuid / raw / targetUuid 都不能为空。")
        note = await self._db.fetch_one(
            "SELECT item_uuid FROM obsidian_notes WHERE item_uuid = ?",
            (clean_note,),
        )
        target = await self._db.fetch_one(
            "SELECT item_uuid FROM obsidian_notes WHERE item_uuid = ?",
            (clean_target,),
        )
        if note is None:
            raise KeyError("noteUuid")
        if target is None:
            raise LookupError("targetUuid")
        now = utc_now()
        await self._db.execute(
            "INSERT INTO obsidian_link_corrections (note_uuid, raw, target_uuid, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(note_uuid, raw) DO UPDATE SET"
            " target_uuid = excluded.target_uuid, updated_at = excluded.updated_at",
            (clean_note, clean_raw, clean_target, now, now),
        )
        return {
            "noteUuid": clean_note,
            "raw": clean_raw,
            "targetUuid": clean_target,
            "updatedAt": now,
        }

    async def list_corrections(self) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT c.note_uuid, c.raw, c.target_uuid, c.updated_at,"
            " n.rel_path AS target_rel_path"
            " FROM obsidian_link_corrections c"
            " LEFT JOIN obsidian_notes n ON n.item_uuid = c.target_uuid"
            " ORDER BY c.updated_at DESC LIMIT 500"
        )
        return [
            {
                "noteUuid": str(row["note_uuid"]),
                "raw": str(row["raw"]),
                "targetUuid": str(row["target_uuid"]),
                "targetRelPath": row["target_rel_path"],
                "updatedAt": str(row["updated_at"]),
            }
            for row in rows
        ]

    async def delete_correction(self, note_uuid: str, raw: str) -> bool:
        await self._db.migrate()
        deleted = await self._db.execute(
            "DELETE FROM obsidian_link_corrections WHERE note_uuid = ? AND raw = ?",
            (note_uuid.strip(), raw.strip()[:_MAX_RAW_LENGTH]),
        )
        return bool(deleted)
