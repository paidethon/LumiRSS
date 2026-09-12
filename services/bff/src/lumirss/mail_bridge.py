"""Newsletter inbound bridge (phase2 G5, recovery P0-06).

Chain: email → authenticated thin webhook → parse/sanitize → per-list
Atom → FreshRSS (same main chain as API sources; no second article
database). Lists live in Lumi with a high-entropy per-list bearer
secret; seen identities are PER-LIST (mail_seen PK (list_uuid, identity)
since migration 0018 — the same Message-ID to two lists must store
twice) and the fallback identity is a stable content fingerprint (list
+ from + to + subject + body digest — never wall-clock, so re-delivery
dedupes deterministically). Seen rows and the entry body commit in ONE
transaction: a crash in between must not lose the mail forever (the
entry table doubles as the bounded delivery spool per ADR 0004).
Attachments are counted (name+size) but their bodies are NEVER stored.
The per-list Atom reuses the api_sources feed URL pattern (outside
/api/*, secret constant-time compared) and is auto-subscribed into
FreshRSS best-effort.
"""

import asyncio
import email
import email.header
import email.policy
import hashlib
import hmac
import json
import secrets as _secrets
import sqlite3
from dataclasses import dataclass
from typing import Any

from lumirss.mail_sanitize import html_to_text, sanitize_email_html
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_RAW_BYTES = 10 * 1024 * 1024
_MAX_PARTS = 40
_MAX_ATTACHMENT_META = 20
_MAX_ENTRIES_PER_LIST = 50
_MAX_LISTS = 20
_MAX_DIGEST_REFS = 50


class MailBridgeInvalid(ValueError):
    """Ingest payload failed structural validation."""


class MailBridgeNotFound(Exception):
    """No such list (or bad secret)."""


@dataclass(frozen=True)
class BridgeList:
    uuid: str
    name: str
    secret: str
    created_at: str

    def to_dict(self, *, with_address: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "uuid": self.uuid,
            "name": self.name,
            "createdAt": self.created_at,
        }
        if with_address:
            payload["secret"] = self.secret
        return payload


def new_list_secret() -> str:
    return _secrets.token_hex(20)


def _content_fingerprint(
    list_uuid: str, sender: str, recipient: str, subject: str, body_text: str
) -> str:
    """Stable content identity (P0-06e): list-scoped, never wall-clock.

    The same content re-delivered to the same list dedupes at any time;
    the same content to ANOTHER list hashes differently (list_uuid in the
    digest) and is stored independently."""
    digest = hashlib.sha256()
    for part in (list_uuid, sender, recipient, subject, body_text):
        digest.update(part.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


class MailBridgeStore:
    """Lists + seen ledger + per-list entry ring (for the Atom).

    The store also owns the domain's only multi-statement transaction
    helper: storage.Database commits per execute site by design, but the
    ingest path must not lose mail when it crashes between the dedupe
    row and the entry body (P0-06f)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def _transaction(
        self, statements: list[tuple[str, tuple[Any, ...]]]
    ) -> None:
        """Commit every statement or none of them.

        Local helper over the same connection primitives storage.Database
        uses (mirrors migrations.py, which shares the private connector
        for the same reason: one file, one transaction boundary)."""

        def _run() -> None:
            connection = self._db._connect()  # noqa: SLF001 — same module family
            try:
                for sql, params in statements:
                    connection.execute(sql, params)
                connection.commit()
            finally:
                connection.close()

        await asyncio.to_thread(_run)

    # -- lists -------------------------------------------------------------

    async def create_list(self, name: str) -> BridgeList:
        await self._db.migrate()
        clean = name.strip()
        if not clean or len(clean) > 100:
            raise MailBridgeInvalid("List name must be 1-100 characters.")
        count = await self._db.fetch_one("SELECT COUNT(*) AS n FROM mail_bridge_lists")
        if count is not None and int(count["n"]) >= _MAX_LISTS:
            raise MailBridgeInvalid(f"Too many lists (max {_MAX_LISTS}).")
        list_uuid, secret, now = _new_uuid(), new_list_secret(), utc_now()
        await self._db.execute(
            "INSERT INTO mail_bridge_lists (uuid, name, secret, created_at) VALUES (?, ?, ?, ?)",
            (list_uuid, clean, secret, now),
        )
        return BridgeList(uuid=list_uuid, name=clean, secret=secret, created_at=now)

    async def list_lists(self) -> list[BridgeList]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT uuid, name, secret, created_at FROM mail_bridge_lists ORDER BY created_at ASC"
        )
        return [BridgeList(str(r["uuid"]), str(r["name"]), str(r["secret"]), str(r["created_at"])) for r in rows]

    async def get_list(self, list_uuid: str) -> BridgeList | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT uuid, name, secret, created_at FROM mail_bridge_lists WHERE uuid = ?",
            (list_uuid,),
        )
        if row is None:
            return None
        return BridgeList(str(row["uuid"]), str(row["name"]), str(row["secret"]), str(row["created_at"]))

    async def delete_list(self, list_uuid: str) -> bool:
        """Remove a list and ALL its bridge state in one transaction."""
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT uuid FROM mail_bridge_lists WHERE uuid = ?", (list_uuid,)
        )
        if row is None:
            return False
        await self._transaction(
            [
                ("DELETE FROM mail_seen WHERE list_uuid = ?", (list_uuid,)),
                ("DELETE FROM mail_bridge_entries WHERE list_uuid = ?", (list_uuid,)),
                ("DELETE FROM mail_bridge_lists WHERE uuid = ?", (list_uuid,)),
            ]
        )
        return True

    def secrets_match(self, supplied: str, lst: BridgeList) -> bool:
        return hmac.compare_digest(supplied, lst.secret)

    # -- ingest ------------------------------------------------------------

    async def ingest(
        self, lst: BridgeList, raw_bytes: bytes
    ) -> dict[str, Any]:
        """Parse a raw MIME message, sanitize, dedupe, store the entry.

        Dedupe identities are PER-LIST (P0-06e): the Message-ID when the
        mail carries one, plus a stable content fingerprint as the
        same-content-different-id guard. Seen rows + the entry body are
        written in ONE transaction (P0-06f) — a crash between them rolls
        back together, so delivery can be retried without losing the
        mail. Concurrent duplicate inserts are rejected by the composite
        primary key and reported as an honest duplicate. Returns an
        honest per-message report; duplicates are never fatal so
        upstream retries converge."""
        if len(raw_bytes) > _MAX_RAW_BYTES:
            raise MailBridgeInvalid("Message exceeds the 10MB limit.")
        message = email.message_from_bytes(
            raw_bytes, policy=email.policy.default
        )
        subject = _decode_header(message.get("Subject", "")) or "(无主题)"
        sender = _decode_header(message.get("From", ""))
        recipient = _decode_header(message.get("To", ""))
        html_part, text_part = _extract_bodies(message)
        body_source = html_part if html_part else (text_part or "")
        clean_html = sanitize_email_html(body_source)
        clean_text = html_to_text(body_source) if html_part else (text_part or "")
        attachments = _attachment_metadata(message)
        message_id = _decode_header(message.get("Message-ID", ""))
        fingerprint = _content_fingerprint(
            lst.uuid, sender, recipient, subject, clean_text
        )
        identities = ([message_id] if message_id else []) + [fingerprint]
        for identity in identities:
            seen = await self._db.fetch_one(
                "SELECT identity FROM mail_seen WHERE list_uuid = ? AND identity = ?",
                (lst.uuid, identity),
            )
            if seen is not None:
                return {"status": "duplicate", "messageId": identity[:64]}
        now = utc_now()
        statements: list[tuple[str, tuple[Any, ...]]] = [
            (
                "INSERT INTO mail_seen (list_uuid, identity, seen_at) VALUES (?, ?, ?)",
                (lst.uuid, identity, now),
            )
            for identity in identities
        ]
        statements.append(
            (
                "INSERT INTO mail_bridge_entries (list_uuid, message_id, subject, sender, html, text, attachment_count, attachment_meta, received_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    lst.uuid,
                    message_id or fingerprint[:32],
                    subject[:500],
                    sender[:200],
                    clean_html[:200_000],
                    clean_text[:100_000],
                    len(attachments),
                    json.dumps(attachments, ensure_ascii=False),
                    now,
                ),
            )
        )
        try:
            await self._transaction(statements)
        except sqlite3.IntegrityError:
            # A concurrent delivery of the same mail won the race; the
            # transaction rolled back — report honestly, store nothing twice.
            return {"status": "duplicate", "messageId": identities[0][:64]}
        await self._trim_ring(lst.uuid)
        return {
            "status": "accepted",
            "messageId": message_id or fingerprint[:32],
            "subject": subject,
            "attachments": len(attachments),
        }

    async def list_entries(self, list_uuid: str) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT message_id, subject, sender, html, text, attachment_count, attachment_meta, received_at FROM mail_bridge_entries WHERE list_uuid = ? ORDER BY received_at DESC LIMIT ?",
            (list_uuid, _MAX_ENTRIES_PER_LIST),
        )
        return [dict(row) for row in rows]

    async def recent_digest_items(self, limit: int) -> list[dict[str, Any]]:
        """Server-derived digest pool (P0-06b/k): newest entries across
        ALL bridge lists, bounded — the digest is built from what the
        bridge actually received, never from client-supplied text."""
        await self._db.migrate()
        bounded = max(1, min(int(limit), _MAX_DIGEST_REFS))
        rows = await self._db.fetch_all(
            "SELECT e.message_id, e.subject, e.sender, e.received_at, l.name AS list_name FROM mail_bridge_entries e JOIN mail_bridge_lists l ON l.uuid = e.list_uuid ORDER BY e.received_at DESC LIMIT ?",
            (bounded,),
        )
        return [dict(row) for row in rows]

    async def entries_by_ids(self, message_ids: list[str]) -> list[dict[str, Any]]:
        """Resolve explicit digest references against stored entries only.

        Unknown ids are skipped (never invented); lookups are per-id
        bounded queries (SQL stays a single-line literal at each site)."""
        await self._db.migrate()
        found: list[dict[str, Any]] = []
        for message_id in message_ids[:_MAX_DIGEST_REFS]:
            if not message_id:
                continue
            row = await self._db.fetch_one(
                "SELECT e.message_id, e.subject, e.sender, e.received_at, l.name AS list_name FROM mail_bridge_entries e JOIN mail_bridge_lists l ON l.uuid = e.list_uuid WHERE e.message_id = ?",
                (message_id,),
            )
            if row is not None:
                found.append(dict(row))
        return found

    async def _trim_ring(self, list_uuid: str) -> None:
        row = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM mail_bridge_entries WHERE list_uuid = ?",
            (list_uuid,),
        )
        count = int(row["n"]) if row is not None else 0
        if count <= _MAX_ENTRIES_PER_LIST:
            return
        await self._db.execute(
            "DELETE FROM mail_bridge_entries WHERE list_uuid = ? AND message_id NOT IN (SELECT message_id FROM mail_bridge_entries WHERE list_uuid = ? ORDER BY received_at DESC LIMIT ?)",
            (list_uuid, list_uuid, _MAX_ENTRIES_PER_LIST),
        )


def _new_uuid() -> str:
    import uuid as _uuid

    return str(_uuid.uuid4())


def _decode_header(value: Any) -> str:
    if value is None:
        return ""
    try:
        return str(value)
    except Exception:
        return ""


def _extract_bodies(message: email.message.Message) -> tuple[str | None, str | None]:
    """Extract text/html and text/plain parts (never attachments)."""
    html_body: str | None = None
    text_body: str | None = None
    part_count = 0
    for part in message.walk():
        part_count += 1
        if part_count > _MAX_PARTS:
            break
        if part.get_content_maintype() == "multipart":
            continue
        if part.get_content_disposition() == "attachment":
            continue
        content_type = part.get_content_type()
        try:
            payload = part.get_content()
        except Exception:
            continue
        if not isinstance(payload, str):
            continue
        if content_type == "text/html" and html_body is None:
            html_body = payload
        elif content_type == "text/plain" and text_body is None:
            text_body = payload
    return html_body, text_body


def _attachment_metadata(message: email.message.Message) -> list[dict[str, Any]]:
    meta: list[dict[str, Any]] = []
    for part in message.walk():
        if part.get_content_disposition() != "attachment":
            continue
        if len(meta) >= _MAX_ATTACHMENT_META:
            break
        try:
            size = len(part.get_payload(decode=True) or b"")
        except Exception:
            size = -1
        meta.append(
            {
                "filename": part.get_filename() or "(unnamed)",
                "bytes": size,
            }
        )
    return meta
