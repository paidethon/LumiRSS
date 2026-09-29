"""NEW-260 研究分享脱敏预览 —— 共享前逐项盘点私人笔记、成员名字与附件。

- 盘点（只读，零写入）：
  - privateNotes：研究组各表的笔记类字段（hypothesis 材料注、反例注/
    处理说明、时间线注、缺口关闭注）逐项列出（表 + 字段 + id + 摘录）；
  - memberNames：用控制库账号名单（精确子串匹配，不做任何推断）在
    项目全部自由文本字段里找成员用户名的出现位置；
  - attachments：研究组各表不存附件（NEW-240 附件属于 library 域，
    不挂在研究项目下）——诚实返回空表 + 说明，绝不伪造附件条目。
- 确认：POST 确认把用户逐项勾选结果存成 manifest 快照（append-only）。
  快照只是「可带出清单」的核对记录，不产出任何真实分享包/导出文件。
"""

import json
import uuid as _uuid
from typing import Any

from lumirss.new251_research import (
    ProjectNotFound,
    ResearchInvalid,
    require_project,
)
from lumirss.util import utc_now

MAX_CONFIRM_ITEMS = 500
_EXCERPT_LEN = 120

# 项目内全部自由文本字段的只读盘点（table, field）；成员名扫描全集。
_SCAN_QUERIES: tuple[tuple[str, str, str], ...] = (
    (
        "research_hypothesis_materials",
        "note",
        "SELECT 'research_hypothesis_materials' AS src_table, m.id AS src_id, 'note' AS src_field, "
        "m.note AS src_text FROM research_hypothesis_materials m "
        "JOIN research_hypotheses h ON m.hypothesis_id = h.id "
        "WHERE h.project_id = ? AND m.note IS NOT NULL AND TRIM(m.note) != ''",
    ),
    (
        "research_counterexamples",
        "excerpt",
        "SELECT 'research_counterexamples' AS src_table, id AS src_id, 'excerpt' AS src_field, "
        "excerpt AS src_text FROM research_counterexamples "
        "WHERE project_id = ? AND TRIM(excerpt) != ''",
    ),
    (
        "research_counterexamples",
        "note",
        "SELECT 'research_counterexamples' AS src_table, id AS src_id, 'note' AS src_field, "
        "note AS src_text FROM research_counterexamples "
        "WHERE project_id = ? AND note IS NOT NULL AND TRIM(note) != ''",
    ),
    (
        "research_counterexamples",
        "resolutionNote",
        "SELECT 'research_counterexamples' AS src_table, id AS src_id, 'resolutionNote' AS src_field, "
        "resolution_note AS src_text FROM research_counterexamples "
        "WHERE project_id = ? AND resolution_note IS NOT NULL AND TRIM(resolution_note) != ''",
    ),
    (
        "research_timeline_events",
        "note",
        "SELECT 'research_timeline_events' AS src_table, id AS src_id, 'note' AS src_field, "
        "note AS src_text FROM research_timeline_events "
        "WHERE project_id = ? AND note IS NOT NULL AND TRIM(note) != ''",
    ),
    (
        "research_material_gaps",
        "closeNote",
        "SELECT 'research_material_gaps' AS src_table, id AS src_id, 'closeNote' AS src_field, "
        "close_note AS src_text FROM research_material_gaps "
        "WHERE project_id = ? AND close_note IS NOT NULL AND TRIM(close_note) != ''",
    ),
    (
        "research_material_gaps",
        "description",
        "SELECT 'research_material_gaps' AS src_table, id AS src_id, 'description' AS src_field, "
        "description AS src_text FROM research_material_gaps "
        "WHERE project_id = ? AND TRIM(description) != ''",
    ),
    (
        "research_subquestions",
        "conclusion",
        "SELECT 'research_subquestions' AS src_table, s.id AS src_id, 'conclusion' AS src_field, "
        "s.conclusion AS src_text FROM research_subquestions s "
        "JOIN research_questions q ON s.question_id = q.id "
        "WHERE q.project_id = ? AND s.conclusion IS NOT NULL AND TRIM(s.conclusion) != ''",
    ),
    (
        "research_decisions",
        "basis",
        "SELECT 'research_decisions' AS src_table, id AS src_id, 'basis' AS src_field, "
        "basis AS src_text FROM research_decisions "
        "WHERE project_id = ? AND basis IS NOT NULL AND TRIM(basis) != ''",
    ),
    (
        "research_outline_items",
        "content",
        "SELECT 'research_outline_items' AS src_table, id AS src_id, 'content' AS src_field, "
        "content AS src_text FROM research_outline_items "
        "WHERE section_id IN (SELECT id FROM research_outline_sections WHERE project_id = ?) "
        "AND TRIM(content) != ''",
    ),
)

_PRIVATE_FIELDS = {"note", "resolutionNote", "closeNote"}


def _excerpt(text: str) -> str:
    return text if len(text) <= _EXCERPT_LEN else text[:_EXCERPT_LEN] + "…"


class SharePreviewStore:
    def __init__(self, db: Any, accounts: Any) -> None:
        self._db = db
        self._accounts = accounts

    async def _scan_rows(self, project_id: str) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for _table, _field, sql in _SCAN_QUERIES:
            for row in await self._db.fetch_all(sql, (project_id,)):
                rows.append(
                    {
                        "table": str(row["src_table"]),
                        "id": str(row["src_id"]),
                        "field": str(row["src_field"]),
                        "text": str(row["src_text"]),
                    }
                )
        return rows

    async def preview(self, project_id: str) -> dict[str, Any]:
        await require_project(self._db, project_id)
        scan = await self._scan_rows(project_id)

        private_notes = [
            {
                "id": f"{row['table']}:{row['id']}:{row['field']}",
                "table": row["table"],
                "field": row["field"],
                "itemId": row["id"],
                "excerpt": _excerpt(row["text"]),
            }
            for row in scan
            if row["field"] in _PRIVATE_FIELDS
        ]

        usernames = [
            str(u["username"])
            for u in await self._accounts.list_users(limit=200)
            if u.get("username")
        ]
        member_hits: list[dict[str, Any]] = []
        for username in sorted(usernames):
            occurrences = [
                {
                    "id": f"{row['table']}:{row['id']}:{row['field']}",
                    "table": row["table"],
                    "field": row["field"],
                    "itemId": row["id"],
                }
                for row in scan
                if username in row["text"]
            ]
            if occurrences:
                member_hits.append({"username": username, "occurrences": occurrences})

        return {
            "projectId": project_id,
            "privateNotes": private_notes,
            "memberNames": member_hits,
            "attachments": [],
            "attachmentsNote": "研究组各表不存附件（附件属于 library 域，不挂在研究项目下）——无附件可盘点。",
            "note": "预览是逐项核对工具；确认只存清单快照，不产出任何真实分享包。",
        }

    async def confirm(
        self, project_id: str, *, include_note_ids: Any, anonymize_usernames: Any
    ) -> dict[str, Any]:
        await require_project(self._db, project_id)
        if not isinstance(include_note_ids, list) or not isinstance(anonymize_usernames, list):
            raise ResearchInvalid("includePrivateNoteIds / anonymizeMemberUsernames 必须是数组。")
        if len(include_note_ids) > MAX_CONFIRM_ITEMS or len(anonymize_usernames) > MAX_CONFIRM_ITEMS:
            raise ResearchInvalid(f"确认清单每类最多 {MAX_CONFIRM_ITEMS} 项。")

        note_ids: list[str] = []
        for raw in include_note_ids:
            if not isinstance(raw, str) or not raw.strip():
                raise ResearchInvalid("includePrivateNoteIds 里只能是非空字符串。")
            if raw.strip() not in note_ids:
                note_ids.append(raw.strip())
        usernames: list[str] = []
        for raw in anonymize_usernames:
            if not isinstance(raw, str) or not raw.strip():
                raise ResearchInvalid("anonymizeMemberUsernames 里只能是非空字符串。")
            if raw.strip() not in usernames:
                usernames.append(raw.strip())

        # 快照自带盘点计数（可核对）：确认时的私人笔记总数 / 成员命中数。
        preview = await self.preview(project_id)
        now = utc_now()
        manifest = {
            "includePrivateNoteIds": note_ids,
            "anonymizeMemberUsernames": usernames,
            "privateNoteCountAtConfirm": len(preview["privateNotes"]),
            "memberNameHitCountAtConfirm": sum(
                len(m["occurrences"]) for m in preview["memberNames"]
            ),
        }
        confirmation_id = str(_uuid.uuid4())
        await self._db.execute(
            "INSERT INTO research_share_confirmations (id, project_id, manifest, created_at) "
            "VALUES (?, ?, ?, ?)",
            (confirmation_id, project_id, json.dumps(manifest, ensure_ascii=False), now),
        )
        return {
            "id": confirmation_id,
            "projectId": project_id,
            "manifest": manifest,
            "createdAt": now,
        }

    async def list_confirmations(self, project_id: str) -> dict[str, Any]:
        await require_project(self._db, project_id)
        rows = await self._db.fetch_all(
            "SELECT id, manifest, created_at FROM research_share_confirmations "
            "WHERE project_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 100",
            (project_id,),
        )
        items = []
        for row in rows:
            try:
                manifest = json.loads(str(row["manifest"]))
                if not isinstance(manifest, dict):
                    manifest = {}
            except ValueError:
                manifest = {}
            items.append(
                {
                    "id": str(row["id"]),
                    "projectId": project_id,
                    "manifest": manifest,
                    "createdAt": str(row["created_at"]),
                }
            )
        return {"projectId": project_id, "items": items}


__all__ = ["ProjectNotFound", "ResearchInvalid", "SharePreviewStore"]
