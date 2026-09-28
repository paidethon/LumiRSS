"""NEW-238 标注批量迁移 —— 指定标注从一个个人集合（层）迁入另一个。

- 集合 = NEW-234 的个人批注层（fromLayerId 可为 null = 未分层）。
- 预览（零写入）：解析成员集（显式 annotationIds ∩ 来源集合；缺省
  = 来源集合全体），逐条展示 [摘录/颜色] 与标签变化
  （fromLayer 名 → toLayer 名）。
- 应用：逐条把 layer_id 改为目标层。**绝不触碰 entry_ref / anchor /
  正文**——原文章身份不变；已在目标的条目 honest skipped。
"""

import json
from typing import Any

from lumirss.new234_annotation_layers import AnnotationLayerStore
from lumirss.storage import Database
from lumirss.util import utc_now


class LayerMigrationInvalid(ValueError):
    """迁移负载非法（同层/空集/层缺失），映射 422 或 404（层缺失）。"""


class LayerMigrationNotFound(Exception):
    """来源层或目标层不存在，映射 404。"""


def _row_to_item(row: Any) -> dict[str, Any]:
    try:
        anchor = json.loads(row["anchor_json"])
    except (json.JSONDecodeError, TypeError):
        anchor = {}
    return {
        "id": str(row["id"]),
        "entryRef": str(row["entry_ref"]),
        "excerpt": str(row["excerpt"] or ""),
        "note": str(row["note"] or ""),
        "color": str(row["color"]),
        "anchor": anchor if isinstance(anchor, dict) else {},
    }


async def _resolve_members(
    db: Database, from_layer_id: str | None, annotation_ids: list[str] | None
) -> list[dict[str, Any]]:
    """来源集合成员：显式 ids ∩ 来源集合；ids 缺省 = 来源集合全体。
    来源集合 = layer_id 匹配（from None → 未分层 IS NULL）。"""
    if from_layer_id is None:
        where = "layer_id IS NULL"
        params: list[Any] = []
    else:
        where = "layer_id = ?"
        params = [from_layer_id]
    if annotation_ids is not None:
        placeholders = ",".join("?" for _ in annotation_ids)
        where += f" AND id IN ({placeholders})"
        params.extend(str(i) for i in annotation_ids)
    rows = await db.fetch_all(
        f"SELECT id, entry_ref, anchor_json, excerpt, note, color FROM annotations WHERE {where} "
        "ORDER BY created_at ASC, id ASC",
        tuple(params),
    )
    return [_row_to_item(row) for row in rows]


async def preview_migration(
    db: Database,
    layers: AnnotationLayerStore,
    *,
    from_layer_id: str | None,
    to_layer_id: str,
    annotation_ids: list[str] | None,
) -> dict[str, Any]:
    """预览（零写入）。from == to → 422；目标层缺失 / 显式来源层缺失
    → 404；成员空 → 422（没有可迁移的标注）。"""
    if from_layer_id is not None and not await layers.layer_exists(from_layer_id):
        raise LayerMigrationNotFound("fromLayerId")
    if not await layers.layer_exists(to_layer_id):
        raise LayerMigrationNotFound("toLayerId")
    if from_layer_id == to_layer_id:
        raise LayerMigrationInvalid("fromLayerId 与 toLayerId 不能相同。")
    members = await _resolve_members(db, from_layer_id, annotation_ids)
    if not members:
        raise LayerMigrationInvalid("来源集合中没有可迁移的标注。")
    all_layers = {layer["id"]: layer["name"] for layer in await layers.list_layers()}
    from_name = all_layers.get(from_layer_id) if from_layer_id else None
    to_name = all_layers.get(to_layer_id, "")
    items = [
        {
            "annotationId": member["id"],
            "entryRef": member["entryRef"],
            "excerpt": member["excerpt"],
            "color": member["color"],
            "fromLayer": from_name,
            "toLayer": to_name,
        }
        for member in members
    ]
    return {
        "fromLayerId": from_layer_id,
        "toLayerId": to_layer_id,
        "fromLayer": from_name,
        "toLayer": to_name,
        "items": items,
        "count": len(items),
    }


async def apply_migration(
    db: Database,
    layers: AnnotationLayerStore,
    *,
    from_layer_id: str | None,
    to_layer_id: str,
    annotation_ids: list[str] | None,
) -> dict[str, Any]:
    """应用迁移：成员逐条改层（layer_id → 目标）。文章身份字段
    （entry_ref/anchor）零改动。返回 moved/skipped。"""
    preview = await preview_migration(
        db,
        layers,
        from_layer_id=from_layer_id,
        to_layer_id=to_layer_id,
        annotation_ids=annotation_ids,
    )
    now = utc_now()
    moved: list[str] = []
    for item in preview["items"]:
        await db.execute(
            "UPDATE annotations SET layer_id = ?, updated_at = ? WHERE id = ?",
            (to_layer_id, now, item["annotationId"]),
        )
        moved.append(item["annotationId"])
    return {
        "moved": moved,
        "skipped": [],
        "toLayer": preview["toLayer"],
        "count": len(moved),
    }
