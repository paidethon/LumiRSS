"""N118 工作区自动收集规则 —— 手动触发的匹配收集（绝不是后台抓取器）。

- 规则 = 一个来源条件（feedUrl | tag | keyword，恰好其一）+ 累计上限
  ``max_items``（≤100 硬顶）+ 开关 ``enabled``（暂停语义，非删除）；
- 预演（preview，dry-run）：从派生投影（search_entries / item_tags）
  实时匹配，有界 50 条，绝不写库、绝不触发上游抓取；
- 应用（apply）：命中条目以 item_ref 引用进工作区（幂等——已在工作区
  的命中诚实跳过；``add_item`` 只写 Lumi 自有元数据行，绝不复制内容，
  ADR 0004）；``added_count`` 累计本规则真实新增数，到达 ``max_items``
  上限后不再新增（capReached=true 诚实回显）；
- 触发方式只有一种：用户点按钮调 apply（文档化语义：本表没有任何
  后台任务读它——收集是显式动作，不是订阅抓取）。

本文件直接写站点 4 处（规则 INSERT / DELETE / enabled UPDATE /
added_count UPDATE）；成员行写入委托 WorkspaceStore.add_item。
"""

import sqlite3
import uuid
from typing import Any

from lumirss.db_tx import transaction
from lumirss.itemref import parse_item_ref
from lumirss.storage import Database
from lumirss.util import utc_now
from lumirss.workspaces import WorkspaceStore

_MAX_RULES_PER_WORKSPACE = 20
_MAX_KEYWORD_LENGTH = 100
_MAX_FEED_URL_LENGTH = 2000
_MAX_TAG_LENGTH = 100
_MAX_ITEMS_CAP = 100
_PREVIEW_LIMIT = 50


class CollectRuleInvalid(ValueError):
    """规则载荷非法（条件数量/长度/上限），映射 422。"""


class CollectRuleNotFound(Exception):
    """规则不存在（或不属于该工作区），映射 404。"""


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class WorkspaceCollectRuleStore:
    """Persistence for workspace_collect_rules (N118)."""

    def __init__(self, db: Database, workspace_store: WorkspaceStore) -> None:
        self._db = db
        self._workspaces = workspace_store

    # -- CRUD ---------------------------------------------------------------

    async def create_rule(
        self,
        workspace_id: str,
        *,
        feed_url: str | None = None,
        tag: str | None = None,
        keyword: str | None = None,
        max_items: int = 100,
        enabled: bool = True,
    ) -> dict:
        summary = await self._workspaces.get_workspace(workspace_id)
        if summary is None:
            from lumirss.workspaces import WorkspaceNotFound

            raise WorkspaceNotFound(workspace_id)
        clean_feed, clean_tag, clean_keyword = _validate_source(
            feed_url, tag, keyword
        )
        clean_max = _validate_max_items(max_items)
        await self._db.migrate()
        count_row = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM workspace_collect_rules WHERE workspace_id = ?",
            (workspace_id,),
        )
        if count_row is not None and int(count_row["n"]) >= _MAX_RULES_PER_WORKSPACE:
            raise CollectRuleInvalid(
                f"Too many collect rules (max {_MAX_RULES_PER_WORKSPACE})."
            )
        rule_id = f"rule-{uuid.uuid4().hex}"
        now = utc_now()
        await self._db.execute(
            "INSERT INTO workspace_collect_rules (id, workspace_id, source_feed_url, source_tag, keyword, enabled, max_items, added_count, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
            (
                rule_id,
                workspace_id,
                clean_feed,
                clean_tag,
                clean_keyword,
                1 if enabled else 0,
                clean_max,
                now,
                now,
            ),
        )
        rule = await self.get_rule(workspace_id, rule_id)
        assert rule is not None
        return rule

    async def list_rules(self, workspace_id: str) -> list[dict]:
        summary = await self._workspaces.get_workspace(workspace_id)
        if summary is None:
            from lumirss.workspaces import WorkspaceNotFound

            raise WorkspaceNotFound(workspace_id)
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, workspace_id, source_feed_url, source_tag, keyword, enabled, max_items, added_count, created_at, updated_at FROM workspace_collect_rules WHERE workspace_id = ? ORDER BY created_at ASC, id ASC",
            (workspace_id,),
        )
        return [self._view(row) for row in rows]

    async def get_rule(self, workspace_id: str, rule_id: str) -> dict | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, workspace_id, source_feed_url, source_tag, keyword, enabled, max_items, added_count, created_at, updated_at FROM workspace_collect_rules WHERE workspace_id = ? AND id = ?",
            (workspace_id, rule_id),
        )
        return self._view(row) if row is not None else None

    async def set_enabled(
        self, workspace_id: str, rule_id: str, enabled: bool
    ) -> dict:
        """暂停/恢复（set 语义非 toggle；不触碰 added_count）。"""
        if await self.get_rule(workspace_id, rule_id) is None:
            raise CollectRuleNotFound(rule_id)
        await self._db.execute(
            "UPDATE workspace_collect_rules SET enabled = ?, updated_at = ? WHERE workspace_id = ? AND id = ?",
            (1 if enabled else 0, utc_now(), workspace_id, rule_id),
        )
        rule = await self.get_rule(workspace_id, rule_id)
        assert rule is not None
        return rule

    async def delete_rule(self, workspace_id: str, rule_id: str) -> bool:
        if await self.get_rule(workspace_id, rule_id) is None:
            return False

        def _tx(conn: sqlite3.Connection) -> bool:
            cursor = conn.execute(
                "DELETE FROM workspace_collect_rules WHERE workspace_id = ? AND id = ?",
                (workspace_id, rule_id),
            )
            return cursor.rowcount > 0

        return bool(await transaction(self._db, _tx))

    # -- matching (projection only; never upstream) --------------------------

    async def match_refs(self, rule: dict, limit: int) -> list[dict]:
        """从派生投影匹配（只读；超出 limit 截断——调用方据此诚实上报
        ``bounded``）。命中一律回 typed ItemRef（rss: 前缀拼上投影的
        裸 entry_ref；library 腿本来就是 typed ref）。tag 条件经
        item_tags（typed ref）联表；keyword 双腿匹配（search_entries
        标题/正文 + search_library 标题/正文）。"""
        await self._db.migrate()
        if rule["feedUrl"] is not None:
            rows = await self._db.fetch_all(
                "SELECT 'rss:' || entry_ref AS ref, title, feed_title, published_at FROM search_entries WHERE feed_url = ? ORDER BY published_at DESC, id DESC LIMIT ?",
                (rule["feedUrl"], limit),
            )
            return [self._match_view(row) for row in rows]
        if rule["tag"] is not None:
            rows = await self._db.fetch_all(
                "SELECT 'rss:' || e.entry_ref AS ref, e.title, e.feed_title, e.published_at FROM search_entries e WHERE 'rss:' || e.entry_ref IN (SELECT it.item_ref FROM item_tags it JOIN tags t ON t.id = it.tag_id WHERE t.name = ? COLLATE NOCASE AND it.status = 'active') UNION ALL SELECT l.ref, l.title, NULL, NULL FROM search_library l WHERE l.ref IN (SELECT it.item_ref FROM item_tags it JOIN tags t ON t.id = it.tag_id WHERE t.name = ? COLLATE NOCASE AND it.status = 'active') ORDER BY published_at DESC LIMIT ?",
                (rule["tag"], rule["tag"], limit),
            )
            return [self._match_view(row) for row in rows]
        keyword = str(rule["keyword"] or "")
        like = f"%{_escape_like(keyword)}%"
        rows = await self._db.fetch_all(
            "SELECT 'rss:' || entry_ref AS ref, title, feed_title, published_at FROM search_entries WHERE title LIKE ? ESCAPE '\\' OR content_text LIKE ? ESCAPE '\\' UNION ALL SELECT ref, title, NULL AS feed_title, NULL AS published_at FROM search_library WHERE title LIKE ? ESCAPE '\\' OR body LIKE ? ESCAPE '\\' ORDER BY published_at DESC LIMIT ?",
            (like, like, like, like, limit),
        )
        return [self._match_view(row) for row in rows]

    @staticmethod
    def _match_view(row: Any) -> dict:
        return {
            "itemRef": str(row["ref"]),
            "title": str(row["title"] or "") or None,
            "feedTitle": str(row["feed_title"] or "") or None,
            "publishedAt": str(row["published_at"] or "") or None,
        }

    # -- preview / apply -----------------------------------------------------

    async def preview(self, workspace_id: str, rule_id: str) -> dict:
        """N118 预演（dry-run，有界 50）：命中清单 + 既有成员标记 +
        剩余可收集额度。暂停规则照常预演（预演是无害只读），诚实回显
        ``enabled`` 由调用方呈现。"""
        rule = await self.get_rule(workspace_id, rule_id)
        if rule is None:
            raise CollectRuleNotFound(rule_id)
        rows = await self.match_refs(rule, limit=_PREVIEW_LIMIT + 1)
        bounded = len(rows) > _PREVIEW_LIMIT
        rows = rows[:_PREVIEW_LIMIT]
        members = {
            str(r["item_ref"])
            for r in await self._db.fetch_all(
                "SELECT item_ref FROM workspace_items WHERE workspace_id = ? LIMIT 5000",
                (workspace_id,),
            )
        }
        for row in rows:
            row["alreadyMember"] = row["itemRef"] in members
        remaining_cap = max(rule["maxItems"] - rule["addedCount"], 0)
        return {
            "ruleId": rule_id,
            "matches": rows,
            "matchCount": len(rows),
            "bounded": bounded,
            "alreadyMemberCount": sum(1 for row in rows if row["alreadyMember"]),
            "remainingCap": remaining_cap,
        }

    async def apply(self, workspace_id: str, rule_id: str) -> dict:
        """应用规则：命中条目幂等收进工作区（受 ``max_items`` 累计上限
        约束）。暂停规则 → 结果如实带 ``enabled=false`` 且零新增。"""
        rule = await self.get_rule(workspace_id, rule_id)
        if rule is None:
            raise CollectRuleNotFound(rule_id)
        added: list[str] = []
        skipped_existing = 0
        if rule["enabled"]:
            matches = await self.match_refs(
                rule, limit=_PREVIEW_LIMIT + rule["maxItems"]
            )
            for match in matches:
                if rule["addedCount"] + len(added) >= rule["maxItems"]:
                    break
                ref = match["itemRef"]
                try:
                    clean_ref = parse_item_ref(ref).format()
                except ValueError:
                    continue
                member = await self._db.fetch_one(
                    "SELECT 1 FROM workspace_items WHERE workspace_id = ? AND item_ref = ?",
                    (workspace_id, clean_ref),
                )
                if member is not None:
                    skipped_existing += 1
                    continue
                await self._workspaces.add_item(workspace_id, clean_ref)
                added.append(clean_ref)
        if added:
            await self._db.execute(
                "UPDATE workspace_collect_rules SET added_count = added_count + ?, updated_at = ? WHERE id = ?",
                (len(added), utc_now(), rule_id),
            )
        final = await self.get_rule(workspace_id, rule_id)
        assert final is not None
        cap_reached = final["addedCount"] >= final["maxItems"]
        return {
            "ruleId": rule_id,
            "enabled": bool(final["enabled"]),
            "added": added,
            "addedCount": len(added),
            "skippedExisting": skipped_existing,
            "capReached": cap_reached,
            "ruleAddedCount": int(final["addedCount"]),
        }

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _view(row: Any) -> dict:  # noqa: ANN401 — sqlite Row
        return {
            "id": str(row["id"]),
            "workspaceId": str(row["workspace_id"]),
            "feedUrl": row["source_feed_url"],
            "tag": row["source_tag"],
            "keyword": row["keyword"],
            "enabled": bool(row["enabled"]),
            "maxItems": int(row["max_items"]),
            "addedCount": int(row["added_count"]),
            "createdAt": str(row["created_at"]),
            "updatedAt": str(row["updated_at"]),
        }


def _validate_source(
    feed_url: str | None, tag: str | None, keyword: str | None
) -> tuple[str | None, str | None, str | None]:
    """三种条件恰好其一（空串视同未给）；长度上限各自校验。"""
    given = sum(
        1
        for value in (feed_url, tag, keyword)
        if value is not None and str(value).strip()
    )
    if given != 1:
        raise CollectRuleInvalid(
            "恰好需要一种来源条件：feedUrl | tag | keyword。"
        )

    def _clean(value: str | None, limit: int) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        if len(text) > limit:
            raise CollectRuleInvalid(f"来源条件过长（max {limit} 字符）。")
        return text

    return (
        _clean(feed_url, _MAX_FEED_URL_LENGTH),
        _clean(tag, _MAX_TAG_LENGTH),
        _clean(keyword, _MAX_KEYWORD_LENGTH),
    )


def _validate_max_items(max_items: int) -> int:
    if not isinstance(max_items, int) or not 1 <= max_items <= _MAX_ITEMS_CAP:
        raise CollectRuleInvalid(
            f"maxItems 必须是 1–{_MAX_ITEMS_CAP} 的整数。"
        )
    return int(max_items)
