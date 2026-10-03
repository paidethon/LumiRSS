"""Newsletter send ledger (R19 已发送内容页的数据真源).

One row per outbound digest send ATTEMPT (written by
``mail_digest.deliver_digest``): a ``sent`` row keeps the exact body
snapshot (text/html) so the sent-content page can re-show what actually
went out; a ``failed`` row keeps the typed error and the per-recipient
ledger so a retry targets ONLY recipients never recorded as sent — a
retried send never re-delivers to a recipient that already got it.

``dedupe_key`` makes scheduled sends idempotent across recovery paths:
it mirrors the DigestScheduler hour-window lease scope and the partial
unique index turns a second completion of the same window into an
UPDATE of the same row (same convention as the gpt_digest issue_key).
``''`` (manual sends) never dedupes — every explicit send is its own
row. Retries always write back to their original row (``row_id``),
merging the per-recipient ledger by address.

Recipient addresses live verbatim in the per-user SQLite for retry
accounting and NEVER in logs; the API layer masks them for non-admin
principals (local-part first char + ``***``).
"""

import json
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

_LIST_LIMIT = 50


def parse_recipients(raw: Any) -> list[dict[str, Any]]:
    """recipients_json 列 → 账目列表（畸形数据诚实为空，不抛错）。"""
    if not raw:
        return []
    try:
        parsed = json.loads(str(raw))
    except ValueError:
        return []
    if not isinstance(parsed, list):
        return []
    return [entry for entry in parsed if isinstance(entry, dict)]


def merge_recipients(base: list[dict[str, Any]], results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按地址合并逐收件人账目：新结果覆盖同地址旧状态（重试语义）。

    已 sent 的地址绝不被降级——重试结果只可能把 failed 翻成 sent，
    或把新的失败原因写上。"""
    merged: dict[str, dict[str, Any]] = {
        str(entry.get("address") or ""): dict(entry) for entry in base
    }
    for result in results:
        address = str(result.get("address") or "")
        current = merged.get(address)
        if current is not None and current.get("status") == "sent":
            continue
        merged[address] = {
            "address": address,
            "status": str(result.get("status") or "failed"),
            "error": str(result.get("error") or ""),
            "providerRef": str(result.get("providerRef") or ""),
            "sentAt": result.get("sentAt"),
        }
    return [merged[key] for key in merged]


class NewsletterIssueStore:
    """Outbound digest send ledger on the per-user SQLite."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def record_result(
        self,
        *,
        subject: str,
        source: str,
        origin: str,
        status: str,
        recipients: list[dict[str, Any]],
        item_count: int,
        dedupe_key: str = "",
        items_json: str = "[]",
        text: str | None = None,
        html: str | None = None,
        provider_receipt: str = "",
        error: str | None = None,
        sent_at: str | None = None,
        row_id: int | None = None,
    ) -> int:
        """写入一次发送结果；返回该行 id。

        行定位优先级：显式 ``row_id``（重试回写原行）→ ``dedupe_key``
        命中的既有行（调度窗口补写 → UPDATE 同一行）→ 新 INSERT。
        ``status='sent'`` 落正文快照并清空 error；``'failed'`` 不落
        快照（正文从未送达），bodyAvailable 由此诚实为 False。
        """
        await self._db.migrate()
        now = utc_now()
        if row_id is None and dedupe_key:
            existing = await self._db.fetch_one(
                "SELECT id FROM newsletter_issues WHERE dedupe_key = ?",
                (dedupe_key,),
            )
            row_id = int(existing["id"]) if existing is not None else None
        recipients_json = json.dumps(recipients, ensure_ascii=False)
        values: tuple[Any, ...] = (
            subject,
            source,
            origin,
            status,
            text,
            html,
            items_json,
            provider_receipt,
            item_count,
            len(recipients),
            recipients_json,
            error,
            sent_at,
            now,
        )
        if row_id is not None:
            await self._db.execute(
                "UPDATE newsletter_issues SET subject = ?, source = ?, origin = ?, status = ?, body_text = ?, body_html = ?, items_json = ?, provider_receipt = ?, item_count = ?, recipient_count = ?, recipients_json = ?, error = ?, sent_at = ?, updated_at = ? WHERE id = ?",
                values + (int(row_id),),
            )
            return int(row_id)
        new_id = await self._db.execute(
            "INSERT INTO newsletter_issues (subject, source, origin, status, body_text, body_html, items_json, provider_receipt, item_count, recipient_count, recipients_json, error, sent_at, updated_at, dedupe_key, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            values + (dedupe_key, now),
        )
        return int(new_id or 0)

    async def list_issues(
        self, status: str | None = None, limit: int = _LIST_LIMIT
    ) -> list[dict[str, Any]]:
        """新→旧的有界清单（不含正文快照列）。"""
        await self._db.migrate()
        bound = max(1, min(int(limit), _LIST_LIMIT))
        if status is not None:
            rows = await self._db.fetch_all(
                "SELECT id, subject, source, origin, status, item_count, recipient_count, error, created_at, sent_at, updated_at, (body_text IS NOT NULL OR body_html IS NOT NULL) AS has_body FROM newsletter_issues WHERE status = ? ORDER BY created_at DESC, id DESC LIMIT ?",
                (status, bound),
            )
        else:
            rows = await self._db.fetch_all(
                "SELECT id, subject, source, origin, status, item_count, recipient_count, error, created_at, sent_at, updated_at, (body_text IS NOT NULL OR body_html IS NOT NULL) AS has_body FROM newsletter_issues ORDER BY created_at DESC, id DESC LIMIT ?",
                (bound,),
            )
        return [dict(row) for row in rows]

    async def get_issue(self, issue_id: int) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, subject, source, origin, status, body_text, body_html, items_json, dedupe_key, provider_receipt, item_count, recipient_count, recipients_json, error, created_at, sent_at, updated_at FROM newsletter_issues WHERE id = ?",
            (int(issue_id),),
        )
        return dict(row) if row is not None else None

    async def count_pending_recipients(self, issue_id: int) -> tuple[int, int]:
        """（未成功收件数, 总收件数）——重试前的诚实账目。"""
        issue = await self.get_issue(issue_id)
        if issue is None:
            return (0, 0)
        recipients = parse_recipients(issue["recipients_json"])
        pending = [e for e in recipients if str(e.get("status") or "") != "sent"]
        return (len(pending), len(recipients))
