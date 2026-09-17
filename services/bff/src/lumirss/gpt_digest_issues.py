"""GPT 日报期刊行的 SQL 唯一入口（M4）。

upsert 以 ``issue_key`` 为唯一键：同一天重复生成 = 修订（同一行，
``updated_at`` 前移、``published_at`` 保留首次发布时刻），订阅端不会
看到无穷重复刊次。并发与重启由 UNIQUE 约束兜底——第二个写入者改为
UPDATE 路径，最多产生一个逻辑发布结果。
"""

import json
from typing import Any

from lumirss.storage import Database


class GptDigestIssuesStore:
    """Issue persistence: upsert / recent list / single get."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def upsert_issue(
        self,
        *,
        config_id: int,
        issue_key: str,
        title: str,
        body_html: str,
        sections_json: str,
        refs_json: str,
        model: str,
        published_at: str,
    ) -> dict[str, Any]:
        await self._db.migrate()
        await self._db.execute(
            "INSERT INTO gpt_digest_issues (config_id, issue_key, status, title, body_html, sections_json, refs_json, model, created_at, published_at, updated_at) VALUES (?, ?, 'published', ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(config_id, issue_key) DO UPDATE SET status = 'published', title = excluded.title, body_html = excluded.body_html, sections_json = excluded.sections_json, refs_json = excluded.refs_json, model = excluded.model, updated_at = excluded.updated_at",
            (
                config_id,
                issue_key,
                title,
                body_html,
                sections_json,
                refs_json,
                model,
                published_at,
                published_at,
                published_at,
            ),
        )
        row = await self._db.fetch_one(
            "SELECT issue_key, status, title, body_html, sections_json, refs_json, model, note, created_at, published_at, updated_at FROM gpt_digest_issues WHERE config_id = ? AND issue_key = ?",
            (config_id, issue_key),
        )
        return dict(row) if row else {}

    async def recent_issues(self, config_id: int, limit: int) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT issue_key, status, title, body_html, sections_json, refs_json, model, note, created_at, published_at, updated_at FROM gpt_digest_issues WHERE config_id = ? AND status = 'published' ORDER BY issue_key DESC LIMIT ?",
            (config_id, max(1, min(limit, 90))),
        )
        return [dict(row) for row in rows]

    async def get_issue(self, config_id: int, issue_key: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT issue_key, status, title, body_html, sections_json, refs_json, model, note, created_at, published_at, updated_at FROM gpt_digest_issues WHERE config_id = ? AND issue_key = ?",
            (config_id, issue_key),
        )
        return dict(row) if row else None

    def issue_to_dto(self, row: dict[str, Any]) -> dict[str, Any]:
        """API 形状：sections/refs 解析为 JSON，正文不进列表响应。"""
        try:
            sections = json.loads(str(row.get("sections_json") or "[]"))
        except ValueError:
            sections = []
        try:
            refs = json.loads(str(row.get("refs_json") or "{}"))
        except ValueError:
            refs = {}
        return {
            "issueKey": str(row.get("issue_key") or ""),
            "status": str(row.get("status") or ""),
            "title": str(row.get("title") or ""),
            "sections": sections,
            "refs": refs,
            "model": str(row.get("model") or ""),
            "createdAt": str(row.get("created_at") or ""),
            "publishedAt": str(row.get("published_at") or ""),
            "updatedAt": str(row.get("updated_at") or ""),
        }
