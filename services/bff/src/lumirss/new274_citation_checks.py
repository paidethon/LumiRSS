"""NEW-274 AI 结果引用核验 —— 对回答中的引用逐条定位原文。

- 每条引用 = {index, entryRef, claim（被引述的原文片段，≤300 字符）}；
  定位 = 在该文章的规范化正文里做「字面子串匹配」——命中 → found
  （带 excerpt 与 offset）；文章取不到 → entry_unavailable；取到但
  找不到 → not_found；
- 诚实口径：字面匹配不理解为语义——改写/转述过的引用可能定位不到；
  本功能绝不声称「自动核验一切引用」，逐条结果由用户判读；
- 「已核对」必须经用户显式确认：存在未定位引用时必须带
  confirmMissing=true 才能置 checked（服务端强制，防止一键漂白）。

per-user：核验台账在 per-user 库；文章读取经该用户自己的 FreshRSS
绑定——A 引用 B 不可见的文章时如实 entry_unavailable。
"""

import json
import uuid
from dataclasses import dataclass
from typing import Any

from lumirss.adapters.freshrss import FreshRSSAdapter
from lumirss.ai_artifacts import normalize_ai_content
from lumirss.storage import Database
from lumirss.util import utc_now

MAX_ANSWER_CHARS = 20000
MAX_CITATIONS = 20
MAX_CLAIM_CHARS = 300
_EXCERPT_CONTEXT = 40

_COLUMNS = "id, answer_text, citations, checked, confirmed_missing, created_at, checked_at"


class CitationInvalid(ValueError):
    """核验负载非法（映射 422）。"""


class CitationCheckNotFound(Exception):
    """核验台账不存在（映射 404）。"""


class CitationConfirmationRequired(Exception):
    """存在未定位引用且未带 confirmMissing=true（映射 422）。

   携带 missing 数量；「用户确认后才能标为已核对」的服务端闸门。"""

    def __init__(self, missing: int) -> None:
        super().__init__(f"{missing} 条引用未能定位。")
        self.missing = missing


@dataclass(frozen=True)
class Citation:
    index: int
    entry_ref: str
    claim: str
    status: str  # found | not_found | entry_unavailable
    excerpt: str
    offset: int


class CitationCheckStore:
    def __init__(self, db: Database, adapter: FreshRSSAdapter) -> None:
        self._db = db
        self._adapter = adapter

    async def run_check(
        self, answer_text: Any, citations: Any
    ) -> dict[str, Any]:
        """逐条定位（每条引用一次文章读取，命中即记录字面证据）。"""
        clean_answer = _clean_answer(answer_text)
        clean_citations = _clean_citations(citations)
        checked: list[Citation] = []
        for citation in clean_citations:
            checked.append(await self._locate(citation))
        return await self._insert(
            answer_text=clean_answer,
            citations=checked,
        )

    async def _locate(self, citation: dict[str, str]) -> Citation:
        from lumirss.adapters.freshrss import EntryNotFound
        from lumirss.entryref import decode_entry_ref

        try:
            item_id = decode_entry_ref(citation["entryRef"])
        except Exception:
            return Citation(
                index=int(citation["index"]),
                entry_ref=citation["entryRef"],
                claim=citation["claim"],
                status="entry_unavailable",
                excerpt="",
                offset=-1,
            )
        try:
            detail = await self._adapter.get_entry(item_id)
        except EntryNotFound:
            return Citation(
                index=int(citation["index"]),
                entry_ref=citation["entryRef"],
                claim=citation["claim"],
                status="entry_unavailable",
                excerpt="",
                offset=-1,
            )
        body = normalize_ai_content(detail.contentText)
        claim = citation["claim"]
        offset = body.find(claim)
        if offset < 0:
            return Citation(
                index=int(citation["index"]),
                entry_ref=citation["entryRef"],
                claim=claim,
                status="not_found",
                excerpt="",
                offset=-1,
            )
        start = max(0, offset - _EXCERPT_CONTEXT)
        end = min(len(body), offset + len(claim) + _EXCERPT_CONTEXT)
        return Citation(
            index=int(citation["index"]),
            entry_ref=citation["entryRef"],
            claim=claim,
            status="found",
            excerpt=(
                ("…" if start > 0 else "")
                + body[start:end]
                + ("…" if end < len(body) else "")
            ),
            offset=offset,
        )

    async def mark_checked(
        self, check_id: str, *, confirm_missing: bool = False
    ) -> dict[str, Any]:
        """标为已核对（存在未定位引用时必须显式确认）。"""
        check = await self.get_check(check_id)
        missing = sum(
            1
            for item in check["citations"]
            if item["status"] in ("not_found", "entry_unavailable")
        )
        if missing > 0 and not confirm_missing:
            raise CitationConfirmationRequired(missing)
        await self._db.execute(
            "UPDATE ai_citation_checks SET checked = 1, confirmed_missing = ?, "
            "checked_at = ? WHERE id = ?",
            (1 if missing > 0 else 0, utc_now(), check_id),
        )
        return await self.get_check(check_id)

    async def list_checks(self, limit: int = 20) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            f"SELECT {_COLUMNS} FROM ai_citation_checks "
            "ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (max(1, min(limit, 100)),),
        )
        return [_row(row) for row in rows]

    async def get_check(self, check_id: str) -> dict[str, Any]:
        await self._db.migrate()
        row = await self._db.fetch_one(
            f"SELECT {_COLUMNS} FROM ai_citation_checks WHERE id = ?",
            (check_id,),
        )
        if row is None:
            raise CitationCheckNotFound(check_id)
        return _row(row)

    async def _insert(
        self, *, answer_text: str, citations: list[Citation]
    ) -> dict[str, Any]:
        await self._db.migrate()
        check_id = uuid.uuid4().hex[:20]
        payload = json.dumps(
            [
                {
                    "index": c.index,
                    "entryRef": c.entry_ref,
                    "claim": c.claim,
                    "status": c.status,
                    "excerpt": c.excerpt,
                    "offset": c.offset,
                }
                for c in citations
            ],
            ensure_ascii=False,
        )
        await self._db.execute(
            "INSERT INTO ai_citation_checks (id, answer_text, citations, "
            "checked, confirmed_missing, created_at, checked_at) "
            "VALUES (?, ?, ?, 0, 0, ?, NULL)",
            (check_id, answer_text, payload, utc_now()),
        )
        return await self.get_check(check_id)


def _clean_answer(raw: Any) -> str:
    if not isinstance(raw, str) or not raw.strip():
        raise CitationInvalid("answerText 必填。")
    return raw.strip()[:MAX_ANSWER_CHARS]


def _clean_citations(raw: Any) -> list[dict[str, str]]:
    if not isinstance(raw, list) or not (1 <= len(raw) <= MAX_CITATIONS):
        raise CitationInvalid(f"citations 必须是 1..{MAX_CITATIONS} 条。")
    cleaned: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            raise CitationInvalid("citations 的元素必须是对象。")
        index = item.get("index")
        entry_ref = item.get("entryRef")
        claim = item.get("claim")
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise CitationInvalid("citations.index 必须是非负整数。")
        if not isinstance(entry_ref, str) or not entry_ref.strip():
            raise CitationInvalid("citations.entryRef 必填。")
        if not isinstance(claim, str) or not claim.strip():
            raise CitationInvalid("citations.claim 必填（被引述的原文片段）。")
        cleaned.append(
            {
                "index": str(index),
                "entryRef": entry_ref.strip(),
                "claim": claim.strip()[:MAX_CLAIM_CHARS],
            }
        )
    return cleaned


def _row(row: Any) -> dict[str, Any]:
    try:
        citations = json.loads(str(row["citations"] or "[]"))
    except json.JSONDecodeError:
        citations = []
    if not isinstance(citations, list):
        citations = []
    missing = sum(
        1
        for item in citations
        if isinstance(item, dict)
        and item.get("status") in ("not_found", "entry_unavailable")
    )
    return {
        "id": str(row["id"]),
        "answerText": str(row["answer_text"]),
        "citations": citations,
        "checked": bool(row["checked"]),
        "confirmedMissing": bool(row["confirmed_missing"]),
        "missingCount": missing,
        "createdAt": str(row["created_at"]),
        "checkedAt": row["checked_at"],
        "honestyNote": (
            "定位是字面子串匹配：改写或转述过的引用可能找不到；"
            "逐条结果请人工判读，系统不会自动核验一切引用。"
        ),
    }
