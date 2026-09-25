"""GPT 日报期刊行的 SQL 唯一入口（M4）。

upsert 以 ``issue_key`` 为唯一键：同一天重复生成 = 修订（同一行，
``updated_at`` 前移、``published_at`` 保留首次发布时刻），订阅端不会
看到无穷重复刊次。并发与重启由 UNIQUE 约束兜底——第二个写入者改为
UPDATE 路径，最多产生一个逻辑发布结果。
"""

import json
import re
from typing import Any

from lumirss.storage import Database

_SENTENCE_SPLIT_RE = re.compile(r"[^。！？!?…]*(?:[。！？!?…]+|$)")


def split_sentences(text: str) -> list[str]:
    """N173：把一段总结拆成句子（。！？!?… 为界；换行跟随所在句）。

    切分保真：``"".join(split_sentences(t)) == t``（逐句修订后按原样
    重组，不丢标点也不引入空格）。空白片段不构成句子。Web 端用同一
    正则语义切分，保证 sentenceOps 的句子索引两端一致。"""
    source = str(text or "")
    return [part for part in _SENTENCE_SPLIT_RE.findall(source) if part]


def build_sentence_map(sections: Any) -> list[dict[str, Any]]:
    """N173：由 sections 构建逐句事实检查映射。

    每句继承所在条目的引用（模型在该条目上标注的 sourceIds——「模型
    引用了」的最直接证据）；条目没有引用 → 该句 refs=[]、verified=False
    （待核实）。生成时写入 meta.sentenceMap。"""
    sentence_map: list[dict[str, Any]] = []
    if not isinstance(sections, list):
        return sentence_map
    for section in sections:
        if not isinstance(section, dict):
            continue
        for item in section.get("items", []) or []:
            if not isinstance(item, dict):
                continue
            refs = [sid for sid in item.get("sourceIds", []) or [] if isinstance(sid, str)]
            for sentence in split_sentences(str(item.get("summary") or "")):
                sentence_map.append(
                    {
                        "sentence": sentence,
                        "refs": refs,
                        "verified": bool(refs),
                    }
                )
    return sentence_map


def recompute_sentence_map(
    old_map: Any, new_sections: Any
) -> list[dict[str, Any]]:
    """N173：人工编辑后的映射重算——按句子原文在同一期内容里匹配。

    与旧映射句子原文一致的句子保留原引用（引用是生成时的事实，编辑不
    凭空新增）；改写/新增的句子匹配不到 → refs=[]、verified=False（待
    核实，诚实标注）。删除的句子自然不再出现。"""
    if not isinstance(old_map, list):
        old_map = build_sentence_map(new_sections)
    pool: dict[str, list[dict[str, Any]]] = {}
    for entry in old_map:
        if isinstance(entry, dict):
            pool.setdefault(str(entry.get("sentence") or ""), []).append(entry)
    sentence_map: list[dict[str, Any]] = []
    if not isinstance(new_sections, list):
        return sentence_map
    for section in new_sections:
        if not isinstance(section, dict):
            continue
        for item in section.get("items", []) or []:
            if not isinstance(item, dict):
                continue
            for sentence in split_sentences(str(item.get("summary") or "")):
                queue = pool.get(sentence)
                if queue:
                    entry = queue.pop(0)
                    refs = entry.get("refs")
                    sentence_map.append(
                        {
                            "sentence": sentence,
                            "refs": [r for r in refs or [] if isinstance(r, str)],
                            "verified": bool(refs),
                        }
                    )
                else:
                    sentence_map.append(
                        {"sentence": sentence, "refs": [], "verified": False}
                    )
    return sentence_map


_MAX_USAGE_RESULTS = 20


def _normalize_usage_ref(value: Any) -> str:
    """N180：refs 里的条目引用归一（剥 rss: 前缀；仅接受 opaque e1.*）。"""
    text = str(value or "").strip()
    if text.startswith("rss:"):
        text = text[len("rss:"):]
    return text if text.startswith("e1.") else ""


async def digest_usage_for_entry(
    db: Database, entry_ref: str, *, limit: int = _MAX_USAGE_RESULTS
) -> list[dict[str, Any]]:
    """N180 日报材料使用追踪：在我的配置/期刊里反查某条目的引用位置。

    数据源是期刊行的 refs_json（s1..sN → {…, ref: entryRef}，生成时
    写入；旧期号没有 ref → 查不到 = 诚实空）。查询只发生在当前请求
    用户的库上——其他用户的期刊天然不可见（隔离由每用户数据库保证）。
    返回 [{configId, configName, issueKey, issueDate, section, sourceId,
    citationAnchor, publishedAt}]，citationAnchor 供 Web 跳转定位。"""
    await db.migrate()
    target = _normalize_usage_ref(entry_ref)
    if not target:
        return []
    from lumirss.gpt_digest_configs import GptDigestConfigStore

    configs = await GptDigestConfigStore(db).list_configs()
    usage: list[dict[str, Any]] = []
    cap = max(1, min(limit, _MAX_USAGE_RESULTS))
    for config in configs:
        if len(usage) >= cap:
            break
        rows = await db.fetch_all(
            "SELECT issue_key, published_at, sections_json, refs_json FROM gpt_digest_issues WHERE config_id = ? AND status = 'published' ORDER BY issue_key DESC LIMIT 90",
            (int(config["id"]),),
        )
        for row in rows:
            if len(usage) >= cap:
                break
            try:
                refs = json.loads(str(row["refs_json"] or "{}"))
            except ValueError:
                continue
            try:
                sections = json.loads(str(row["sections_json"] or "[]"))
            except ValueError:
                sections = []
            if isinstance(sections, dict):
                sections = sections.get("sections") or []
            issue_key = str(row["issue_key"])
            for sid, ref in refs.items() if isinstance(refs, dict) else []:
                if not isinstance(ref, dict):
                    continue
                if _normalize_usage_ref(ref.get("ref")) != target:
                    continue
                heading = ""
                if isinstance(sections, list):
                    for section in sections:
                        if not isinstance(section, dict):
                            continue
                        items = section.get("items") or []
                        if any(
                            isinstance(item, dict) and sid in (item.get("sourceIds") or [])
                            for item in items
                        ):
                            heading = str(section.get("heading") or "")
                            break
                usage.append(
                    {
                        "configId": int(config["id"]),
                        "configName": str(config["name"]),
                        "issueKey": issue_key,
                        "issueDate": issue_key[:10],
                        "section": heading,
                        "sourceId": str(sid),
                        "citationAnchor": f"{issue_key}:{sid}",
                        "publishedAt": str(row["published_at"] or ""),
                    }
                )
                if len(usage) >= cap:
                    break
    return usage


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
        # N173：事实检查句子映射——meta 里存有（编辑后重算）的用之；
        # 旧期号没有 → 从 sections 现算（引用继承条目标注）。
        sentence_map = meta.get("sentenceMap")
        if not isinstance(sentence_map, list):
            sentence_map = build_sentence_map(sections)
        # N177：可见订正标记——updated_at 晚于 published_at 即修订过；
        # Web 端在期号顶部渲染订正块（与 Atom 注入口径一致）。
        from lumirss.gpt_digest import is_revised_issue

        return {
            "issueKey": str(row.get("issue_key") or ""),
            "status": str(row.get("status") or ""),
            "title": str(row.get("title") or ""),
            "sections": sections,
            "refs": refs,
            "model": str(row.get("model") or ""),
            "meta": meta,
            "sentenceMap": sentence_map,
            "note": str(row.get("note") or ""),
            "revised": is_revised_issue(row.get("updated_at"), row.get("published_at")),
            "createdAt": str(row.get("created_at") or ""),
            "publishedAt": str(row.get("published_at") or ""),
            "updatedAt": str(row.get("updated_at") or ""),
        }
