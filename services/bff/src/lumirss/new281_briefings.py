"""NEW-281 个人简报编排台 —— 用户自选文章排成一期简报（核心存储）。

语义边界（本组 281..290 的公共地基）：

- 期次（briefings）：draft → confirmed 单向。确认后才进入 RSS 发布
  (285)、EML 导出(289)、更正(290) 的可见面；草稿绝不外泄；
- 编排：选时间范围 + 来源 → 候选摘要卡（search_entries 真实查询，
  只取标题/来源/链接/摘录 ≤200 字，不 shadow-copy 正文）；条目挂
  栏目（sections_json 顺序即栏目顺序）；
- 去重审批（282）：条目引用已在「已确认」期次收录过的 entry_ref 时
  必须显式带 dupDecision(include/defer/skip)，缺失 → DupApprovalRequired
  (409)。草稿期次不算收录——只有确认过才算「已刊出」；
- 人工精选标记（287）：provenance = manual(人工选入) / rule(规则推荐)，
  建稿与建议双入口都如实标注；确认后不可翻转（历史完整性，与 290
  的「不静默替换」同一哲学）；
- 窗口（283）：迟到条目必须显式 pullBack 才能进本期，绝不静默改写
  窗口归属；
- 确认空刊（0 条）→ 422：空白成功页是 284 明令禁止的形态。

per-user：全部行在 per-user 库（RoutingDatabase），A 的期次对 B 不可见。
"""

import json
import sqlite3
import uuid as _uuid
from typing import Any

from lumirss.db_tx import transaction
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_TITLE = 200
_MAX_SECTIONS = 12
_MAX_SECTION_KEY = 40
_MAX_SECTION_LABEL = 60
_MAX_ITEMS = 100
_EXCERPT_CHARS = 200
_CANDIDATE_LIMIT = 60

PROVENANCES = ("manual", "rule")
PROVENANCE_LABELS = {"manual": "编辑选入", "rule": "规则推荐"}
DUP_DECISIONS = ("include", "defer", "skip")


class BriefingInvalid(ValueError):
    """简报负载非法（映射 422）。"""


class BriefingNotFound(Exception):
    """期次不存在（映射 404；跨用户访问同一 404，不泄露存在性）。"""


class BriefingStateConflict(Exception):
    """期次状态不允许该操作（映射 409）。"""


class DupApprovalRequired(Exception):
    """收录已刊出条目但缺少显式去重决定（映射 409 + 审批清单）。"""

    def __init__(self, duplicates: list[dict[str, Any]]) -> None:
        super().__init__("以下条目已在以前期次收录，请逐条给出决定。")
        self.duplicates = duplicates


class LateEntryRejected(Exception):
    """窗口截稿点之后的条目未带 pullBack（映射 422）。"""

    def __init__(self, refs: list[str]) -> None:
        super().__init__("以下条目在截稿点之后发布（迟到），需显式调回。")
        self.refs = refs


def clean_title(raw: Any) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise BriefingInvalid("title 不能为空。")
    title = raw.strip()
    if len(title) > _MAX_TITLE:
        raise BriefingInvalid(f"title 不能超过 {_MAX_TITLE} 字符。")
    return title


def clean_entry_refs(raw: Any, field: str = "entryRef") -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise BriefingInvalid(f"{field} 不能为空。")
    ref = raw.strip()
    if len(ref) > 500:
        raise BriefingInvalid(f"{field} 过长。")
    return ref


def clean_sections(raw: Any) -> list[dict[str, str]]:
    """栏目定义清洗：[{key,label}]，key 唯一且为安全短标识。"""
    if not isinstance(raw, list) or not raw:
        raise BriefingInvalid("sections 必须是非空数组。")
    if len(raw) > _MAX_SECTIONS:
        raise BriefingInvalid(f"栏目不能超过 {_MAX_SECTIONS} 个。")
    seen: set[str] = set()
    sections: list[dict[str, str]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise BriefingInvalid("sections 元素必须是对象。")
        key = entry.get("key")
        label = entry.get("label")
        if not isinstance(key, str) or not key.strip():
            raise BriefingInvalid("栏目 key 不能为空。")
        key = key.strip()
        if len(key) > _MAX_SECTION_KEY or any(ch in key for ch in ' \t"\'<>&/'):
            raise BriefingInvalid(
                "栏目 key 须为 ≤40 字符且不含空白与 <>&\"'/ 的短标识。"
            )
        if not isinstance(label, str) or not label.strip():
            raise BriefingInvalid(f"栏目 {key} 的 label 不能为空。")
        label = label.strip()
        if len(label) > _MAX_SECTION_LABEL:
            raise BriefingInvalid(f"栏目 {key} 的 label 不能超过 {_MAX_SECTION_LABEL}。")
        if key in seen:
            raise BriefingInvalid(f"栏目 key 重复：{key}。")
        seen.add(key)
        sections.append({"key": key, "label": label})
    return sections


def make_excerpt(text: str, limit: int = _EXCERPT_CHARS) -> str:
    collapsed = " ".join((text or "").split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"


def provenance_label(provenance: str) -> str:
    return PROVENANCE_LABELS.get(provenance, provenance)


class BriefingStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    # ---- 候选摘要卡（真实 search_entries 查询，绝不伪造） -----------------

    async def candidates(
        self,
        range_from: str,
        range_to: str,
        *,
        feed_url: str | None = None,
        prior: dict[str, list[dict[str, Any]]] | None = None,
    ) -> list[dict[str, Any]]:
        """时间范围 [from, to) 内的文章摘要卡，附「已在哪几期刊过」。"""
        if not range_from or not range_to:
            raise BriefingInvalid("from 与 to 都是必填（ISO 时间）。")
        if range_from >= range_to:
            raise BriefingInvalid("from 必须早于 to。")
        await self._db.migrate()
        sql = (
            "SELECT entry_ref, item_id, title, feed_title, feed_url, url,"
            " published_at, content_text, starred FROM search_entries"
            " WHERE published_at >= ? AND published_at < ?"
        )
        params: list[Any] = [range_from, range_to]
        if feed_url:
            sql += " AND feed_url = ?"
            params.append(feed_url)
        sql += " ORDER BY published_at DESC, id DESC LIMIT ?"
        params.append(_CANDIDATE_LIMIT)
        rows = await self._db.fetch_all(sql, params)
        prior = prior if prior is not None else await self.prior_issue_index()
        cards: list[dict[str, Any]] = []
        for row in rows:
            ref = str(row["entry_ref"])
            cards.append(
                {
                    "entryRef": ref,
                    "itemId": str(row["item_id"]),
                    "title": str(row["title"]),
                    "feedTitle": str(row["feed_title"]),
                    "feedUrl": str(row["feed_url"]),
                    "url": str(row["url"]),
                    "publishedAt": str(row["published_at"]),
                    "starred": bool(row["starred"]),
                    "excerpt": make_excerpt(str(row["content_text"])),
                    "seenInIssues": prior.get(ref, []),
                }
            )
        return cards

    async def prior_issue_index(self) -> dict[str, list[dict[str, Any]]]:
        """entry_ref -> 已确认期次收录记录（282 去重的真源）。"""
        rows = await self._db.fetch_all(
            "SELECT bi.entry_ref, bi.title, b.id, b.title AS issue_title,"
            " b.confirmed_at FROM briefing_items bi"
            " JOIN briefings b ON b.id = bi.briefing_id"
            " WHERE b.status = 'confirmed'"
            " ORDER BY b.confirmed_at ASC"
        )
        index: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            index.setdefault(str(row["entry_ref"]), []).append(
                {
                    "issueId": str(row["id"]),
                    "issueTitle": str(row["issue_title"]),
                    "confirmedAt": str(row["confirmed_at"] or ""),
                }
            )
        return index

    # ---- 期次 CRUD -------------------------------------------------------

    async def create_issue(
        self,
        *,
        title: Any,
        range_from: str,
        range_to: str,
        sections: Any,
        items: Any,
        source: str = "compose",
        cutoff_utc: str | None = None,
    ) -> dict[str, Any]:
        clean = clean_title(title)
        clean_secs = clean_sections(sections)
        if not isinstance(items, list) or not items:
            raise BriefingInvalid("items 必须是非空数组（空刊不可创建）。")
        if len(items) > _MAX_ITEMS:
            raise BriefingInvalid(f"一期最多 {_MAX_ITEMS} 条。")
        await self._db.migrate()
        now = utc_now()
        issue_id = str(_uuid.uuid4())
        keys = {s["key"] for s in clean_secs}

        # 282 去重审批 + 283 迟到拦截：一次遍历收集两类待决定条目。
        prior = await self.prior_issue_index()
        pending: list[dict[str, Any]] = []
        late_refs: list[str] = []
        for raw in items:
            if not isinstance(raw, dict):
                raise BriefingInvalid("items 元素必须是对象。")
            ref = clean_entry_refs(raw.get("entryRef"))
            if ref in prior and "dupDecision" not in raw:
                pending.append(
                    {
                        "entryRef": ref,
                        "title": str(raw.get("title") or ""),
                        "priorIssues": prior[ref],
                    }
                )
            published = str(
                raw.get("publishedAt")
                or (raw.get("card") or {}).get("publishedAt")
                or ""
            )
            if (
                cutoff_utc
                and published
                and published >= cutoff_utc
                and not raw.get("pullBack")
            ):
                late_refs.append(ref)
        if pending:
            raise DupApprovalRequired(pending)
        if late_refs:
            raise LateEntryRejected(late_refs)
        rows: list[tuple[Any, ...]] = []
        decisions: list[tuple[Any, ...]] = []
        for position, raw in enumerate(items):
            ref = clean_entry_refs(raw.get("entryRef"))
            section_key = raw.get("sectionKey")
            if section_key not in keys:
                raise BriefingInvalid(f"sectionKey 不在栏目定义里：{section_key!r}。")
            provenance = raw.get("provenance", "manual")
            if provenance not in PROVENANCES:
                raise BriefingInvalid("provenance 必须是 manual 或 rule。")
            decision = raw.get("dupDecision")
            if decision is not None and ref in prior:
                if decision not in DUP_DECISIONS:
                    raise BriefingInvalid("dupDecision 必须是 include/defer/skip。")
                decisions.append(
                    (
                        str(_uuid.uuid4()),
                        ref,
                        decision,
                        issue_id,
                        prior[ref][0]["issueId"],
                        now,
                    )
                )
                if decision != "include":
                    continue  # defer/skip：记录决定但不进正文
            card = raw.get("card") or {}
            rows.append(
                (
                    str(_uuid.uuid4()),
                    issue_id,
                    ref,
                    str(raw.get("itemId") or card.get("itemId") or ""),
                    str(raw.get("title") or card.get("title") or ""),
                    str(raw.get("feedTitle") or card.get("feedTitle") or ""),
                    str(raw.get("url") or card.get("url") or ""),
                    str(raw.get("publishedAt") or card.get("publishedAt") or ""),
                    make_excerpt(str(raw.get("excerpt") or card.get("excerpt") or "")),
                    section_key,
                    position,
                    provenance,
                    1 if raw.get("pullBack") else 0,
                    now,
                )
            )
        if not rows:
            raise BriefingInvalid(
                "所有条目都被 defer/skip，本期没有正文（空刊不可创建）。"
            )

        def _tx(conn: sqlite3.Connection) -> None:
            conn.execute(
                "INSERT INTO briefings (id, title, status, range_from,"
                " range_to, sections_json, source, created_at, updated_at)"
                " VALUES (?, ?, 'draft', ?, ?, ?, ?, ?, ?)",
                (
                    issue_id,
                    clean,
                    range_from,
                    range_to,
                    json.dumps(clean_secs, ensure_ascii=False),
                    source,
                    now,
                    now,
                ),
            )
            for row in rows:
                conn.execute(
                    "INSERT INTO briefing_items (id, briefing_id, entry_ref,"
                    " item_id, title, feed_title, url, published_at, excerpt,"
                    " section_key, position, provenance, pulled_back, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    row,
                )
            for decision in decisions:
                conn.execute(
                    "INSERT INTO briefing_dup_decisions (id, entry_ref,"
                    " decision, decided_in_issue, prior_issue, decided_at)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    decision,
                )

        await transaction(self._db, _tx)
        return await self.get_issue(issue_id)

    async def get_issue(self, issue_id: str) -> dict[str, Any]:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, title, status, range_from, range_to, sections_json,"
            " source, created_at, updated_at, confirmed_at FROM briefings"
            " WHERE id = ?",
            (issue_id,),
        )
        if row is None:
            raise BriefingNotFound("期次不存在。")
        items = await self._db.fetch_all(
            "SELECT id, entry_ref, item_id, title, feed_title, url,"
            " published_at, excerpt, section_key, position, provenance,"
            " pulled_back FROM briefing_items WHERE briefing_id = ?"
            " ORDER BY position ASC",
            (issue_id,),
        )
        sections = json.loads(str(row["sections_json"] or "[]"))
        return {
            "id": str(row["id"]),
            "title": str(row["title"]),
            "status": str(row["status"]),
            "rangeFrom": str(row["range_from"]),
            "rangeTo": str(row["range_to"]),
            "source": str(row["source"]),
            "sections": sections,
            "createdAt": str(row["created_at"]),
            "updatedAt": str(row["updated_at"]),
            "confirmedAt": str(row["confirmed_at"] or "") or None,
            "items": [
                {
                    "id": str(item["id"]),
                    "entryRef": str(item["entry_ref"]),
                    "itemId": str(item["item_id"]),
                    "title": str(item["title"]),
                    "feedTitle": str(item["feed_title"]),
                    "url": str(item["url"]),
                    "publishedAt": str(item["published_at"]),
                    "excerpt": str(item["excerpt"]),
                    "sectionKey": str(item["section_key"]),
                    "position": int(item["position"]),
                    "provenance": str(item["provenance"]),
                    "provenanceLabel": provenance_label(str(item["provenance"])),
                    "pulledBack": bool(item["pulled_back"]),
                }
                for item in items
            ],
        }

    async def list_issues(self, *, limit: int = 50) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT b.id, b.title, b.status, b.created_at, b.confirmed_at,"
            " COUNT(bi.id) AS item_count FROM briefings b"
            " LEFT JOIN briefing_items bi ON bi.briefing_id = b.id"
            " GROUP BY b.id ORDER BY b.created_at DESC LIMIT ?",
            (max(1, min(int(limit), 200)),),
        )
        return [
            {
                "id": str(row["id"]),
                "title": str(row["title"]),
                "status": str(row["status"]),
                "createdAt": str(row["created_at"]),
                "confirmedAt": str(row["confirmed_at"] or "") or None,
                "itemCount": int(row["item_count"]),
            }
            for row in rows
        ]

    async def _get_row(self, issue_id: str) -> dict[str, Any]:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, status FROM briefings WHERE id = ?", (issue_id,)
        )
        if row is None:
            raise BriefingNotFound("期次不存在。")
        return dict(row)

    async def update_draft(
        self,
        issue_id: str,
        *,
        title: Any = None,
        sections: Any = None,
        items: Any = None,
    ) -> dict[str, Any]:
        """整稿替换式编辑（只对 draft；确认后的期次不可改——289/290
        的读者面以确认稿为准，静默替换历史是明令禁止的）。"""
        row = await self._get_row(issue_id)
        if row["status"] != "draft":
            raise BriefingStateConflict("已确认的期次不可编辑（请走更正流程）。")
        clean_secs = clean_sections(sections) if sections is not None else None
        if items is not None:
            if not isinstance(items, list) or not items:
                raise BriefingInvalid("items 必须是非空数组（空刊不可保存）。")
            if len(items) > _MAX_ITEMS:
                raise BriefingInvalid(f"一期最多 {_MAX_ITEMS} 条。")
        await self._db.migrate()
        now = utc_now()

        def _tx(conn: sqlite3.Connection) -> None:
            if clean_secs is not None:
                conn.execute(
                    "UPDATE briefings SET sections_json = ?, updated_at = ?"
                    " WHERE id = ?",
                    (json.dumps(clean_secs, ensure_ascii=False), now, issue_id),
                )
            if title is not None:
                conn.execute(
                    "UPDATE briefings SET title = ?, updated_at = ? WHERE id = ?",
                    (clean_title(title), now, issue_id),
                )
            if items is not None:
                keys = {
                    s["key"]
                    for s in json.loads(
                        str(
                            conn.execute(
                                "SELECT sections_json FROM briefings WHERE id = ?",
                                (issue_id,),
                            ).fetchone()["sections_json"]
                        )
                        or "[]"
                    )
                }
                conn.execute(
                    "DELETE FROM briefing_items WHERE briefing_id = ?", (issue_id,)
                )
                for position, raw in enumerate(items):
                    if not isinstance(raw, dict):
                        raise BriefingInvalid("items 元素必须是对象。")
                    ref = clean_entry_refs(raw.get("entryRef"))
                    section_key = raw.get("sectionKey")
                    if section_key not in keys:
                        raise BriefingInvalid(
                            f"sectionKey 不在栏目定义里：{section_key!r}。"
                        )
                    provenance = raw.get("provenance", "manual")
                    if provenance not in PROVENANCES:
                        raise BriefingInvalid("provenance 必须是 manual 或 rule。")
                    conn.execute(
                        "INSERT INTO briefing_items (id, briefing_id, entry_ref,"
                        " item_id, title, feed_title, url, published_at, excerpt,"
                        " section_key, position, provenance, pulled_back, created_at)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            str(_uuid.uuid4()),
                            issue_id,
                            ref,
                            str(raw.get("itemId") or ""),
                            str(raw.get("title") or ""),
                            str(raw.get("feedTitle") or ""),
                            str(raw.get("url") or ""),
                            str(raw.get("publishedAt") or ""),
                            make_excerpt(str(raw.get("excerpt") or "")),
                            section_key,
                            position,
                            provenance,
                            1 if raw.get("pullBack") else 0,
                            now,
                        ),
                    )

        await transaction(self._db, _tx)
        return await self.get_issue(issue_id)

    async def confirm_issue(self, issue_id: str) -> dict[str, Any]:
        await self._db.migrate()
        row = await self._get_row(issue_id)
        if row["status"] == "confirmed":
            raise BriefingStateConflict("期次已确认。")
        count = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM briefing_items WHERE briefing_id = ?",
            (issue_id,),
        )
        if count is None or int(count["n"]) == 0:
            raise BriefingInvalid("空刊不可确认（0 条正文的空白成功页是禁止形态）。")
        now = utc_now()
        await self._db.execute(
            "UPDATE briefings SET status = 'confirmed', confirmed_at = ?,"
            " updated_at = ? WHERE id = ?",
            (now, now, issue_id),
        )
        return await self.get_issue(issue_id)

    async def delete_draft(self, issue_id: str) -> bool:
        await self._db.migrate()
        row = await self._get_row(issue_id)
        if row["status"] != "draft":
            raise BriefingStateConflict("已确认期次不可删除（历史更正走 290）。")

        def _tx(conn: sqlite3.Connection) -> None:
            conn.execute(
                "DELETE FROM briefing_items WHERE briefing_id = ?", (issue_id,)
            )
            conn.execute("DELETE FROM briefings WHERE id = ?", (issue_id,))

        await transaction(self._db, _tx)
        return True

    # ---- 282 后续清单 -----------------------------------------------------

    async def followups(self) -> list[dict[str, Any]]:
        """defer 决定中、此后仍未被任何期次重新收录的条目（仅列后续）。

        「此后」用 briefings.rowid（插入序，单调）判定，不用墙钟——
        同一秒内的建稿/决定次序必须可靠（n271 同秒教训）。
        """
        await self._db.migrate()
        decisions = await self._db.fetch_all(
            "SELECT d.entry_ref, d.decided_at, d.prior_issue, d.decided_in_issue"
            " FROM briefing_dup_decisions d"
            " WHERE d.decision = 'defer' AND d.rowid = ("
            "  SELECT MAX(d2.rowid) FROM briefing_dup_decisions d2"
            "  WHERE d2.entry_ref = d.entry_ref)"
            " ORDER BY d.decided_at DESC"
        )
        result: list[dict[str, Any]] = []
        for decision in decisions:
            ref = str(decision["entry_ref"])
            recalled = await self._db.fetch_one(
                "SELECT COUNT(*) AS n FROM briefing_items bi"
                " JOIN briefings b ON b.id = bi.briefing_id"
                " WHERE bi.entry_ref = ? AND b.rowid > ("
                " SELECT rowid FROM briefings WHERE id = ?)",
                (ref, str(decision["decided_in_issue"])),
            )
            if recalled is not None and int(recalled["n"]) > 0:
                continue  # 已被后续期次收录，不再列
            entry = await self._db.fetch_one(
                "SELECT title, feed_title FROM briefing_items"
                " WHERE entry_ref = ? ORDER BY created_at DESC LIMIT 1",
                (ref,),
            )
            result.append(
                {
                    "entryRef": ref,
                    "title": str(entry["title"]) if entry else "",
                    "feedTitle": str(entry["feed_title"]) if entry else "",
                    "priorIssue": str(decision["prior_issue"] or ""),
                    "deferredAt": str(decision["decided_at"]),
                }
            )
        return result

    # ---- 287 人工精选标记 -------------------------------------------------

    async def flip_provenance(
        self, issue_id: str, item_row_id: str, provenance: Any
    ) -> dict[str, Any]:
        if provenance not in PROVENANCES:
            raise BriefingInvalid("provenance 必须是 manual 或 rule。")
        await self._db.migrate()
        row = await self._get_row(issue_id)
        if row["status"] != "draft":
            raise BriefingStateConflict(
                "已确认期次的编辑来源不可翻转（读者已按确认稿阅读）。"
            )
        existing = await self._db.fetch_one(
            "SELECT id FROM briefing_items WHERE id = ? AND briefing_id = ?",
            (item_row_id, issue_id),
        )
        if existing is None:
            raise BriefingNotFound("条目不存在。")
        await self._db.execute(
            "UPDATE briefing_items SET provenance = ? WHERE id = ?",
            (provenance, item_row_id),
        )
        return await self.get_issue(issue_id)

    async def suggestions(
        self, range_from: str, range_to: str, *, rule: str, feed_url: str | None = None
    ) -> list[dict[str, Any]]:
        """规则推荐（确定性，零 AI）：starred / recent / feed。

        返回的卡片 provenance 恒为 'rule'——推荐归推荐，选不选由用户；
        一旦用户采纳，编辑来源如实保留为「规则推荐」，读者可见（287）。
        """
        if rule not in ("starred", "recent", "feed"):
            raise BriefingInvalid("rule 必须是 starred/recent/feed。")
        if rule == "feed" and not feed_url:
            raise BriefingInvalid("rule=feed 时 feedUrl 必填。")
        if not range_from or not range_to:
            raise BriefingInvalid("from 与 to 都是必填（ISO 时间）。")
        if range_from >= range_to:
            raise BriefingInvalid("from 必须早于 to。")
        await self._db.migrate()
        sql = (
            "SELECT entry_ref, item_id, title, feed_title, feed_url, url,"
            " published_at, content_text FROM search_entries"
            " WHERE published_at >= ? AND published_at < ?"
        )
        params: list[Any] = [range_from, range_to]
        if rule == "starred":
            sql += " AND starred = 1"
        if rule == "feed":
            sql += " AND feed_url = ?"
            params.append(feed_url)
        sql += " ORDER BY published_at DESC, id DESC LIMIT 10"
        rows = await self._db.fetch_all(sql, params)
        return [
            {
                "entryRef": str(row["entry_ref"]),
                "itemId": str(row["item_id"]),
                "title": str(row["title"]),
                "feedTitle": str(row["feed_title"]),
                "url": str(row["url"]),
                "publishedAt": str(row["published_at"]),
                "excerpt": make_excerpt(str(row["content_text"])),
                "provenance": "rule",
                "provenanceLabel": provenance_label("rule"),
                "rule": rule,
            }
            for row in rows
        ]
