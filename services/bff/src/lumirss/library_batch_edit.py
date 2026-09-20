"""F081 批量元数据编辑 —— library 域 Lumi 字段的批量预览与应用。

边界（规格固定）：
- 仅接受 ``library:<uuid>`` 引用（rss: 引用属 FreshRSS 域，逐项报错，
  绝不改写；Obsidian 文件为只读投影，本模块零接触）；
- title 只允许追加后缀（"原题 suffix"），检测到已存在后缀则跳过
  （幂等：重复应用不重复追加）；
- tags add/remove 幂等（走 TagStore 既有 attach/detach）；
- workspaceId = 移动目标：加入目标工作区并移出其它工作区（原值在
  preview 中如实呈现）；
- preview 零写入；apply 逐条执行、部分失败逐项汇报（可重试）。

本文件直接写站点仅 2 处（bookmarks/clip 标题 UPDATE 各一）。
"""

import sqlite3
from typing import Any

from lumirss.db_tx import transaction
from lumirss.itemref import LIBRARY_DOMAIN, parse_item_ref
from lumirss.library import _MAX_TITLE_LENGTH
from lumirss.storage import Database


class BatchEditInvalid(ValueError):
    """批量编辑载荷非法（refs 数量、后缀长度等），映射 422。"""


_MAX_BATCH_REFS = 50


def _normalize_ref(ref: str) -> str:
    try:
        return parse_item_ref(ref).format()
    except ValueError as exc:
        raise BatchEditInvalid(str(exc)) from exc


def _state_from_rows(
    title: str, tags: list[str], workspace_ids: list[str]
) -> dict[str, Any]:
    return {"title": title, "tags": tags, "workspaceIds": workspace_ids}


class BatchEditService:
    """预览与应用（title 走 payload 表；tags/workspace 走既有 store）。"""

    def __init__(
        self,
        db: Database,
        tag_store: Any,
        workspace_store: Any,
    ) -> None:
        self._db = db
        self._tags = tag_store
        self._workspaces = workspace_store

    # -- 读取当前状态 -------------------------------------------------------

    async def _item_row(self, item_uuid: str) -> dict[str, Any] | None:
        row = await self._db.fetch_one(
            "SELECT i.uuid, i.kind, i.deleted_at FROM library_items i WHERE i.uuid = ?",
            (item_uuid,),
        )
        if row is None or row["deleted_at"] is not None:
            return None
        kind = str(row["kind"])
        title: str | None = None
        if kind == "bookmark":
            row_b = await self._db.fetch_one(
                "SELECT title FROM library_bookmarks WHERE item_uuid = ?",
                (item_uuid,),
            )
            title = str(row_b["title"]) if row_b is not None else None
        elif kind == "clip":
            row_c = await self._db.fetch_one(
                "SELECT title FROM library_clips WHERE item_uuid = ?",
                (item_uuid,),
            )
            title = str(row_c["title"]) if row_c is not None else None
        if title is None:
            return None
        return {"uuid": item_uuid, "kind": kind, "title": title}

    async def _workspace_ids_for(self, ref: str) -> list[str]:
        rows = await self._db.fetch_all(
            "SELECT workspace_id FROM workspace_items WHERE item_ref = ? ORDER BY workspace_id ASC",
            (ref,),
        )
        return [str(r["workspace_id"]) for r in rows]

    async def _current_state(self, ref: str) -> dict[str, Any] | None:
        item_uuid = ref.removeprefix(f"{LIBRARY_DOMAIN}:")
        row = await self._item_row(item_uuid)
        if row is None:
            return None
        tags = await self._tags.tags_for_item(ref)
        tag_names = [str(t["name"]) for t in tags]
        return _state_from_rows(
            row["title"], tag_names, await self._workspace_ids_for(ref)
        )

    # -- 预览 ---------------------------------------------------------------

    async def preview(
        self,
        refs: list[str],
        *,
        title_suffix: str | None,
        tags_add: list[str] | None,
        tags_remove: list[str] | None,
        workspace_id: str | None,
    ) -> list[dict[str, Any]]:
        """逐项 before/after（零写入）。失效 ref 以 after=before 呈现
        会被 apply 报 not_found——preview 只对可编辑项给出 after。"""
        cleaned: list[str] = []
        for ref in refs:
            try:
                cleaned.append(_normalize_ref(ref))
            except BatchEditInvalid:
                cleaned.append(str(ref))  # 逐项汇报，不中断整批
        items: list[dict[str, Any]] = []
        for ref in cleaned:
            before = await self._current_state(ref)
            if before is None:
                items.append({"ref": ref, "before": None, "after": None})
                continue
            after_title = before["title"]
            if title_suffix and not before["title"].endswith(title_suffix):
                after_title = before["title"] + " " + title_suffix
            tag_set = list(before["tags"])
            if tags_add:
                for tag in tags_add:
                    if tag not in tag_set:
                        tag_set.append(tag)
            if tags_remove:
                tag_set = [t for t in tag_set if t not in tags_remove]
            workspaces = (
                [workspace_id]
                if workspace_id
                else list(before["workspaceIds"])
            )
            items.append(
                {
                    "ref": ref,
                    "before": before,
                    "after": _state_from_rows(
                        after_title, tag_set, workspaces
                    ),
                }
            )
        return items

    # -- 应用 ---------------------------------------------------------------

    async def _apply_title(self, kind: str, item_uuid: str, title: str) -> None:
        def _tx_bookmark(conn: sqlite3.Connection) -> int:
            cursor = conn.execute(
                "UPDATE library_bookmarks SET title = ? WHERE item_uuid = ?",
                (title, item_uuid),
            )
            return cursor.rowcount

        def _tx_clip(conn: sqlite3.Connection) -> int:
            cursor = conn.execute(
                "UPDATE library_clips SET title = ? WHERE item_uuid = ?",
                (title, item_uuid),
            )
            return cursor.rowcount

        if kind == "bookmark":
            await transaction(self._db, _tx_bookmark)
        elif kind == "clip":
            await transaction(self._db, _tx_clip)
        else:  # pragma: no cover — kind 白名单在 _item_row 已过滤
            raise BatchEditInvalid("unsupported_kind")

    async def apply(
        self,
        refs: list[str],
        *,
        title_suffix: str | None,
        tags_add: list[str] | None,
        tags_remove: list[str] | None,
        workspace_id: str | None,
    ) -> list[dict[str, Any]]:
        """逐条应用；单条失败不影响其余（部分失败可重试）。"""
        if title_suffix and len(title_suffix) > _MAX_TITLE_LENGTH:
            raise BatchEditInvalid("titleSuffix is too long.")
        if workspace_id is not None:
            target = await self._workspaces.get_workspace(workspace_id)
            if target is None:
                raise BatchEditInvalid("目标工作区不存在。")
        results: list[dict[str, Any]] = []
        for raw_ref in refs:
            try:
                ref = _normalize_ref(raw_ref)
            except BatchEditInvalid as exc:
                results.append(
                    {"ref": str(raw_ref), "ok": False, "error": str(exc)[:200]}
                )
                continue
            try:
                if not ref.startswith(f"{LIBRARY_DOMAIN}:"):
                    raise BatchEditInvalid("仅支持 library 引用（rss 域不修改）。")
                item_uuid = ref.removeprefix(f"{LIBRARY_DOMAIN}:")
                row = await self._item_row(item_uuid)
                if row is None:
                    raise BatchEditInvalid("条目不存在或已删除。")
                if title_suffix and not row["title"].endswith(title_suffix):
                    new_title = row["title"] + " " + title_suffix
                    if len(new_title) > _MAX_TITLE_LENGTH:
                        raise BatchEditInvalid("追加后缀后标题超长。")
                    await self._apply_title(row["kind"], item_uuid, new_title)
                for tag in tags_add or []:
                    await self._tags.attach(ref, tag, origin="manual")
                for tag in tags_remove or []:
                    await self._tags.detach(ref, tag, origin="manual")
                if workspace_id is not None:
                    current = await self._workspace_ids_for(ref)
                    for old in current:
                        if old != workspace_id:
                            await self._workspaces.remove_item(old, ref)
                    await self._workspaces.add_item(workspace_id, ref)
                results.append({"ref": ref, "ok": True})
            except (BatchEditInvalid, ValueError) as exc:
                results.append({"ref": ref, "ok": False, "error": str(exc)[:200]})
            except Exception as exc:  # noqa: BLE001 — 逐项诚实汇报
                results.append({"ref": ref, "ok": False, "error": str(exc)[:200]})
        return results
