"""N120 工作区清理预演 —— 只读报告 + 选择性应用 + 快照撤销。

- 预演（GET /cleanup-preview）只读：unresolved_refs（feed/entry 已消失
  的 rss 成员行）、protected_library_refs（解析不到但受保护的库引用）、
  unverifiable_refs（无法核实——上游未配置/超时/出错，绝不建议删除）、
  empty_groups（组顺序里已无成员的空组名）、orphan_section_refs（指向
  已移出工作区条目的分节引用行）、pinned_group_conflicts（固定条目仍
  带组标签的呈现冲突，只报告）；每项带原因，绝不静默；
- 应用（POST /cleanup）只接受三个可执行类目，只删 Lumi 自有元数据行：
  * unresolved_refs → workspace_items 成员行（仅 rss: 域——library:
    域引用受保护，即使解析不到也绝不删除）；
  * empty_groups → workspaces.group_order_json 里的空组名；
  * orphan_section_refs → workspace_section_items 悬空引用行；
  * 绝不触碰 FreshRSS 数据（read/star/条目本体不动——预演根本不写
    上游，应用也只 DELETE Lumi 行）；
- 快照先行：每次真实删除前把被移除行原值（含 group_name/pinned/
  snoozed_until 列 + 移除前的组顺序）整包写入 workspace_cleanup_log
  （N105 会话快照同构：只存元数据行，绝不复制内容）；上限 5 条，
  超出淘汰最旧；
- 撤销（POST /cleanup/undo）按日志恢复被移除的行（已存在则跳过——
  重复 undo 幂等）；真实写库时 bump workspaces.revision。

本文件直接写站点 5 处（workspace_items DELETE、workspace_section_items
DELETE、group_order_json UPDATE、cleanup_log INSERT/DELETE、恢复期
INSERT——恢复是对既有行的重新插入）。
"""

import json
import sqlite3
import uuid
from typing import Any

from lumirss.db_tx import transaction
from lumirss.storage import Database
from lumirss.util import utc_now
from lumirss.workspaces import WorkspaceNotFound, WorkspaceStore

# 可执行类目（POST /cleanup 白名单；其余类目只读报告，拒绝执行）。
ACTIONABLE_CATEGORIES = ("unresolved_refs", "empty_groups", "orphan_section_refs")
# 只读类目（出现在预演里；POST /cleanup 收到 → 422）。
REPORT_ONLY_CATEGORIES = (
    "protected_library_refs",
    "unverifiable_refs",
    "pinned_group_conflicts",
)
_MAX_LOG_ENTRIES = 5
_PAYLOAD_VERSION = 1


class CleanupInvalid(ValueError):
    """清理载荷非法（未知/只读类目、空类目表），映射 422。"""


class CleanupLogNotFound(Exception):
    """撤销日志不存在（或已随上限淘汰），映射 404。"""


class WorkspaceCleanupStore:
    """Persistence for workspace cleanup preview/apply/undo (N120)."""

    def __init__(self, db: Database, workspace_store: WorkspaceStore) -> None:
        self._db = db
        self._workspaces = workspace_store

    # -- preview（DB 侧类目；ref 解析类目由路由层传入） ----------------------

    async def empty_groups(self, workspace_id: str) -> list[dict[str, Any]]:
        """组顺序里已无任何成员的空组名（N101 组是行派生的，空组只能
        存活在 group_order_json 里）。"""
        order = await self._workspaces._stored_group_order(workspace_id)  # noqa: SLF001 — 同域协作
        if not order:
            return []
        rows = await self._db.fetch_all(
            "SELECT DISTINCT group_name FROM workspace_items WHERE workspace_id = ? AND group_name IS NOT NULL",
            (workspace_id,),
        )
        live = {str(r["group_name"]) for r in rows}
        return [
            {"name": name, "reason": "分组已没有任何成员（组顺序残留）。"}
            for name in order
            if name not in live
        ]

    async def orphan_section_refs(self, workspace_id: str) -> list[dict[str, Any]]:
        """指向已移出工作区条目的分节引用行（分节是组织结构，成员行
        删除后引用行保留 → 这里诚实列出）。"""
        rows = await self._db.fetch_all(
            "SELECT si.section_id, si.item_ref, s.title FROM workspace_section_items si"
            " JOIN workspace_sections s ON s.id = si.section_id"
            " WHERE s.workspace_id = ? AND NOT EXISTS ("
            "  SELECT 1 FROM workspace_items w WHERE w.workspace_id = s.workspace_id AND w.item_ref = si.item_ref)",
            (workspace_id,),
        )
        return [
            {
                "sectionId": str(r["section_id"]),
                "sectionTitle": str(r["title"]),
                "itemRef": str(r["item_ref"]),
                "reason": "分节引用的条目已不在工作区（引用悬空）。N113 契约：列表诚实标记，绝不静默。",
            }
            for r in rows
        ]

    async def pinned_group_conflicts(self, workspace_id: str) -> list[dict[str, Any]]:
        """固定条目仍携带组标签（分组视图固定区优先，组归属被隐藏）——
        只报告的呈现冲突，不属于删除范围。"""
        rows = await self._db.fetch_all(
            "SELECT item_ref, group_name FROM workspace_items WHERE workspace_id = ? AND pinned = 1 AND group_name IS NOT NULL",
            (workspace_id,),
        )
        return [
            {
                "itemRef": str(r["item_ref"]),
                "groupName": str(r["group_name"]),
                "reason": "固定条目仍带组标签：分组视图中固定区优先，组归属被隐藏。",
            }
            for r in rows
        ]

    # -- apply ---------------------------------------------------------------

    async def apply(
        self,
        workspace_id: str,
        categories: list[str],
        *,
        unresolved_refs: list[str],
    ) -> dict[str, Any]:
        """应用选中的类目（快照先行 → 单事务删除 → 日志上限维护）。

        ``unresolved_refs``：路由层已核实消失的 rss: 引用（本方法再次
        强制 rss: 前缀过滤——library: 域引用受保护，绝不删除）。"""
        if not isinstance(categories, list) or not categories:
            raise CleanupInvalid("categories 必须是非空数组。")
        unknown = [c for c in categories if c not in ACTIONABLE_CATEGORIES]
        if unknown:
            raise CleanupInvalid(
                "categories 含未知或只读类目（可执行："
                + ", ".join(ACTIONABLE_CATEGORIES)
                + "）。"
            )
        if len(set(categories)) != len(categories):
            raise CleanupInvalid("categories must not contain duplicates.")
        summary = await self._workspaces.get_workspace(workspace_id)
        if summary is None:
            raise WorkspaceNotFound(workspace_id)
        # 双保险：即便调用方误传，library: 域引用也在这里被剥除。
        rss_unresolved = [ref for ref in unresolved_refs if ref.startswith("rss:")]

        removed_items = await self._fetch_item_rows(workspace_id, rss_unresolved)
        removed_section_items = await self._fetch_orphan_section_rows(workspace_id)
        group_order_before = await self._workspaces._stored_group_order(workspace_id)  # noqa: SLF001 — 同域协作
        empty_names = {entry["name"] for entry in await self.empty_groups(workspace_id)}

        wants_refs = "unresolved_refs" in categories
        wants_groups = "empty_groups" in categories
        wants_orphans = "orphan_section_refs" in categories

        def _tx(conn: sqlite3.Connection) -> None:
            if wants_refs:
                for ref in rss_unresolved:
                    conn.execute(
                        "DELETE FROM workspace_items WHERE workspace_id = ? AND item_ref = ?",
                        (workspace_id, ref),
                    )
            if wants_orphans:
                conn.execute(
                    "DELETE FROM workspace_section_items WHERE section_id IN ("
                    " SELECT id FROM workspace_sections WHERE workspace_id = ?)"
                    " AND NOT EXISTS ("
                    "  SELECT 1 FROM workspace_items w WHERE w.workspace_id = ? AND w.item_ref = workspace_section_items.item_ref)",
                    (workspace_id, workspace_id),
                )
            if wants_groups and empty_names:
                kept = [n for n in group_order_before if n not in empty_names]
                conn.execute(
                    "UPDATE workspaces SET group_order_json = ? WHERE id = ?",
                    (json.dumps(kept, ensure_ascii=False), workspace_id),
                )
            if removed_items or removed_section_items or (wants_groups and empty_names):
                conn.execute(
                    "UPDATE workspaces SET revision = revision + 1 WHERE id = ?",
                    (workspace_id,),
                )

        if not (wants_refs or wants_groups or wants_orphans):
            # 不可达（白名单校验已挡）——防御式保守：不写、不删、不 bump。
            raise CleanupInvalid("没有可执行的类目。")
        await transaction(self._db, _tx)

        payload = {
            "version": _PAYLOAD_VERSION,
            "workspaceId": workspace_id,
            "categories": list(categories),
            "workspaceItems": removed_items if wants_refs else [],
            "sectionItems": removed_section_items if wants_orphans else [],
            "groupOrderBefore": group_order_before if wants_groups else None,
        }
        log_id = await self._write_log(workspace_id, payload)
        return {
            "logId": log_id,
            "removed": {
                "unresolvedRefs": len(payload["workspaceItems"]),
                "emptyGroups": len(empty_names) if wants_groups else 0,
                "orphanSectionRefs": len(payload["sectionItems"]),
            },
        }

    # -- undo ----------------------------------------------------------------

    async def list_logs(self, workspace_id: str) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT id, workspace_id, created_at, payload_json FROM workspace_cleanup_log WHERE workspace_id = ? ORDER BY rowid DESC",
            (workspace_id,),
        )
        return [self._log_view(row) for row in rows]

    async def undo(self, workspace_id: str, log_id: str | None = None) -> dict[str, Any]:
        """恢复一条清理日志移除的行（缺省 = 最近一条；重复 undo 幂等：
        已存在的行跳过）。真实恢复时 bump revision。"""
        if log_id is None:
            row = await self._db.fetch_one(
                "SELECT id, workspace_id, created_at, payload_json FROM workspace_cleanup_log WHERE workspace_id = ? ORDER BY rowid DESC LIMIT 1",
                (workspace_id,),
            )
        else:
            row = await self._db.fetch_one(
                "SELECT id, workspace_id, created_at, payload_json FROM workspace_cleanup_log WHERE workspace_id = ? AND id = ?",
                (workspace_id, log_id),
            )
        if row is None:
            raise CleanupLogNotFound(log_id or "latest")
        try:
            payload = json.loads(str(row["payload_json"]))
        except ValueError as exc:
            raise CleanupInvalid("清理日志损坏，无法撤销。") from exc
        items = payload.get("workspaceItems") if isinstance(payload, dict) else None
        section_items = (
            payload.get("sectionItems") if isinstance(payload, dict) else None
        )
        group_order = (
            payload.get("groupOrderBefore") if isinstance(payload, dict) else None
        )
        restored_refs = 0
        restored_section_refs = 0

        def _tx(conn: sqlite3.Connection) -> None:
            nonlocal restored_refs, restored_section_refs
            for item in items if isinstance(items, list) else []:
                if not isinstance(item, dict):
                    continue
                ref = item.get("item_ref")
                if not isinstance(ref, str):
                    continue
                exists = conn.execute(
                    "SELECT 1 FROM workspace_items WHERE workspace_id = ? AND item_ref = ?",
                    (workspace_id, ref),
                ).fetchone()
                if exists is not None:
                    continue
                conn.execute(
                    "INSERT INTO workspace_items (workspace_id, item_ref, position, added_at, snoozed_until, group_name, pinned) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        workspace_id,
                        ref,
                        int(item.get("position") or 0),
                        str(item.get("added_at") or utc_now()),
                        item.get("snoozed_until"),
                        item.get("group_name"),
                        1 if item.get("pinned") else 0,
                    ),
                )
                restored_refs += 1
            for si in section_items if isinstance(section_items, list) else []:
                if not isinstance(si, dict):
                    continue
                sid = si.get("section_id")
                ref = si.get("item_ref")
                if not isinstance(sid, str) or not isinstance(ref, str):
                    continue
                section_exists = conn.execute(
                    "SELECT 1 FROM workspace_sections WHERE workspace_id = ? AND id = ?",
                    (workspace_id, sid),
                ).fetchone()
                if section_exists is None:
                    continue  # 分节已被删：引用无处安放，诚实跳过
                pair_exists = conn.execute(
                    "SELECT 1 FROM workspace_section_items WHERE section_id = ? AND item_ref = ?",
                    (sid, ref),
                ).fetchone()
                if pair_exists is not None:
                    continue
                conn.execute(
                    "INSERT INTO workspace_section_items (section_id, item_ref, position, added_at) VALUES (?, ?, ?, ?)",
                    (sid, ref, int(si.get("position") or 0), str(si.get("added_at") or utc_now())),
                )
                restored_section_refs += 1
            if isinstance(group_order, list):
                conn.execute(
                    "UPDATE workspaces SET group_order_json = ? WHERE id = ?",
                    (
                        json.dumps([str(n) for n in group_order if isinstance(n, str)], ensure_ascii=False),
                        workspace_id,
                    ),
                )
            if restored_refs or restored_section_refs:
                conn.execute(
                    "UPDATE workspaces SET revision = revision + 1 WHERE id = ?",
                    (workspace_id,),
                )

        await transaction(self._db, _tx)
        return {
            "logId": str(row["id"]),
            "restoredRefs": restored_refs,
            "restoredSectionRefs": restored_section_refs,
        }

    # -- helpers -------------------------------------------------------------

    async def _fetch_item_rows(
        self, workspace_id: str, refs: list[str]
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for ref in refs:
            row = await self._db.fetch_one(
                "SELECT workspace_id, item_ref, position, added_at, snoozed_until, group_name, pinned FROM workspace_items WHERE workspace_id = ? AND item_ref = ?",
                (workspace_id, ref),
            )
            if row is not None:
                rows.append(dict(row))
        return rows

    async def _fetch_orphan_section_rows(
        self, workspace_id: str
    ) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT si.section_id, si.item_ref, si.position, si.added_at FROM workspace_section_items si"
            " JOIN workspace_sections s ON s.id = si.section_id"
            " WHERE s.workspace_id = ? AND NOT EXISTS ("
            "  SELECT 1 FROM workspace_items w WHERE w.workspace_id = s.workspace_id AND w.item_ref = si.item_ref)",
            (workspace_id,),
        )
        return [dict(r) for r in rows]

    async def _write_log(self, workspace_id: str, payload: dict[str, Any]) -> str:
        log_id = f"clean-{uuid.uuid4().hex}"
        await self._db.execute(
            "INSERT INTO workspace_cleanup_log (id, workspace_id, created_at, payload_json) VALUES (?, ?, ?, ?)",
            (log_id, workspace_id, utc_now(), json.dumps(payload, ensure_ascii=False)),
        )
        # 上限 5：超出淘汰最旧（rowid 序 = 写入序，与 N105 列表同理）。
        stale = await self._db.fetch_all(
            "SELECT id FROM workspace_cleanup_log WHERE workspace_id = ? ORDER BY rowid DESC LIMIT -1 OFFSET ?",
            (workspace_id, _MAX_LOG_ENTRIES),
        )
        for row in stale:
            await self._db.execute(
                "DELETE FROM workspace_cleanup_log WHERE id = ?",
                (str(row["id"]),),
            )
        return log_id

    @staticmethod
    def _log_view(row: Any) -> dict[str, Any]:
        try:
            payload = json.loads(str(row["payload_json"]))
        except ValueError:
            payload = {}
        items = payload.get("workspaceItems") if isinstance(payload, dict) else None
        section_items = (
            payload.get("sectionItems") if isinstance(payload, dict) else None
        )
        return {
            "id": str(row["id"]),
            "workspaceId": str(row["workspace_id"]),
            "createdAt": str(row["created_at"]),
            "removedRefCount": len(items) if isinstance(items, list) else 0,
            "removedSectionRefCount": (
                len(section_items) if isinstance(section_items, list) else 0
            ),
        }
