"""NEW-321 Obsidian 标签映射规则 —— 源库标签 → LumiRSS 个人标签。

口径：

- 源标签来自只读投影 ``obsidian_notes``（frontmatter + 行内 #标签），
  本模块绝不写 Vault——映射只改变【导入层】：规则物化到
  ``obsidian_import_tags``（个人标签），源标签原样保留；
- 预览（preview）是纯计算：每个源标签 → 生效个人标签（有规则用规则，
  无规则原样），并列出层级展开（``a/b`` 隐含父级 ``a``）、合并
  （多条规则汇到同一目标）、冲突（目标是另一个未映射源标签的名；
  目标嵌套在自身之下成环）；
- 物化（materialize）= 按当前规则全量重建导入层（DELETE + INSERT，
  单事务），计数如实；笔记与标签的对应关系可经 /import 查询。

per-user：规则与导入层都在 per-user 库（RoutingDatabase）；投影是
owner 的 Vault 面（路由层 owner 门槛），A 的规则对 B 不可见。
"""

import json
from typing import Any

from lumirss.db_tx import transaction
from lumirss.storage import Database
from lumirss.util import utc_now

MAX_SOURCE_TAG = 50
MAX_TARGET_TAG = 100
_MAX_NOTES_SCANNED = 5000
_MAX_IMPORT_LIST = 200


class TagMappingInvalid(ValueError):
    """映射规则非法（映射 400）。"""


def validate_source_tag(raw: Any) -> str:
    if not isinstance(raw, str):
        raise TagMappingInvalid("sourceTag 必须是字符串。")
    clean = raw.strip().lstrip("#")
    if not clean or len(clean) > MAX_SOURCE_TAG:
        raise TagMappingInvalid(f"sourceTag 不能为空且 ≤{MAX_SOURCE_TAG} 字符。")
    return clean


def validate_target_tag(raw: Any) -> str:
    if not isinstance(raw, str):
        raise TagMappingInvalid("targetTag 必须是字符串。")
    clean = raw.strip()
    if not clean or len(clean) > MAX_TARGET_TAG:
        raise TagMappingInvalid(f"targetTag 不能为空且 ≤{MAX_TARGET_TAG} 字符。")
    if clean.startswith("/") or clean.endswith("/") or "//" in clean:
        raise TagMappingInvalid("targetTag 不能以 / 开头/结尾或包含连续斜杠。")
    for part in clean.split("/"):
        part_clean = part.strip()
        if not part_clean or part_clean.startswith("."):
            raise TagMappingInvalid("targetTag 的每级层级不能为空或以点开头。")
    return "/".join(part.strip() for part in clean.split("/"))


async def list_source_tags(db: Database) -> list[str]:
    """投影中出现过的全部源标签（去重、字典序，有界）。"""
    await db.migrate()
    rows = await db.fetch_all(
        "SELECT tags FROM obsidian_notes LIMIT ?",
        (_MAX_NOTES_SCANNED,),
    )
    tags: set[str] = set()
    for row in rows:
        try:
            loaded = json.loads(str(row["tags"] or "[]"))
        except json.JSONDecodeError:
            continue
        if isinstance(loaded, list):
            tags.update(str(tag) for tag in loaded if str(tag).strip())
    return sorted(tags)


def _implied_parents(target: str) -> list[str]:
    parts = [part for part in target.split("/") if part]
    return ["/".join(parts[: i + 1]) for i in range(len(parts) - 1)]


def build_preview(
    source_tags: list[str], rules: dict[str, str]
) -> dict[str, Any]:
    """纯函数预览：映射结果 + 层级 + 合并 + 冲突（不触库，可测）。"""
    source_set = set(source_tags)
    mappings: list[dict[str, Any]] = []
    by_target: dict[str, list[str]] = {}
    hierarchy: dict[str, list[str]] = {}
    conflicts: list[dict[str, str]] = []
    for tag in source_tags:
        target = rules.get(tag, tag)
        mappings.append({"sourceTag": tag, "targetTag": target, "mapped": tag in rules})
        by_target.setdefault(target, []).append(tag)
        parents = [p for p in _implied_parents(target) if p != target]
        if parents:
            hierarchy[tag] = parents
        if target != tag and target.startswith(f"{tag}/"):
            conflicts.append(
                {
                    "sourceTag": tag,
                    "targetTag": target,
                    "kind": "self_nesting",
                    "detail": "映射目标嵌套在源标签自身之下（成环）。",
                }
            )
        elif (
            target != tag
            and target in source_set
            and rules.get(target, target) == target
        ):
            # 目标是另一个【未再映射】的源标签名 → 两个不同源标签收敛到
            # 同一个个人标签（合并警告，不是错误——有时正是用户意图）。
            conflicts.append(
                {
                    "sourceTag": tag,
                    "targetTag": target,
                    "kind": "target_is_source_tag",
                    "detail": f"目标 {target} 本身也是源标签；该源标签的笔记会与映射结果合并。",
                }
            )
    merges = [
        {"targetTag": target, "sourceTags": sorted(sources)}
        for target, sources in sorted(by_target.items())
        if len(sources) > 1
    ]
    return {
        "sourceTags": source_tags,
        "mappings": mappings,
        "hierarchy": hierarchy,
        "conflicts": conflicts,
        "merges": merges,
        "honestyNote": "预览零写入；映射只改变导入层，源库标签与 Vault 文件保持不变。",
    }


class TagMappingStore:
    """NEW-321 规则 + 导入层物化（per-user）。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def rules(self) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT source_tag, target_tag, updated_at FROM obsidian_tag_mappings"
            " ORDER BY source_tag ASC LIMIT 500"
        )
        return [
            {
                "sourceTag": str(row["source_tag"]),
                "targetTag": str(row["target_tag"]),
                "updatedAt": str(row["updated_at"]),
            }
            for row in rows
        ]

    async def put_rule(self, source_tag: str, target_tag: str) -> dict[str, Any]:
        source = validate_source_tag(source_tag)
        target = validate_target_tag(target_tag)
        now = utc_now()
        await self._db.migrate()
        await self._db.execute(
            "INSERT INTO obsidian_tag_mappings (source_tag, target_tag, created_at, updated_at)"
            " VALUES (?, ?, ?, ?)"
            " ON CONFLICT(source_tag) DO UPDATE SET"
            " target_tag = excluded.target_tag, updated_at = excluded.updated_at",
            (source, target, now, now),
        )
        return {"sourceTag": source, "targetTag": target, "updatedAt": now}

    async def delete_rule(self, source_tag: str) -> bool:
        source = validate_source_tag(source_tag)
        await self._db.migrate()
        deleted = await self._db.execute(
            "DELETE FROM obsidian_tag_mappings WHERE source_tag = ?", (source,)
        )
        return bool(deleted)

    async def preview(self) -> dict[str, Any]:
        source_tags = await list_source_tags(self._db)
        rule_map = {rule["sourceTag"]: rule["targetTag"] for rule in await self.rules()}
        return build_preview(source_tags, rule_map)

    async def materialize(self) -> dict[str, Any]:
        """按当前规则全量重建导入层（单事务；计数如实）。"""
        await self._db.migrate()
        notes = await self._db.fetch_all(
            "SELECT item_uuid, tags FROM obsidian_notes LIMIT ?",
            (_MAX_NOTES_SCANNED,),
        )
        rule_map = {rule["sourceTag"]: rule["targetTag"] for rule in await self.rules()}
        rows: list[tuple[str, str, str]] = []
        now = utc_now()
        tagged_notes = 0
        distinct_tags: set[str] = set()
        for row in notes:
            try:
                source_tags = json.loads(str(row["tags"] or "[]"))
            except json.JSONDecodeError:
                source_tags = []
            mapped: list[str] = []
            for tag in source_tags if isinstance(source_tags, list) else []:
                target = rule_map.get(str(tag), str(tag))
                if target and target not in mapped:
                    mapped.append(target)
            if not mapped:
                continue
            tagged_notes += 1
            distinct_tags.update(mapped)
            note_uuid = str(row["item_uuid"])
            rows.extend((note_uuid, tag, now) for tag in mapped)

        def _tx(conn: Any) -> None:
            conn.execute("DELETE FROM obsidian_import_tags")
            conn.executemany(
                "INSERT OR IGNORE INTO obsidian_import_tags (note_uuid, tag, materialized_at)"
                " VALUES (?, ?, ?)",
                rows,
            )

        await transaction(self._db, _tx)
        return {
            "notesTagged": tagged_notes,
            "tagCount": len(distinct_tags),
            "rulesApplied": len(rule_map),
            "honestyNote": "导入层已按当前规则重建；源库标签不变，Vault 未被写入。",
        }

    async def import_overview(self) -> list[dict[str, Any]]:
        """导入层现有个人标签 → 笔记数（有界）。"""
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT tag, COUNT(*) AS n FROM obsidian_import_tags"
            " GROUP BY tag ORDER BY tag ASC LIMIT ?",
            (_MAX_IMPORT_LIST,),
        )
        return [{"tag": str(row["tag"]), "count": int(row["n"])} for row in rows]

    async def notes_with_tag(self, tag: str) -> list[dict[str, Any]]:
        await self._db.migrate()
        clean = tag.strip()
        if not clean:
            return []
        rows = await self._db.fetch_all(
            "SELECT n.item_uuid, n.rel_path, n.title FROM obsidian_import_tags t"
            " JOIN obsidian_notes n ON n.item_uuid = t.note_uuid"
            " WHERE t.tag = ? ORDER BY n.rel_path ASC LIMIT ?",
            (clean, _MAX_IMPORT_LIST),
        )
        return [
            {
                "ref": f"library:{row['item_uuid']}",
                "relPath": str(row["rel_path"]),
                "title": str(row["title"]),
            }
            for row in rows
        ]
