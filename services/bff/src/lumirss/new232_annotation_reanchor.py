"""NEW-232 失效标注重定位 —— 用户手动选择新段落重锚旧批注。

与 N071 自动修复（repair：以引文相似度驱动、repair_log cap 10）互补：
本模块是**用户显式选择**——原文更新后，用户在客户端选中新段落并
提交其定位锚点（paraId 必填，exact/prefix/suffix 可选），服务端：

1. 旧锚点 JSON 与旧摘录**先**完整写入 annotation_reanchor_log
   （append-only、不封顶——「保留旧引文与旧位置」是硬要求）；
2. 批注本体的 anchor / anchor_hash（导入幂等键）随新锚点更新；
   新 hash 与另一条批注冲突 → AnchorReanchorConflict（路由 409），
   绝不覆盖既有批注；
3. 可选携带新摘录（excerpt）一并更新；不给 → 旧摘录原样保留。

零网络依赖：锚点来自用户客户端 DOM 选区，不需要触达 FreshRSS。
per-user 库——只能重锚本人的批注（他人 id = 404）。
"""

import json
import uuid as _uuid
from typing import Any

from lumirss.annotation_store import AnnotationStore, anchor_hash
from lumirss.storage import Database
from lumirss.util import utc_now

MAX_ANCHOR_TEXT = 500  # 与 annotation_store MAX_EXCERPT 同口径


class AnchorReanchorInvalid(ValueError):
    """重锚负载非法（映射 422）。"""


class AnchorReanchorConflict(Exception):
    """新锚点与另一条既有批注冲突（映射 409）。"""


def validate_anchor(anchor: Any) -> dict[str, str]:
    """校验并归一化用户提交的新锚点：paraId 必填非空；其余字段可选
    字符串 ≤500。返回干净 dict（多余字段丢弃）。"""
    if not isinstance(anchor, dict) or not anchor:
        raise AnchorReanchorInvalid("anchor 不能为空。")
    para_id = anchor.get("paraId")
    if not isinstance(para_id, str) or para_id.strip() == "":
        raise AnchorReanchorInvalid("anchor.paraId 必填（用户选中的段落定位）。")
    cleaned = {"paraId": para_id.strip()}
    for key in ("prefix", "exact", "suffix"):
        value = anchor.get(key)
        if value is None:
            cleaned[key] = ""
            continue
        if not isinstance(value, str):
            raise AnchorReanchorInvalid(f"anchor.{key} 必须是字符串。")
        if len(value) > MAX_ANCHOR_TEXT:
            raise AnchorReanchorInvalid(f"anchor.{key} 过长（≤{MAX_ANCHOR_TEXT} 字符）。")
        cleaned[key] = value
    return cleaned


class AnnotationReanchorStore:
    def __init__(self, db: Database) -> None:
        self._db = db
        self._annotations = AnnotationStore(db)

    async def reanchor(
        self,
        annotation_id: str,
        *,
        anchor: Any,
        excerpt: str | None = None,
    ) -> dict[str, Any] | None:
        """手动重锚。旧位置/旧引文先进历史（append-only），再改本体。
        批注不存在 → None；锚点非法 → AnchorReanchorInvalid；新锚点
        与他条冲突 → AnchorReanchorConflict。"""
        new_anchor = validate_anchor(anchor)
        current = await self._annotations.get(annotation_id)
        if current is None:
            return None
        if excerpt is not None:
            if not isinstance(excerpt, str):
                raise AnchorReanchorInvalid("excerpt 必须是字符串。")
            if len(excerpt) > MAX_ANCHOR_TEXT:
                raise AnchorReanchorInvalid(
                    f"excerpt 过长（≤{MAX_ANCHOR_TEXT} 字符）。"
                )
        raw = await self._db.fetch_one(
            "SELECT anchor_json, excerpt FROM annotations WHERE id = ?",
            (annotation_id,),
        )
        old_anchor_json = str(raw["anchor_json"] or "{}") if raw is not None else "{}"
        old_excerpt = str(raw["excerpt"] or "") if raw is not None else ""

        new_hash = anchor_hash(str(current["entryRef"]), new_anchor)
        clash = await self._annotations.get_by_anchor_hash(new_hash)
        if clash is not None and clash["id"] != annotation_id:
            raise AnchorReanchorConflict("新锚点与另一条批注的锚点重复。")

        new_excerpt = old_excerpt if excerpt is None else excerpt
        now = utc_now()
        new_anchor_json = json.dumps(new_anchor, ensure_ascii=False, separators=(",", ":"))
        await self._db.execute(
            "INSERT INTO annotation_reanchor_log (id, annotation_id, old_anchor_json, old_excerpt, new_anchor_json, new_excerpt, source, reanchored_at) VALUES (?, ?, ?, ?, ?, ?, 'manual', ?)",
            (
                str(_uuid.uuid4()),
                annotation_id,
                old_anchor_json,
                old_excerpt,
                new_anchor_json,
                new_excerpt,
                now,
            ),
        )
        await self._db.execute(
            "UPDATE annotations SET anchor_json = ?, anchor_hash = ?, excerpt = ?, updated_at = ? WHERE id = ?",
            (new_anchor_json, new_hash, new_excerpt, now, annotation_id),
        )
        return await self._annotations.get(annotation_id)

    async def history(self, annotation_id: str) -> list[dict[str, Any]]:
        """重锚历史（新→旧；append-only 台账，含旧引文与旧锚点）。"""
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, old_anchor_json, old_excerpt, new_anchor_json, new_excerpt, source, reanchored_at "
            "FROM annotation_reanchor_log WHERE annotation_id = ? "
            "ORDER BY reanchored_at DESC, rowid DESC",
            (annotation_id,),
        )

        def _loads(value: Any) -> dict[str, Any]:
            try:
                parsed = json.loads(str(value or "{}"))
            except json.JSONDecodeError:
                parsed = {}
            return parsed if isinstance(parsed, dict) else {}

        return [
            {
                "id": str(row["id"]),
                "oldAnchor": _loads(row["old_anchor_json"]),
                "oldExcerpt": str(row["old_excerpt"] or ""),
                "newAnchor": _loads(row["new_anchor_json"]),
                "newExcerpt": str(row["new_excerpt"] or ""),
                "source": str(row["source"] or "manual"),
                "reanchoredAt": str(row["reanchored_at"]),
            }
            for row in rows
        ]
