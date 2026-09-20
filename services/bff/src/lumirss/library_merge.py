"""F082 重复资料合并 —— 单事务内字段级合并 + duplicate 软删。

固定语义（规格）：
- tags 并集；workspace 采用 primary 的成员关系（duplicate 的成员行移除）；
- title/note 按 policy（primary | duplicate；note append = 拼接去重）；
- 资产引用重指到 primary（schema 每条目至多 1 资产：两者都有 → 删除
  duplicate 的资产行并移除其文件，绝不留孤立资产）；
- 批注（annotations）重挂到 primary ref；
- duplicate 软删（library_items.deleted_at → 回收站），item_relations
  以 kind='merged' 记录映射（primary → duplicate）；
- 任何步骤失败整体回滚（单事务）；已 merged 的对再次请求 → 409
  merged_already；
- FreshRSS 条目与 Obsidian Vault 不变（本模块零接触）。

本文件直接写站点 6 处（均在同一事务闭包内：tags 迁移 1、资产重指 1、
资产删除 1、批注重挂 1、成员/关系/软删 3）——超过单文件 4 站点约定，
故把「主事务」拆到本文件唯一一个 transaction() 闭包内，闭包内多条
语句按既有惯例（library.py `_tx` 同形）合并计数为该站点的局部事务。
"""

import os
import sqlite3
from typing import Any

from lumirss.db_tx import transaction
from lumirss.itemref import LIBRARY_DOMAIN, parse_item_ref
from lumirss.search_library import delete_search_row
from lumirss.storage import Database
from lumirss.util import utc_now


class MergeInvalid(ValueError):
    """合并请求非法（自合并/引用不存在/域不支持），映射 422。"""


class MergedAlready(Exception):
    """该对已经合并过（duplicate 已软删或存在 merged 映射），映射 409。"""


def _normalize_ref(ref: str) -> str:
    try:
        return parse_item_ref(ref).format()
    except ValueError as exc:
        raise MergeInvalid(str(exc)) from exc


class LibraryMergeService:
    def __init__(self, db: Database, tag_store: Any) -> None:
        self._db = db
        self._tags = tag_store

    # -- 读取对照 -----------------------------------------------------------

    async def _payload(self, item_uuid: str) -> dict[str, Any] | None:
        row = await self._db.fetch_one(
            "SELECT kind, deleted_at FROM library_items WHERE uuid = ?",
            (item_uuid,),
        )
        if row is None:
            return None
        kind = str(row["kind"])
        title: str | None = None
        note: str | None = None
        url: str | None = None
        if kind == "bookmark":
            row_b = await self._db.fetch_one(
                "SELECT title, note, url FROM library_bookmarks WHERE item_uuid = ?",
                (item_uuid,),
            )
            if row_b is None:
                return None
            title, note, url = (
                str(row_b["title"]),
                str(row_b["note"] or ""),
                row_b["url"],
            )
        elif kind == "clip":
            row_c = await self._db.fetch_one(
                "SELECT title, url FROM library_clips WHERE item_uuid = ?",
                (item_uuid,),
            )
            if row_c is None:
                return None
            title, note, url = str(row_c["title"]), "", row_c["url"]
        else:
            return None
        tags = [
            str(t["name"])
            for t in await self._tags.tags_for_item(f"{LIBRARY_DOMAIN}:{item_uuid}")
        ]
        workspaces = [
            str(r["workspace_id"])
            for r in await self._db.fetch_all(
                "SELECT workspace_id FROM workspace_items WHERE item_ref = ?",
                (f"{LIBRARY_DOMAIN}:{item_uuid}",),
            )
        ]
        asset = await self._db.fetch_one(
            "SELECT uuid FROM library_assets WHERE item_uuid = ?", (item_uuid,)
        )
        annotation_count = int(
            (
                await self._db.fetch_one(
                    "SELECT COUNT(*) AS n FROM annotations WHERE entry_ref = ?",
                    (f"{LIBRARY_DOMAIN}:{item_uuid}",),
                )
            )["n"]
        )
        return {
            "uuid": item_uuid,
            "kind": kind,
            "deleted": row["deleted_at"] is not None,
            "title": title or "",
            "note": note or "",
            "url": url,
            "tags": tags,
            "workspaceIds": workspaces,
            "assetUuid": str(asset["uuid"]) if asset is not None else None,
            "annotationCount": annotation_count,
        }

    async def _merged_mapping_exists(self, primary: str, duplicate: str) -> bool:
        row = await self._db.fetch_one(
            "SELECT id FROM item_relations WHERE src_ref = ? AND dst_ref = ? AND kind = 'merged'",
            (primary, duplicate),
        )
        return row is not None

    async def preview(
        self, primary_ref: str, duplicate_ref: str
    ) -> dict[str, Any]:
        primary = await self._payload(
            _normalize_ref(primary_ref).removeprefix(f"{LIBRARY_DOMAIN}:")
        )
        duplicate = await self._payload(
            _normalize_ref(duplicate_ref).removeprefix(f"{LIBRARY_DOMAIN}:")
        )
        if primary is None or duplicate is None:
            raise MergeInvalid("待合并条目不存在或类型不支持。")
        if primary["uuid"] == duplicate["uuid"]:
            raise MergeInvalid("条目不能与自身合并。")
        if primary["deleted"] or duplicate["deleted"]:
            raise MergedAlready("条目已在回收站（可能已合并）。")
        if await self._merged_mapping_exists(
            f"{LIBRARY_DOMAIN}:{primary['uuid']}",
            f"{LIBRARY_DOMAIN}:{duplicate['uuid']}",
        ):
            raise MergedAlready("该对已合并。")
        fields = [
            {"field": "title", "primary": primary["title"], "duplicate": duplicate["title"]},
            {"field": "url", "primary": primary["url"], "duplicate": duplicate["url"]},
            {"field": "note", "primary": primary["note"], "duplicate": duplicate["note"]},
            {"field": "tags", "primary": primary["tags"], "duplicate": duplicate["tags"]},
            {
                "field": "workspace",
                "primary": primary["workspaceIds"],
                "duplicate": duplicate["workspaceIds"],
            },
            {
                "field": "asset",
                "primary": primary["assetUuid"],
                "duplicate": duplicate["assetUuid"],
            },
            {
                "field": "annotations",
                "primary": primary["annotationCount"],
                "duplicate": duplicate["annotationCount"],
            },
        ]
        return {
            "primaryRef": f"{LIBRARY_DOMAIN}:{primary['uuid']}",
            "duplicateRef": f"{LIBRARY_DOMAIN}:{duplicate['uuid']}",
            "fields": fields,
            "annotationCount": duplicate["annotationCount"],
            "assetUuids": [
                u
                for u in (primary["assetUuid"], duplicate["assetUuid"])
                if u is not None
            ],
        }

    # -- 合并（单事务） -------------------------------------------------------

    async def merge(
        self,
        primary_ref: str,
        duplicate_ref: str,
        *,
        title_policy: str,
        note_policy: str,
    ) -> dict[str, Any]:
        if title_policy not in ("primary", "duplicate"):
            raise MergeInvalid("title policy 必须是 primary|duplicate。")
        if note_policy not in ("primary", "append"):
            raise MergeInvalid("note policy 必须是 primary|append。")
        state = await self.preview(primary_ref, duplicate_ref)
        p_uuid = state["primaryRef"].removeprefix(f"{LIBRARY_DOMAIN}:")
        d_uuid = state["duplicateRef"].removeprefix(f"{LIBRARY_DOMAIN}:")
        primary = await self._payload(p_uuid)
        duplicate = await self._payload(d_uuid)
        assert primary is not None and duplicate is not None  # preview 已校验
        now = utc_now()
        p_ref, d_ref = state["primaryRef"], state["duplicateRef"]

        # 字段合成（在事务外计算，事务内纯写）。
        merged_title = (
            primary["title"]
            if title_policy == "primary"
            else duplicate["title"]
        )
        if note_policy == "append":
            merged_note = (
                primary["note"]
                if not duplicate["note"]
                else (
                    duplicate["note"]
                    if not primary["note"]
                    else primary["note"].rstrip() + "\n\n" + duplicate["note"]
                )
            )
        else:
            merged_note = primary["note"]
        tags_union = list(dict.fromkeys(primary["tags"] + duplicate["tags"]))

        dup_asset_row = await self._db.fetch_one(
            "SELECT uuid, path FROM library_assets WHERE item_uuid = ?", (d_uuid,)
        )
        dup_asset_path = (
            str(dup_asset_row["path"]) if dup_asset_row is not None else None
        )

        def _tx(conn: sqlite3.Connection) -> None:
            # 1) title/note 按类型落 primary 的 payload 表
            if primary["kind"] == "bookmark":
                conn.execute(
                    "UPDATE library_bookmarks SET title = ?, note = ? WHERE item_uuid = ?",
                    (merged_title, merged_note, p_uuid),
                )
            else:
                conn.execute(
                    "UPDATE library_clips SET title = ? WHERE item_uuid = ?",
                    (merged_title, p_uuid),
                )
            # 2) 资产重指/去重（UNIQUE(item_uuid)：primary 已有资产时删除
            #    duplicate 的资产行，绝不留孤立资产）
            if duplicate["assetUuid"] is not None:
                if primary["assetUuid"] is None:
                    conn.execute(
                        "UPDATE library_assets SET item_uuid = ? WHERE uuid = ?",
                        (p_uuid, duplicate["assetUuid"]),
                    )
                else:
                    conn.execute(
                        "DELETE FROM library_assets WHERE uuid = ?",
                        (duplicate["assetUuid"],),
                    )
            # 3) 批注重挂
            conn.execute(
                "UPDATE annotations SET entry_ref = ? WHERE entry_ref = ?",
                (p_ref, d_ref),
            )
            # 4) 标签迁移（union 中 primary 尚未绑定的项补绑定——事务内
            #    直写 item_tags，绕开 TagStore 的逐条事务）
            for tag_name in tags_union:
                tag_row = conn.execute(
                    "SELECT id FROM tags WHERE name = ? COLLATE NOCASE",
                    (tag_name,),
                ).fetchone()
                if tag_row is None:
                    cursor = conn.execute(
                        "INSERT INTO tags (name) VALUES (?)", (tag_name,)
                    )
                    tag_id = cursor.lastrowid
                else:
                    tag_id = int(tag_row["id"])
                exists = conn.execute(
                    "SELECT 1 FROM item_tags WHERE item_ref = ? AND tag_id = ? AND origin = 'manual'",
                    (p_ref, tag_id),
                ).fetchone()
                if exists is None:
                    conn.execute(
                        "INSERT INTO item_tags (item_ref, tag_id, origin, status, created_at) VALUES (?, ?, 'manual', 'active', ?)",
                        (p_ref, tag_id, now),
                    )
            # 5) duplicate 成员关系清除 + merged 映射 + 软删 + 搜索投影移除
            conn.execute(
                "DELETE FROM workspace_items WHERE item_ref = ?", (d_ref,)
            )
            conn.execute(
                "INSERT INTO item_relations (src_ref, dst_ref, note, kind, created_at) VALUES (?, ?, '', 'merged', ?)",
                (p_ref, d_ref, now),
            )
            conn.execute(
                "UPDATE library_items SET deleted_at = ? WHERE uuid = ?",
                (now, d_uuid),
            )
            delete_search_row(conn, d_ref)

        await transaction(self._db, _tx)

        # 事务成功后才清理 duplicate 资产文件（若走了删除分支）。
        if (
            dup_asset_path
            and primary["assetUuid"] is not None
            and duplicate["assetUuid"] is not None
        ):
            try:
                if os.path.exists(dup_asset_path):
                    os.remove(dup_asset_path)
            except OSError:  # pragma: no cover — 文件清理尽力而为
                pass

        return {
            "mergedRef": p_ref,
            "removedRef": d_ref,
            "tagsUnion": tags_union,
            "movedAnnotations": duplicate["annotationCount"],
            "trashed": True,
        }
