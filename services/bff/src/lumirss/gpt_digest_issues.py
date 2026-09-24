"""GPT 日报期刊行的 SQL 唯一入口（M4）。

upsert 以 ``issue_key`` 为唯一键：同一天重复生成 = 修订（同一行，
``updated_at`` 前移、``published_at`` 保留首次发布时刻），订阅端不会
看到无穷重复刊次。并发与重启由 UNIQUE 约束兜底——第二个写入者改为
UPDATE 路径，最多产生一个逻辑发布结果。
"""

import json
from typing import Any

from lumirss.storage import Database


def parse_issue_meta(row: dict[str, Any]) -> dict[str, Any]:
    """期号 meta_json → dict（损坏/缺失诚实回退空对象）。"""
    try:
        meta = json.loads(str(row.get("meta_json") or "{}"))
    except ValueError:
        return {}
    return meta if isinstance(meta, dict) else {}


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
        status_for_new: str = "published",
        meta_json: str = "{}",
    ) -> dict[str, Any]:
        """F031：新期号可用 status_for_new='draft'（人工审阅后发布）；
        修订已有期号不改状态（ON CONFLICT 不更新 status）。N172：新一次
        生成整体替换 meta_json（分阶段模型标签/润色失败标记等）；
        人工修订（revise_issue）不触碰 meta。"""
        await self._db.migrate()
        await self._db.execute(
            "INSERT INTO gpt_digest_issues (config_id, issue_key, status, title, body_html, sections_json, refs_json, model, meta_json, created_at, published_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(config_id, issue_key) DO UPDATE SET title = excluded.title, body_html = excluded.body_html, sections_json = excluded.sections_json, refs_json = excluded.refs_json, model = excluded.model, meta_json = excluded.meta_json, updated_at = excluded.updated_at",
            (
                config_id,
                issue_key,
                status_for_new,
                title,
                body_html,
                sections_json,
                refs_json,
                model,
                meta_json,
                published_at,
                published_at,
                published_at,
            ),
        )
        row = await self._db.fetch_one(
            "SELECT issue_key, status, title, body_html, sections_json, refs_json, model, note, meta_json, created_at, published_at, updated_at FROM gpt_digest_issues WHERE config_id = ? AND issue_key = ?",
            (config_id, issue_key),
        )
        return dict(row) if row else {}

    async def revise_issue(
        self,
        *,
        config_id: int,
        issue_key: str,
        title: str,
        body_html: str,
        sections: dict[str, Any],
        note: str,
        updated_at: str,
        meta_json: str | None = None,
    ) -> dict[str, Any] | None:
        """F08 人工修订：改标题/删条目/调排序后重渲染发布。

        只接受人工编辑域的字段（title/sections + 由其重渲染的 body_html
        + note）；refs_json、model、published_at 保持生成时的值——修订不
        改变来源引用的真实性，订阅端 entry id 不变、仅 updated 前移。
        N173：``meta_json`` 非空时同步更新（句子映射随人工编辑重算）；
        None = 不触碰。Returns None 当期号不存在。"""
        await self._db.migrate()
        exists = await self._db.fetch_one(
            "SELECT 1 AS x FROM gpt_digest_issues WHERE config_id = ? AND issue_key = ?",
            (config_id, issue_key),
        )
        if exists is None:
            return None
        sections_json = json.dumps(sections, ensure_ascii=False)
        if meta_json is None:
            await self._db.execute(
                "UPDATE gpt_digest_issues SET title = ?, body_html = ?, sections_json = ?, note = ?, updated_at = ? WHERE config_id = ? AND issue_key = ?",
                (title, body_html, sections_json, note[:500], updated_at, config_id, issue_key),
            )
        else:
            await self._db.execute(
                "UPDATE gpt_digest_issues SET title = ?, body_html = ?, sections_json = ?, note = ?, meta_json = ?, updated_at = ? WHERE config_id = ? AND issue_key = ?",
                (title, body_html, sections_json, note[:500], meta_json, updated_at, config_id, issue_key),
            )
        return await self.get_issue(config_id, issue_key)

    async def recent_issues(
        self, config_id: int, limit: int, *, include_drafts: bool = False
    ) -> list[dict[str, Any]]:
        """F031：管理面 include_drafts=True 显示草稿；公开订阅默认只出
        published。"""
        await self._db.migrate()
        where = (
            "WHERE config_id = ?"
            if include_drafts
            else "WHERE config_id = ? AND status = 'published'"
        )
        rows = await self._db.fetch_all(
            f"SELECT issue_key, status, title, body_html, sections_json, refs_json, model, note, meta_json, created_at, published_at, updated_at FROM gpt_digest_issues {where} ORDER BY issue_key DESC LIMIT ?",
            (config_id, max(1, min(limit, 90))),
        )
        return [dict(row) for row in rows]

    async def all_issue_keys(self, config_id: int, limit: int = 90) -> list[str]:
        """F032：全部期号 key（含草稿）——缺失日期判定的真实依据。"""
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT issue_key FROM gpt_digest_issues WHERE config_id = ? ORDER BY issue_key DESC LIMIT ?",
            (config_id, max(1, min(limit, 400))),
        )
        return [str(row["issue_key"]) for row in rows]

    async def publish_issue(self, config_id: int, issue_key: str) -> dict[str, Any] | None:
        """F031：显式发布（幂等：已 published 再发布不改动）。"""
        await self._db.migrate()
        row = await self.get_issue(config_id, issue_key)
        if row is None:
            return None
        if row["status"] == "published":
            return row
        await self._db.execute(
            "UPDATE gpt_digest_issues SET status = 'published' WHERE config_id = ? AND issue_key = ?",
            (config_id, issue_key),
        )
        return await self.get_issue(config_id, issue_key)

    async def get_issue(self, config_id: int, issue_key: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT issue_key, status, title, body_html, sections_json, refs_json, model, note, meta_json, created_at, published_at, updated_at FROM gpt_digest_issues WHERE config_id = ? AND issue_key = ?",
            (config_id, issue_key),
        )
        return dict(row) if row else None

    def issue_to_dto(self, row: dict[str, Any]) -> dict[str, Any]:
        """API 形状：sections/refs 解析为 JSON，正文不进列表响应。"""
        try:
            sections = json.loads(str(row.get("sections_json") or "[]"))
        except ValueError:
            sections = []
        # F031 兼容：generate 落库的是完整输出对象 {title, sections,
        # limitations}；此处统一展开为 sections 列表（DTO 契约保持）。
        if isinstance(sections, dict):
            sections = sections.get("sections") or []
        try:
            refs = json.loads(str(row.get("refs_json") or "{}"))
        except ValueError:
            refs = {}
        meta = parse_issue_meta(row)
        return {
            "issueKey": str(row.get("issue_key") or ""),
            "status": str(row.get("status") or ""),
            "title": str(row.get("title") or ""),
            "sections": sections,
            "refs": refs,
            "model": str(row.get("model") or ""),
            "meta": meta,
            "createdAt": str(row.get("created_at") or ""),
            "publishedAt": str(row.get("published_at") or ""),
            "updatedAt": str(row.get("updated_at") or ""),
        }
