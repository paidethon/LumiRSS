"""Newsletter inbound bridge (phase2 G5).

Chain: email → authenticated thin webhook → parse/sanitize → per-list
Atom → FreshRSS (same main chain as API sources; no second article
database). Lists live in Lumi with a high-entropy per-list bearer
secret; seen Message-IDs and content fingerprints give replay/dedupe
protection; attachments are counted (name+size) but their bodies are
NEVER stored. The per-list Atom reuses the api_sources feed URL pattern
(outside /api/*, secret constant-time compared) and is auto-subscribed
into FreshRSS best-effort.
"""

import email
import email.header
import email.policy
import hashlib
import hmac
import json
import secrets as _secrets
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


def _fingerprint(list_uuid: str, message_id: str, body: str) -> str:
    return hashlib.sha256(
        f"{list_uuid}\n{message_id}\n{body}".encode()
    ).hexdigest()


class MailBridgeStore:
    """Lists + seen ledger + per-list entry ring (for the Atom)."""

    def __init__(self, db: Database) -> None:
        self._db = db

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
        row = await self._db.fetch_one(
            "SELECT uuid FROM mail_bridge_lists WHERE uuid = ?", (list_uuid,)
        )
        if row is None:
            return False
        await self._db.execute(
            "DELETE FROM mail_seen WHERE list_uuid = ?", (list_uuid,)
        )
        await self._db.execute(
            "DELETE FROM mail_bridge_entries WHERE list_uuid = ?", (list_uuid,)
        )
        await self._db.execute(
            "DELETE FROM mail_bridge_lists WHERE uuid = ?", (list_uuid,)
        )
        return True

    def secrets_match(self, supplied: str, lst: BridgeList) -> bool:
        return hmac.compare_digest(supplied, lst.secret)

    # -- ingest ------------------------------------------------------------

    async def ingest(
        self, lst: BridgeList, raw_bytes: bytes
    ) -> dict[str, Any]:
        """Parse a raw MIME message, sanitize, dedupe, store the entry.

        Returns an honest per-message report; duplicate messages are
        reported (never fatal) so upstream retries converge.
        """
        if len(raw_bytes) > _MAX_RAW_BYTES:
            raise MailBridgeInvalid("Message exceeds the 10MB limit.")
        message = email.message_from_bytes(
            raw_bytes, policy=email.policy.default
        )
        message_id = _decode_header(message.get("Message-ID", "")) or _fingerprint(
            lst.uuid, utc_now(), str(message.get("Subject", ""))
        )[:32]
        seen = await self._db.fetch_one(
            "SELECT message_id FROM mail_seen WHERE message_id = ?",
            (message_id,),
        )
        if seen is not None:
            return {"status": "duplicate", "messageId": message_id}
        subject = _decode_header(message.get("Subject", "")) or "(无主题)"
        sender = _decode_header(message.get("From", ""))
        html_part, text_part = _extract_bodies(message)
        body_source = html_part if html_part else (text_part or "")
        clean_html = sanitize_email_html(body_source)
        clean_text = html_to_text(body_source) if html_part else (text_part or "")
        attachments = _attachment_metadata(message)
        fingerprint = _fingerprint(lst.uuid, message_id, clean_text)
        fingerprint_seen = await self._db.fetch_one(
            "SELECT message_id FROM mail_seen WHERE message_id = ?",
            (fingerprint,),
        )
        if fingerprint_seen is not None:
            return {"status": "duplicate", "messageId": fingerprint[:32]}
        now = utc_now()
        await self._db.execute(
            "INSERT INTO mail_seen (message_id, list_uuid, seen_at) VALUES (?, ?, ?)",
            (message_id, lst.uuid, now),
        )
        await self._db.execute(
            "INSERT INTO mail_seen (message_id, list_uuid, seen_at) VALUES (?, ?, ?)",
            (fingerprint, lst.uuid, now),
        )
        await self._db.execute(
            "INSERT INTO mail_bridge_entries (list_uuid, message_id, subject, sender, html, text, attachment_count, attachment_meta, received_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                lst.uuid,
                message_id,
                subject[:500],
                sender[:200],
                clean_html[:200_000],
                clean_text[:100_000],
                len(attachments),
                json.dumps(attachments, ensure_ascii=False),
                now,
            ),
        )
        await self._trim_ring(lst.uuid)
        return {
            "status": "accepted",
            "messageId": message_id,
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
