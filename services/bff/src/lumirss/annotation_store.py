"""F051 批注服务端化 — annotations 真源 CRUD + 跨篇检索 + 导入幂等。

- excerpt ≤500、note ≤2000（应用层限额，超限截断/拒绝在路由层）；
- anchor_hash UNIQUE 承载「localStorage 存量导入」幂等：同一锚点重复
  导入返回既有行，不产生副本；
- 跨篇检索：excerpt/note LIKE（CJK 直接 LIKE 命中，绑定参数防注入），
  keyset 分页（updated_at + id 为游标，稳定且 opaque）。

N137 增量批注导出：annotation_export_log 追加日志承载导出水位
（MAX(exported_at)）；delta = updated_at > 水位，按 created_at 区分
「新增 / 修改」。mark 可重复调用（幂等：只追加日志行，水位只前进，
不会重复计数）。
"""

import hashlib
import json
import uuid as _uuid
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

MAX_EXCERPT = 500
MAX_NOTE = 2000
COLORS = ("yellow", "green", "blue", "red", "purple")
_PAGE_SIZE = 50


class AnnotationInvalid(ValueError):
    """批注负载未通过校验。"""


def anchor_hash(entry_ref: str, anchor: dict[str, Any]) -> str:
    """锚点指纹：entry_ref + 归一化 anchor JSON 的 SHA-256（导入幂等键）。"""
    canonical = json.dumps(anchor, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(f"{entry_ref}|{canonical}".encode()).hexdigest()[:32]


def _clean_text(value: Any, limit: int, label: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise AnnotationInvalid(f"{label} 必须是字符串。")
    if len(value) > limit:
        raise AnnotationInvalid(f"{label} 过长（≤{limit} 字符）。")
    return value


class AnnotationStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self,
        *,
        entry_ref: str,
        anchor: dict[str, Any],
        excerpt: str | None,
        note: str | None,
        color: str = "yellow",
    ) -> dict[str, Any]:
        await self._db.migrate()
        if not isinstance(entry_ref, str) or not entry_ref.strip():
            raise AnnotationInvalid("entryRef 不能为空。")
        if not isinstance(anchor, dict) or not anchor:
            raise AnnotationInvalid("anchor 不能为空。")
        if color not in COLORS:
            raise AnnotationInvalid("color 非法。")
        clean_excerpt = _clean_text(excerpt, MAX_EXCERPT, "excerpt")
        clean_note = _clean_text(note, MAX_NOTE, "note")
        row_hash = anchor_hash(entry_ref, anchor)
        existing = await self.get_by_anchor_hash(row_hash)
        if existing is not None:
            return existing  # 导入幂等：同锚点不再新建
        annotation_id = str(_uuid.uuid4())
        now = utc_now()
        await self._db.execute(
            "INSERT INTO annotations (id, entry_ref, anchor_json, anchor_hash, excerpt, note, color, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                annotation_id,
                entry_ref,
                json.dumps(anchor, ensure_ascii=False, separators=(",", ":")),
                row_hash,
                clean_excerpt,
                clean_note,
                color,
                now,
                now,
            ),
        )
        return (await self.get(annotation_id))  # type: ignore[return-value]

    async def get(self, annotation_id: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, entry_ref, anchor_json, anchor_hash, excerpt, note, color, created_at, updated_at FROM annotations WHERE id = ?",
            (annotation_id,),
        )
        return _row_to_dict(row) if row is not None else None

    async def get_by_anchor_hash(self, row_hash: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, entry_ref, anchor_json, anchor_hash, excerpt, note, color, created_at, updated_at FROM annotations WHERE anchor_hash = ?",
            (row_hash,),
        )
        return _row_to_dict(row) if row is not None else None

    async def list_for_entry(
        self, entry_ref: str, *, updated_after: str | None = None
    ) -> list[dict[str, Any]]:
        """一篇文章的全部批注；``updated_after``（N137 增量导出）时只返回
        updated_at 严格晚于该水位的批注。"""
        await self._db.migrate()
        if updated_after is not None:
            rows = await self._db.fetch_all(
                "SELECT id, entry_ref, anchor_json, anchor_hash, excerpt, note, color, created_at, updated_at FROM annotations WHERE entry_ref = ? AND updated_at > ? ORDER BY created_at ASC, id ASC",
                (entry_ref, updated_after),
            )
        else:
            rows = await self._db.fetch_all(
                "SELECT id, entry_ref, anchor_json, anchor_hash, excerpt, note, color, created_at, updated_at FROM annotations WHERE entry_ref = ? ORDER BY created_at ASC, id ASC",
                (entry_ref,),
            )
        return [_row_to_dict(row) for row in rows]

    async def search(
        self, q: str | None = None, after: tuple[str, str] | None = None
    ) -> tuple[list[dict[str, Any]], str | None]:
        """跨篇检索（q 可选 LIKE）；keyset 分页，返回 (items, nextCursor)。"""
        await self._db.migrate()
        params: list[Any] = []
        where = "WHERE 1=1"
        if q:
            where += " AND (excerpt LIKE ? OR note LIKE ?)"
            like = f"%{q}%"
            params.extend([like, like])
        if after is not None:
            where += " AND (updated_at < ? OR (updated_at = ? AND id < ?))"
            params.extend([after[0], after[0], after[1]])
        params.append(_PAGE_SIZE + 1)
        rows = await self._db.fetch_all(
            f"SELECT id, entry_ref, anchor_json, anchor_hash, excerpt, note, color, created_at, updated_at FROM annotations {where} ORDER BY updated_at DESC, id DESC LIMIT ?",
            tuple(params),
        )
        items = [_row_to_dict(row) for row in rows[:_PAGE_SIZE]]
        next_cursor = None
        if len(rows) > _PAGE_SIZE and items:
            last = items[-1]
            next_cursor = f"{last['updatedAt']}|{last['id']}"
        return items, next_cursor

    async def search_bounded(
        self, q: str, *, limit: int = 10
    ) -> tuple[list[dict[str, Any]], bool]:
        """N149 主题演变时间线：本人批注按 excerpt/note LIKE 检索，
        硬上限 limit；命中超过上限 → (前 limit 条, False) 诚实截断。

        与 search() 同一 LIKE 口径（批注检索的既有行为）；annotations
        表在 per-user 库中，只可能是本人批注——他人批注天然不可见。"""
        await self._db.migrate()
        like = f"%{q}%"
        rows = await self._db.fetch_all(
            "SELECT id, entry_ref, anchor_json, anchor_hash, excerpt, note, color, created_at, updated_at FROM annotations WHERE excerpt LIKE ? OR note LIKE ? ORDER BY updated_at DESC, id DESC LIMIT ?",
            (like, like, max(1, limit) + 1),
        )
        complete = len(rows) <= limit
        return [_row_to_dict(row) for row in rows[:limit]], complete

    async def update(
        self,
        annotation_id: str,
        *,
        note: str | None = None,
        color: str | None = None,
        excerpt: str | None = None,
    ) -> dict[str, Any] | None:
        await self._db.migrate()
        current = await self.get(annotation_id)
        if current is None:
            return None
        clean_note = current["note"] if note is None else _clean_text(note, MAX_NOTE, "note")
        clean_excerpt = (
            current["excerpt"] if excerpt is None else _clean_text(excerpt, MAX_EXCERPT, "excerpt")
        )
        clean_color = current["color"] if color is None else color
        if clean_color not in COLORS:
            raise AnnotationInvalid("color 非法。")
        await self._db.execute(
            "UPDATE annotations SET note = ?, excerpt = ?, color = ?, updated_at = ? WHERE id = ?",
            (clean_note, clean_excerpt, clean_color, utc_now(), annotation_id),
        )
        return await self.get(annotation_id)

    async def delete(self, annotation_id: str) -> bool:
        await self._db.migrate()
        current = await self.get(annotation_id)
        if current is None:
            return False
        await self._db.execute("DELETE FROM annotations WHERE id = ?", (annotation_id,))
        # F058 级联：批注删除 → 复习队列项删除
        await self._db.execute(
            "DELETE FROM review_queue WHERE annotation_id = ?", (annotation_id,)
        )
        return True

    # ------------------------------------------------------------------
    # N137 增量批注导出：导出水位（annotation_export_log 追加日志）。
    # ------------------------------------------------------------------

    async def mark_exported(self, ids: list[str]) -> dict[str, Any]:
        """记录一次成功导出（水位前进）。幂等：重复 mark 只追加日志行，
        水位取 MAX(exported_at)，增量查询按时间比较、不会重复计数。
        未知 id 静默跳过（诚实计数只含实际存在的批注）。"""
        await self._db.migrate()
        found: list[dict[str, Any]] = []
        for annotation_id in ids:
            item = await self.get(str(annotation_id))
            if item is not None:
                found.append(item)
        entry_refs = sorted({item["entryRef"] for item in found})
        exported_at = utc_now()
        await self._db.execute(
            "INSERT INTO annotation_export_log (exported_at, entry_refs_json, count) VALUES (?, ?, ?)",
            (
                exported_at,
                json.dumps(entry_refs, ensure_ascii=False),
                len(found),
            ),
        )
        return {
            "exportedAt": exported_at,
            "count": len(found),
            "entryRefs": entry_refs,
            "ids": [item["id"] for item in found],
        }

    async def last_export_watermark(self) -> str | None:
        """导出水位 = MAX(exported_at)；从未导出 → None（全量视为新增）。"""
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT MAX(exported_at) AS watermark FROM annotation_export_log"
        )
        value = row["watermark"] if row is not None else None
        return str(value) if value else None

    async def export_delta(
        self, *, entry_ref: str | None = None
    ) -> dict[str, Any]:
        """增量预览：水位之后 updated_at 有变化的批注。

        新增 = created_at > 水位（或从未导出 → 全部为新增）；修改 =
        updated_at > 水位但创建于水位之前。可选 entryRef 收窄到单篇
        （导出对话框按文章预览）。"""
        await self._db.migrate()
        watermark = await self.last_export_watermark()
        params: list[Any] = []
        where = "WHERE 1=1"
        if watermark is not None:
            where += " AND updated_at > ?"
            params.append(watermark)
        if entry_ref:
            where += " AND entry_ref = ?"
            params.append(entry_ref)
        rows = await self._db.fetch_all(
            f"SELECT created_at, updated_at FROM annotations {where}",
            tuple(params),
        )
        added = 0
        modified = 0
        for row in rows:
            created_at = str(row["created_at"] or "")
            if watermark is None or created_at > watermark:
                added += 1
            else:
                modified += 1
        return {
            "lastExportedAt": watermark,
            "addedCount": added,
            "modifiedCount": modified,
            "total": added + modified,
        }


def _row_to_dict(row: Any) -> dict[str, Any]:
    try:
        anchor = json.loads(row["anchor_json"])
    except (json.JSONDecodeError, TypeError):
        anchor = {}
    return {
        "id": str(row["id"]),
        "entryRef": str(row["entry_ref"]),
        "anchor": anchor if isinstance(anchor, dict) else {},
        "anchorHash": str(row["anchor_hash"]),
        "excerpt": str(row["excerpt"] or ""),
        "note": str(row["note"] or ""),
        "color": str(row["color"]),
        "createdAt": str(row["created_at"]),
        "updatedAt": str(row["updated_at"]),
    }
