"""NEW-290 简报历史更正 —— 已发布期次的追加式更正记录（append-only）。

- 只增：POST 追加更正，GET 按时间读回；模块不提供任何 UPDATE/DELETE
  路径——期次正文永不静默替换，错误以「更正提示」追加在原期次之后
  （详情 / RSS(285) / EML(289) 三面同一口径）；
- 只对已确认期次生效（草稿还在编辑，不存在「已发布历史」）。

per-user：更正在 per-user 库，A 的期次对 B 不可见（404 同形）。
"""

import uuid as _uuid
from typing import Any

from lumirss.new281_briefings import BriefingInvalid
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_BODY = 2000


class CorrectionStateConflict(Exception):
    """期次未确认，不存在「已发布历史」可更正（映射 409）。"""


def clean_correction_body(raw: Any) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise BriefingInvalid("更正内容不能为空。")
    body = raw.strip()
    if len(body) > _MAX_BODY:
        raise BriefingInvalid(f"更正内容不能超过 {_MAX_BODY} 字符。")
    return body


class CorrectionStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def add(
        self, db_check, issue_id: str, *, body: Any
    ) -> dict[str, Any]:
        """追加更正。``db_check`` 是 BriefingStore（复用 404/状态校验）。"""
        text = clean_correction_body(body)
        issue = await db_check.get_issue(issue_id)  # 404 同形
        if issue["status"] != "confirmed":
            raise CorrectionStateConflict("草稿期次没有已发布历史：请直接编辑草稿。")
        await self._db.migrate()
        correction_id = str(_uuid.uuid4())
        now = utc_now()
        await self._db.execute(
            "INSERT INTO briefing_corrections (id, briefing_id, body, created_at)"
            " VALUES (?, ?, ?, ?)",
            (correction_id, issue_id, text, now),
        )
        return {
            "id": correction_id,
            "briefingId": issue_id,
            "body": text,
            "createdAt": now,
        }

    async def list_corrections(self, issue_id: str) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, briefing_id, body, created_at FROM briefing_corrections"
            " WHERE briefing_id = ? ORDER BY created_at ASC, rowid ASC",
            (issue_id,),
        )
        return [
            {
                "id": str(row["id"]),
                "briefingId": str(row["briefing_id"]),
                "body": str(row["body"]),
                "createdAt": str(row["created_at"]),
            }
            for row in rows
        ]
