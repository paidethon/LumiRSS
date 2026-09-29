"""NEW-234 个人批注层 —— 同一文章的批注按用途分层、切换、单独导出。

- 层是纯个人结构（per-user 库），命名即用途（「精读考据」「待办摘录」…）；
  默认绝不进入任何共享面——层从不改变批注的私有性。
- annotations.layer_id：NULL = 未分层（默认层，行为与分层前一致）。
- 删除层：成员批注回未分层（layer_id 置 NULL），批注本体永不随层删除。
- 单独导出：层成员按既有批注汇编格式（excerpt > 引用 + 我的批注 +
  回原文 deep link）生成 Markdown。
- 加入层：批注必须存在（per-user 库内查询，他人 id 天然 404 →
  honest skipped）。
"""

import json
import uuid as _uuid
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

MAX_LAYER_NAME = 100
_PAGE_SIZE = 200


class AnnotationLayerInvalid(ValueError):
    """层负载非法（名称空/过长），映射 422。"""


class AnnotationLayerNotFound(Exception):
    """层不存在，映射 404。"""


def _dump_row(row: Any) -> dict[str, Any]:
    try:
        anchor = json.loads(row["anchor_json"])
    except (json.JSONDecodeError, TypeError):
        anchor = {}
    layer_id = row["layer_id"] if "layer_id" in row.keys() else None  # noqa: SIM118 — sqlite3.Row.keys()
    return {
        "id": str(row["id"]),
        "entryRef": str(row["entry_ref"]),
        "anchor": anchor if isinstance(anchor, dict) else {},
        "excerpt": str(row["excerpt"] or ""),
        "note": str(row["note"] or ""),
        "color": str(row["color"]),
        "layerId": str(layer_id) if layer_id else None,
        "createdAt": str(row["created_at"]),
        "updatedAt": str(row["updated_at"]),
    }


_SELECT = (
    "SELECT id, entry_ref, anchor_json, excerpt, note, color, layer_id, created_at, updated_at "
    "FROM annotations"
)


class AnnotationLayerStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    # -- 层 CRUD ----------------------------------------------------------

    async def create(self, name: str) -> dict[str, Any]:
        await self._db.migrate()
        clean = str(name or "").strip()
        if not clean:
            raise AnnotationLayerInvalid("层名称不能为空。")
        if len(clean) > MAX_LAYER_NAME:
            raise AnnotationLayerInvalid(f"层名称过长（≤{MAX_LAYER_NAME} 字符）。")
        layer_id = str(_uuid.uuid4())
        now = utc_now()
        await self._db.execute(
            "INSERT INTO annotation_layers (id, name, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (layer_id, clean, now, now),
        )
        return {"id": layer_id, "name": clean, "createdAt": now, "itemCount": 0}

    async def list_layers(self) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT l.id, l.name, l.created_at, "
            "(SELECT COUNT(*) FROM annotations a WHERE a.layer_id = l.id) AS item_count "
            "FROM annotation_layers l ORDER BY l.created_at ASC, l.rowid ASC"
        )
        return [
            {
                "id": str(row["id"]),
                "name": str(row["name"]),
                "createdAt": str(row["created_at"]),
                "itemCount": int(row["item_count"]),
            }
            for row in rows
        ]

    async def rename(self, layer_id: str, name: str) -> dict[str, Any] | None:
        await self._db.migrate()
        clean = str(name or "").strip()
        if not clean:
            raise AnnotationLayerInvalid("层名称不能为空。")
        if len(clean) > MAX_LAYER_NAME:
            raise AnnotationLayerInvalid(f"层名称过长（≤{MAX_LAYER_NAME} 字符）。")
        row = await self._db.fetch_one(
            "SELECT id FROM annotation_layers WHERE id = ?", (layer_id,)
        )
        if row is None:
            return None
        await self._db.execute(
            "UPDATE annotation_layers SET name = ?, updated_at = ? WHERE id = ?",
            (clean, utc_now(), layer_id),
        )
        return {"id": layer_id, "name": clean}

    async def delete(self, layer_id: str) -> bool:
        """删层：成员批注回未分层（数据保留），层定义删除。"""
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id FROM annotation_layers WHERE id = ?", (layer_id,)
        )
        if row is None:
            return False
        await self._db.execute(
            "UPDATE annotations SET layer_id = NULL WHERE layer_id = ?", (layer_id,)
        )
        await self._db.execute("DELETE FROM annotation_layers WHERE id = ?", (layer_id,))
        return True

    async def layer_exists(self, layer_id: str) -> bool:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id FROM annotation_layers WHERE id = ?", (layer_id,)
        )
        return row is not None

    # -- 成员 --------------------------------------------------------------

    async def assign(self, layer_id: str, annotation_ids: list[str]) -> dict[str, Any]:
        """把既有批注加入层（幂等；未知批注 honest skipped）。"""
        if not await self.layer_exists(layer_id):
            raise AnnotationLayerNotFound(layer_id)
        added: list[str] = []
        skipped: list[dict[str, str]] = []
        for annotation_id in annotation_ids:
            row = await self._db.fetch_one(
                "SELECT layer_id FROM annotations WHERE id = ?", (str(annotation_id),)
            )
            if row is None:
                skipped.append(
                    {"annotationId": str(annotation_id), "reason": "annotation_not_found"}
                )
                continue
            if row["layer_id"] == layer_id:
                skipped.append(
                    {"annotationId": str(annotation_id), "reason": "already_in_layer"}
                )
                continue
            await self._db.execute(
                "UPDATE annotations SET layer_id = ?, updated_at = ? WHERE id = ?",
                (layer_id, utc_now(), str(annotation_id)),
            )
            added.append(str(annotation_id))
        return {"added": added, "skipped": skipped}

    async def unassign(self, layer_id: str, annotation_id: str) -> bool:
        """从层移除（批注本体保留，回未分层）。"""
        if not await self.layer_exists(layer_id):
            raise AnnotationLayerNotFound(layer_id)
        row = await self._db.fetch_one(
            "SELECT layer_id FROM annotations WHERE id = ?", (annotation_id,)
        )
        if row is None or row["layer_id"] != layer_id:
            return False
        await self._db.execute(
            "UPDATE annotations SET layer_id = NULL, updated_at = ? WHERE id = ?",
            (utc_now(), annotation_id),
        )
        return True

    async def list_annotations(self, layer_id: str) -> list[dict[str, Any]]:
        """层成员（加入顺序近似 = created_at 升序）；层不存在 → 404。"""
        if not await self.layer_exists(layer_id):
            raise AnnotationLayerNotFound(layer_id)
        rows = await self._db.fetch_all(
            f"{_SELECT} WHERE layer_id = ? ORDER BY created_at ASC, id ASC LIMIT ?",
            (layer_id, _PAGE_SIZE),
        )
        return [_dump_row(row) for row in rows]

    # -- 导出 --------------------------------------------------------------

    async def export_markdown(self, layer_id: str, *, include_notes: bool = True) -> str:
        """层成员的 Markdown 汇编（与批注导出同一要素：摘录引用、
        可选批注、回原文定位）。空层 → 诚实空汇编头。"""
        items = await self.list_annotations(layer_id)
        layers = {layer["id"]: layer["name"] for layer in await self.list_layers()}
        name = layers.get(layer_id, "")
        lines = [f"# 批注层：{name}", ""]
        if not items:
            lines.append("（该层暂无批注）")
            return "\n".join(lines) + "\n"
        from lumirss.util import utc_now as _now

        lines.append(f"导出于 {_now()} · 共 {len(items)} 条批注")
        for item in items:
            anchor = item.get("anchor") or {}
            para = str(anchor.get("paraId", "")) if isinstance(anchor, dict) else ""
            lines += [
                "",
                f"## 文章 {item['entryRef']}",
                "",
                f"[打开原文（定位段落）](/reader?entry={item['entryRef']}"
                + (f"&para={para}" if para else "")
                + ")",
                "",
                "> " + (item["excerpt"] or "（无摘录）"),
            ]
            if include_notes:
                note = item["note"]
                lines += ["", f"我的批注：{note if note else '（无批注）'}"]
        return "\n".join(lines) + "\n"
