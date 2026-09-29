"""NEW-327 笔记属性列映射 —— frontmatter 字段 → 列表可见列（可筛选）。

口径：

- 属性来自扫描投影 ``obsidian_notes.properties_json``（0250，有界：
  ≤20 键 × ≤200 字符，扫描时只读提取）——原文件格式保持不变，Lumi
  绝不回写 frontmatter；
- 可用字段 = 投影中实际出现过的属性键 + 出现次数（诚实：没出现过的
  字段列出来也是空列）；列映射由用户显式配置（展示名/可见/可筛选/
  排序位），不存在「自动发明列」；
- 筛选 = 属性精确值匹配（本地投影查询，零 Vault 访问）。

per-user：投影与列映射都在 per-user 库；投影是 owner 的 Vault 面
（路由层 owner 门槛）。
"""

import json
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

MAX_FIELD_LENGTH = 50
MAX_LABEL_LENGTH = 50
_MAX_NOTES_SCANNED = 5000
_MAX_FILTER_RESULTS = 200


class PropertyColumnInvalid(ValueError):
    """列映射输入非法（映射 400）。"""


class PropertyColumnStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def available_fields(self) -> list[dict[str, Any]]:
        """投影中出现过的属性键 + 笔记数（字典序，有界）。"""
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT properties_json FROM obsidian_notes LIMIT ?",
            (_MAX_NOTES_SCANNED,),
        )
        counts: dict[str, int] = {}
        for row in rows:
            try:
                properties = json.loads(str(row["properties_json"] or "{}"))
            except json.JSONDecodeError:
                continue
            if not isinstance(properties, dict):
                continue
            for key in properties:
                counts[str(key)] = counts.get(str(key), 0) + 1
        return [
            {"field": field, "noteCount": count}
            for field, count in sorted(counts.items())
        ]

    async def list_columns(self) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT field, label, visible, filterable, position, updated_at"
            " FROM obsidian_property_columns ORDER BY position ASC, field ASC LIMIT 100"
        )
        return [
            {
                "field": str(row["field"]),
                "label": str(row["label"]),
                "visible": bool(row["visible"]),
                "filterable": bool(row["filterable"]),
                "position": int(row["position"]),
                "updatedAt": str(row["updated_at"]),
            }
            for row in rows
        ]

    async def put_column(
        self,
        field: str,
        *,
        label: str = "",
        visible: bool = True,
        filterable: bool = False,
        position: int = 0,
    ) -> dict[str, Any]:
        clean_field = str(field or "").strip()[:MAX_FIELD_LENGTH]
        if not clean_field:
            raise PropertyColumnInvalid("field 不能为空。")
        clean_label = str(label or "").strip()[:MAX_LABEL_LENGTH]
        if not isinstance(position, int) or position < 0 or position > 999:
            raise PropertyColumnInvalid("position 必须是 0-999 的整数。")
        now = utc_now()
        await self._db.migrate()
        await self._db.execute(
            "INSERT INTO obsidian_property_columns (field, label, visible, filterable, position, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(field) DO UPDATE SET label = excluded.label,"
            " visible = excluded.visible, filterable = excluded.filterable,"
            " position = excluded.position, updated_at = excluded.updated_at",
            (
                clean_field,
                clean_label,
                1 if visible else 0,
                1 if filterable else 0,
                position,
                now,
            ),
        )
        return {
            "field": clean_field,
            "label": clean_label,
            "visible": visible,
            "filterable": filterable,
            "position": position,
            "updatedAt": now,
        }

    async def delete_column(self, field: str) -> bool:
        clean_field = str(field or "").strip()[:MAX_FIELD_LENGTH]
        if not clean_field:
            raise PropertyColumnInvalid("field 不能为空。")
        await self._db.migrate()
        deleted = await self._db.execute(
            "DELETE FROM obsidian_property_columns WHERE field = ?",
            (clean_field,),
        )
        return bool(deleted)

    async def filtered_notes(self, field: str, value: str) -> dict[str, Any]:
        """按属性精确值筛选笔记，返回（可见列名 + 命中笔记含属性）。"""
        clean_field = str(field or "").strip()
        if not clean_field:
            raise PropertyColumnInvalid("field 不能为空。")
        await self._db.migrate()
        columns = {
            column["field"]: column
            for column in await self.list_columns()
            if column["visible"]
        }
        rows = await self._db.fetch_all(
            "SELECT item_uuid, rel_path, title, tags, truncated, indexed_at, properties_json"
            " FROM obsidian_notes ORDER BY rel_path ASC LIMIT ?",
            (_MAX_NOTES_SCANNED,),
        )
        hits: list[dict[str, Any]] = []
        wanted = str(value or "").strip()
        for row in rows:
            try:
                properties = json.loads(str(row["properties_json"] or "{}"))
            except json.JSONDecodeError:
                properties = {}
            if not isinstance(properties, dict):
                continue
            if str(properties.get(clean_field, "")).strip() != wanted:
                continue
            hits.append(
                {
                    "ref": f"library:{row['item_uuid']}",
                    "relPath": str(row["rel_path"]),
                    "title": str(row["title"]),
                    "tags": json.loads(str(row["tags"] or "[]")),
                    "truncated": bool(row["truncated"]),
                    "indexedAt": str(row["indexed_at"]),
                    "properties": properties,
                }
            )
            if len(hits) >= _MAX_FILTER_RESULTS:
                break
        return {
            "field": clean_field,
            "value": wanted,
            "columns": [columns[key] for key in sorted(columns)],
            "notes": hits,
            "truncated": len(hits) >= _MAX_FILTER_RESULTS,
            "honestyNote": "筛选作用于只读投影；原文件 frontmatter 未被修改。",
        }
