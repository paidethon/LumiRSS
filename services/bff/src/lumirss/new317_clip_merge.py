"""NEW-317 剪藏重复合并 —— 同页多次剪藏保留版本与选段，用户选择。

- 「同页」判定用 url_normalize.normalize_content_url（保守归一化：host
  小写、折一个尾斜杠、丢追踪参数、签名参数绝不丢）——与 F018 相同
  链接聚合同一口径；组内不足两条不构成候选；
- 预览零写入：分组列出每条的 URL/标题/创建时间，用户挑保留侧；
- 合并（显式 POST）：把被并入剪藏的选区包（NEW-312 selections 的
  clip_item_uuid）重指向保留侧（选段保留），修订版本（revised_*）
  在保留侧没有修订时迁移过去（版本保留），元数据按 meta_policy：
  kept=保留侧标题；newest=组内最新剪藏的标题/byline；被并入侧走
  F019 软删（回收站可见、可恢复原始行）；原始 content_html 永不
  互相覆盖；
- 不属于同一归一化组 / 引用不存在 → 422/404（绝不静默收敛）。
  合并台账（clip_duplicate_merges）只追加，供审计。

per-user：分组、合并、台账都在 per-user 库；A 的剪藏对 B 不可见，
B 无法把 A 的剪藏并进自己的组。
"""

import json
import uuid as _uuid
from typing import Any

from lumirss.library_clips import ClipNotFound
from lumirss.search_library import delete_search_row
from lumirss.storage import Database
from lumirss.url_normalize import normalize_content_url
from lumirss.util import utc_now

_GROUP_SCAN_LIMIT = 500
_MAX_MERGE_REFS = 20

_META_POLICIES = ("kept", "newest")


class ClipMergeInvalid(ValueError):
    """合并请求非法（映射 422）。"""


class ClipMergeStore:
    """重复合并：分组预览 + 显式合并（per-user）。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def list_groups(self) -> dict[str, Any]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT c.item_uuid, c.url, c.title, c.content_text, c.created_at"
            " FROM library_clips c"
            " WHERE NOT EXISTS (SELECT 1 FROM library_items i WHERE i.uuid = c.item_uuid AND i.deleted_at IS NOT NULL)"
            " ORDER BY c.created_at ASC LIMIT ?",
            (_GROUP_SCAN_LIMIT,),
        )
        groups: dict[str, list[dict[str, Any]]] = {}
        order: list[str] = []
        for row in rows:
            key = normalize_content_url(str(row["url"])) or str(row["url"])
            if key not in groups:
                groups[key] = []
                order.append(key)
            groups[key].append(
                {
                    "ref": f"library:{row['item_uuid']}",
                    "url": str(row["url"]),
                    "title": str(row["title"]),
                    "textChars": len(str(row["content_text"])),
                    "createdAt": str(row["created_at"]),
                }
            )
        duplicates = [
            {
                "key": key,
                "items": groups[key],
            }
            for key in order
            if len(groups[key]) > 1
        ]
        return {
            "groups": duplicates,
            "groupCount": len(duplicates),
            "honestyNote": (
                "分组只做保守归一化（追踪参数/scheme/尾斜杠）；"
                "预览零写入，合并由你显式确认。"
            ),
        }

    async def merge(
        self, keep_ref: Any, merge_refs: Any, meta_policy: Any
    ) -> dict[str, Any]:
        if meta_policy not in _META_POLICIES:
            raise ClipMergeInvalid(
                f"metaPolicy 必须是 {'、'.join(_META_POLICIES)} 之一。"
            )
        if not isinstance(keep_ref, str) or not keep_ref.startswith("library:"):
            raise ClipMergeInvalid("keepRef 必须是 library:<uuid> 形式。")
        if not isinstance(merge_refs, list) or not merge_refs:
            raise ClipMergeInvalid("mergeRefs 不能为空。")
        if len(merge_refs) > _MAX_MERGE_REFS:
            raise ClipMergeInvalid(f"一次最多并入 {_MAX_MERGE_REFS} 条。")
        keep_uuid = keep_ref.split(":", 1)[1]
        merge_uuids: list[str] = []
        for ref in merge_refs:
            if not isinstance(ref, str) or not ref.startswith("library:"):
                raise ClipMergeInvalid("mergeRefs 必须是 library:<uuid> 形式。")
            uuid_ = ref.split(":", 1)[1]
            if uuid_ == keep_uuid:
                raise ClipMergeInvalid("保留侧不能同时出现在 mergeRefs 里。")
            merge_uuids.append(uuid_)

        kept = await self._clip_row(keep_uuid)
        if kept is None:
            raise ClipNotFound()
        merged_rows: dict[str, Any] = {}
        for uuid_ in merge_uuids:
            row = await self._clip_row(uuid_)
            if row is None:
                raise ClipNotFound()
            merged_rows[uuid_] = row

        # 同一归一化组才允许合并（保守归一化，防止错并不同文章）
        kept_key = normalize_content_url(str(kept["url"])) or str(kept["url"])
        for row in merged_rows.values():
            row_key = normalize_content_url(str(row["url"])) or str(row["url"])
            if row_key != kept_key:
                raise ClipMergeInvalid(
                    "mergeRefs 里有与保留侧不同页的剪藏（归一化后不同组），拒绝合并。"
                )

        now = utc_now()
        carried_selections = 0
        carried_revision = 0
        newest = max(
            merged_rows.values(), key=lambda r: str(r["created_at"])
        )

        def _tx(conn: Any) -> None:
            nonlocal carried_selections, carried_revision
            for uuid_ in merge_uuids:
                row = merged_rows[uuid_]
                # 选段保留：选区包重指向保留侧
                cursor = conn.execute(
                    "UPDATE clip_selections SET clip_item_uuid = ? WHERE clip_item_uuid = ?",
                    (keep_uuid, uuid_),
                )
                carried_selections += cursor.rowcount
                # 版本保留：保留侧没有修订时迁移被并入侧的修订槽
                if kept["revised_content_html"] is None and row["revised_content_html"]:
                    conn.execute(
                        "UPDATE library_clips SET revised_content_html = ?, revised_note = ?, revised_at = ?"
                        " WHERE item_uuid = ? AND revised_content_html IS NULL",
                        (
                            row["revised_content_html"],
                            row["revised_note"],
                            row["revised_at"],
                            keep_uuid,
                        ),
                    )
                    carried_revision += 1
                # 元数据按用户选择
            if meta_policy == "newest" and newest["item_uuid"] != keep_uuid:
                conn.execute(
                    "UPDATE library_clips SET title = ?, byline = ? WHERE item_uuid = ?",
                    (newest["title"], newest["byline"], keep_uuid),
                )
            # 被并入侧：F019 软删 + 搜索投影下线（原始行可从回收站恢复）
            for uuid_ in merge_uuids:
                conn.execute(
                    "UPDATE library_items SET deleted_at = ? WHERE uuid = ? AND kind = 'clip' AND deleted_at IS NULL",
                    (now, uuid_),
                )
                delete_search_row(conn, f"library:{uuid_}")
            conn.execute(
                "INSERT INTO clip_duplicate_merges (id, kept_item_uuid, merged_item_uuids_json, meta_policy, carried_selections, carried_revision, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    str(_uuid.uuid4()), keep_uuid,
                    json.dumps(merge_uuids, ensure_ascii=False), meta_policy,
                    carried_selections, carried_revision, now,
                ),
            )

        from lumirss.db_tx import transaction

        await transaction(self._db, _tx)
        return {
            "keptRef": keep_ref,
            "mergedRefs": list(merge_uuids),
            "metaPolicy": meta_policy,
            "carriedSelections": carried_selections,
            "carriedRevision": carried_revision,
            "mergedAt": now,
        }

    async def list_merges(self) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, kept_item_uuid, merged_item_uuids_json, meta_policy, carried_selections, carried_revision, created_at"
            " FROM clip_duplicate_merges ORDER BY created_at DESC LIMIT 100"
        )
        result: list[dict[str, Any]] = []
        for row in rows:
            try:
                merged = json.loads(str(row["merged_item_uuids_json"]))
            except json.JSONDecodeError:
                merged = []
            result.append(
                {
                    "id": str(row["id"]),
                    "keptRef": f"library:{row['kept_item_uuid']}",
                    "mergedRefs": merged if isinstance(merged, list) else [],
                    "metaPolicy": str(row["meta_policy"]),
                    "carriedSelections": int(row["carried_selections"]),
                    "carriedRevision": int(row["carried_revision"]),
                    "createdAt": str(row["created_at"]),
                }
            )
        return result

    async def _clip_row(self, item_uuid: str) -> Any:
        await self._db.migrate()
        return await self._db.fetch_one(
            "SELECT item_uuid, url, title, byline, content_html, content_text, revised_content_html, revised_note, revised_at, created_at"
            " FROM library_clips WHERE item_uuid = ?",
            (item_uuid,),
        )


__all__ = ["ClipMergeInvalid", "ClipMergeStore", "ClipNotFound"]
