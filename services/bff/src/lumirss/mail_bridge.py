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

import email
import email.header
import email.policy
import hashlib
import json
import secrets as _secrets
import sqlite3
from dataclasses import dataclass
from typing import Any

from lumirss.db_tx import transaction
from lumirss.mail_sanitize import html_to_text, sanitize_email_html
from lumirss.storage import Database
from lumirss.token_hash import hash_token, verify_token
from lumirss.util import utc_now

_MAX_RAW_BYTES = 10 * 1024 * 1024
_MAX_PARTS = 40
_MAX_ATTACHMENT_META = 20
_MAX_ENTRIES_PER_LIST = 50
_MAX_LISTS = 20
_MAX_DIGEST_REFS = 50
_MAX_STRUCTURE_BYTES = 2048  # F104：结构快照 JSON 上界（超出截断并标记）


class MailBridgeInvalid(ValueError):
    """Ingest payload failed structural validation."""


class MailBridgeDenied(Exception):
    """F105：邮件被该列表的接收规则拒绝（deny）——不入 feed。"""

    def __init__(self, rule_id: int, field: str, op: str, value: str) -> None:
        super().__init__("denied by mail rule")
        self.rule_id = rule_id
        self.field = field
        self.op = op
        self.value = value


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

    Multi-statement writes go through ``db_tx.transaction`` (one
    connection, one commit, rollback on failure, raw IntegrityError
    propagated): the ingest path must not lose mail when it crashes
    between the dedupe row and the entry body (P0-06f)."""

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
        # §13.4：只存哈希；明文仅存于本次返回（创建响应一次性展示）。
        await self._db.execute(
            "INSERT INTO mail_bridge_lists (uuid, name, secret, created_at, secret_is_hash) VALUES (?, ?, ?, ?, 1)",
            (list_uuid, clean, hash_token(secret), now),
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

    async def increment_skipped(self, list_uuid: str) -> None:
        """F105：deny 计数（独立计数列；如实留痕，不入 feed）。"""
        await self._db.migrate()
        await self._db.execute(
            "UPDATE mail_bridge_lists SET skipped_count = skipped_count + 1 WHERE uuid = ?",
            (list_uuid,),
        )

    async def skipped_count(self, list_uuid: str) -> int:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT skipped_count FROM mail_bridge_lists WHERE uuid = ?",
            (list_uuid,),
        )
        return int(row["skipped_count"]) if row is not None else 0

    async def delete_list(self, list_uuid: str) -> bool:
        """Remove a list and ALL its bridge state in one transaction."""
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT uuid FROM mail_bridge_lists WHERE uuid = ?", (list_uuid,)
        )
        if row is None:
            return False

        def _run(connection: sqlite3.Connection) -> None:
            connection.execute(
                "DELETE FROM mail_seen WHERE list_uuid = ?", (list_uuid,)
            )
            connection.execute(
                "DELETE FROM mail_bridge_entries WHERE list_uuid = ?",
                (list_uuid,),
            )
            connection.execute(
                "DELETE FROM mail_bridge_lists WHERE uuid = ?", (list_uuid,)
            )

        await transaction(self._db, _run)
        return True

    def secrets_match(self, supplied: str, lst: BridgeList) -> bool:
        # §13.4：存储值为 SHA-256（旧明文行走兼容分支）。
        return verify_token(supplied, lst.secret)

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
        # F105：首条命中规则决定 allow/deny（无规则 = allow）；deny 邮件
        # 不入 feed、不写 seen（重投递仍会被再次拒绝并计数——诚实）。
        from lumirss.mail_rules import MailRuleStore, first_matching_rule

        rules = await MailRuleStore(self._db).list_rules(lst.uuid, enabled_only=True)
        matched = first_matching_rule(rules, sender=sender, subject=subject)
        if matched is not None and matched["action"] == "deny":
            await self.increment_skipped(lst.uuid)
            return {
                "status": "denied",
                "ruleId": int(matched["id"]),
                "field": str(matched["field"]),
            }
        html_part, text_part = _extract_bodies(message)
        body_source = html_part if html_part else (text_part or "")
        clean_html = sanitize_email_html(body_source)
        clean_text = html_to_text(body_source) if html_part else (text_part or "")
        attachments = _attachment_metadata(message)
        # F104/F110：Message-ID 归一化（去尖括号、仅保留 token@token 形态）
        # ——同时用作去重身份、条目身份与会话串联键（URL 友好、可比较）。
        message_id = _first_msg_id(message.get("Message-ID", "")) or ""
        # F104：ingest 时的有界结构快照 + 追踪像素计数（渲染层本就拦外链
        # 图片，此处如实统计原始 HTML 里的外链 <img> 数）。
        structure = _structure_snapshot(message)
        structure["trackingPixels"] = _tracking_pixel_count(html_part or "")
        # F110：会话头（仅存服务端解析出的 Message-ID 形态，不信任原文）。
        in_reply_to = _first_msg_id(message.get("In-Reply-To", ""))
        references_head = _first_msg_id(message.get("References", ""))
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
        entry_id = message_id or fingerprint[:32]

        def _run(connection: sqlite3.Connection) -> None:
            for identity in identities:
                connection.execute(
                    "INSERT INTO mail_seen (list_uuid, identity, seen_at) VALUES (?, ?, ?)",
                    (lst.uuid, identity, now),
                )
            connection.execute(
                "INSERT INTO mail_bridge_entries (list_uuid, message_id, subject, sender, html, text, attachment_count, attachment_meta, structure_json, in_reply_to, references_head, received_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    lst.uuid,
                    entry_id,
                    subject[:500],
                    sender[:200],
                    clean_html[:200_000],
                    clean_text[:100_000],
                    len(attachments),
                    json.dumps(attachments, ensure_ascii=False),
                    _structure_json_bounded(structure),
                    in_reply_to,
                    references_head,
                    now,
                ),
            )

        try:
            await transaction(self._db, _run)
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
            "SELECT message_id, subject, sender, html, text, attachment_count, attachment_meta, structure_json, in_reply_to, references_head, received_at FROM mail_bridge_entries WHERE list_uuid = ? ORDER BY received_at DESC LIMIT ?",
            (list_uuid, _MAX_ENTRIES_PER_LIST),
        )
        return [dict(row) for row in rows]

    async def get_entry(self, list_uuid: str, message_id: str) -> dict[str, Any] | None:
        """F104/F110：单封邮件（按列表隔离；message_id 即条目身份）。"""
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT message_id, subject, sender, html, text, attachment_count, attachment_meta, structure_json, in_reply_to, references_head, received_at FROM mail_bridge_entries WHERE list_uuid = ? AND message_id = ?",
            (list_uuid, message_id),
        )
        return dict(row) if row is not None else None

    async def build_thread(self, list_uuid: str, message_id: str) -> dict[str, Any] | None:
        """F110：沿 In-Reply-To/References 组装同列表内的有序会话链。

        - 仅同 list（跨列表的父邮件视为缺失——隔离语义）；
        - 仅使用服务端在 ingest 时解析出的可信头值；
        - 缺父 → 链从本封开始 + reason="parent_missing"；
        - 环 → 断开（visited 集合）并标 cycleBroken（诚实降级）。
        返回 None 当本封不存在。"""
        entry = await self.get_entry(list_uuid, message_id)
        if entry is None:
            return None
        rows = await self._db.fetch_all(
            "SELECT message_id, subject, sender, in_reply_to, references_head, received_at FROM mail_bridge_entries WHERE list_uuid = ? ORDER BY received_at ASC LIMIT ?",
            (list_uuid, _MAX_ENTRIES_PER_LIST),
        )
        by_id = {str(r["message_id"]): dict(r) for r in rows}
        children: dict[str, list[str]] = {}
        for row in rows:
            parent = str(row["in_reply_to"] or "") or str(row["references_head"] or "")
            if parent:
                children.setdefault(parent, []).append(str(row["message_id"]))
        # 向上找祖先（In-Reply-To 优先，References 链首兜底）
        chain_ids: list[str] = []
        visited: set[str] = set()
        reason: str | None = None
        cycle_broken = False
        cursor = str(entry["message_id"])
        while True:
            if cursor in visited:
                cycle_broken = True
                break
            visited.add(cursor)
            chain_ids.append(cursor)
            row = by_id.get(cursor)
            parent = str(row["in_reply_to"] or "") if row else ""
            if not parent:
                parent = str(row["references_head"] or "") if row else ""
            if not parent:
                break
            if parent not in by_id:
                reason = "parent_missing"
                break
            cursor = parent
        chain_ids.reverse()  # 祖先 → 本封
        root_missing = reason == "parent_missing"
        # 向下收子孙（BFS，有界）
        queue = [str(entry["message_id"])]
        seen_down: set[str] = set(queue)
        while queue:
            current = queue.pop(0)
            for child in children.get(current, []):
                if child in visited or child in seen_down:
                    cycle_broken = True
                    continue
                seen_down.add(child)
                chain_ids.append(child)
                queue.append(child)
                if len(chain_ids) > _MAX_ENTRIES_PER_LIST:
                    break
        deduped: list[str] = []
        seen_ids: set[str] = set()
        for mid in chain_ids:
            if mid in seen_ids:
                continue
            seen_ids.add(mid)
            deduped.append(mid)
        chain = [
            {
                "id": mid,
                "subject": str(by_id[mid]["subject"]),
                "date": str(by_id[mid]["received_at"]),
                "current": mid == str(entry["message_id"]),
            }
            for mid in deduped
            if mid in by_id
        ]
        return {
            "chain": chain,
            "reason": reason if root_missing else None,
            "cycleBroken": cycle_broken,
        }

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


def _structure_snapshot(message: email.message.Message) -> dict[str, Any]:
    """F104：ingest 时的结构快照（multipart 树：类型/边界/大小）。

    有界：每层最多 12 个 part、深度最多 6 层；超界截断并标
    ``truncated: true``（快照只服务「解析对照」，不追求完整）。"""
    def _walk(part: email.message.Message, depth: int) -> dict[str, Any]:
        node: dict[str, Any] = {
            "type": part.get_content_type(),
        }
        disposition = part.get_content_disposition()
        if disposition:
            node["disposition"] = disposition
        if part.is_multipart() and depth < 6:
            children = []
            truncated = False
            for index, child in enumerate(part.iter_parts()):
                if index >= 12:
                    truncated = True
                    break
                children.append(_walk(child, depth + 1))
            node["parts"] = children
            if truncated:
                node["truncated"] = True
        else:
            try:
                payload = part.get_payload(decode=True) or b""
            except Exception:  # noqa: BLE001 — 大小未知留 -1（诚实）
                payload = b""
            node["bytes"] = len(payload) if isinstance(payload, bytes) else len(str(payload))
        return node

    return _walk(message, 0)


def _structure_json_bounded(structure: dict[str, Any]) -> str:
    """快照序列化并压到 ≤2KB（超出截尾 + 标记；对照用途足够）。"""
    text = json.dumps(structure, ensure_ascii=False, separators=(",", ":"))
    if len(text.encode("utf-8")) <= _MAX_STRUCTURE_BYTES:
        return text
    clipped = dict(structure)
    clipped["truncated"] = True
    while len(json.dumps(clipped, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > _MAX_STRUCTURE_BYTES:
        if not clipped.pop("parts", None):
            break
    return json.dumps(clipped, ensure_ascii=False, separators=(",", ":"))[:_MAX_STRUCTURE_BYTES]


def _tracking_pixel_count(html: str) -> int:
    """F104：原始 HTML 中外链 <img> 数（渲染层本就拦截，如实统计）。"""
    import re

    if not html:
        return 0
    count = 0
    for match in re.finditer(r"<img\b[^>]*>", html, re.IGNORECASE):
        src = re.search(r"""src\s*=\s*["']?([^"'\s>]+)""", match.group(0), re.IGNORECASE)
        if src and src.group(1).lower().startswith(("http://", "https://")):
            count += 1
    return count


def _first_msg_id(header_value: Any) -> str | None:
    """从 In-Reply-To / References 头取第一个 msg-id（去尖括号；仅保留
    形如 token@token 的可信形态——服务端解析结果，不信任原文其余部分）。"""
    import re

    text = _decode_header(header_value)
    if not text:
        return None
    match = re.search(r"<([^<>]+)>|([^\s;,<>]+@[^\s;,<>]+)", text)
    if match is None:
        return None
    value = match.group(1) or match.group(2) or ""
    value = value.strip()
    if not value or "@" not in value or len(value) > 250:
        return None
    return value


def mask_from_display(sender: str) -> str:
    """F104：发件人脱敏展示——邮箱本地部分替换为 ***（保留显示名与域）。"""
    import re

    text = str(sender or "").strip()
    if not text:
        return ""
    email_match = re.search(r"([^\s<]+)@([^\s>]+)", text)
    if email_match is None:
        return text[:120]
    return text.replace(email_match.group(1), "***", 1)


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
                # F104：附件名净化展示（去尖括号/引号/控制符，限长）——
                # 名字只作展示，绝不进入 HTML/Atom 渲染面。
                "filename": _sanitize_display_name(
                    part.get_filename() or "(unnamed)"
                ),
                "bytes": size,
            }
        )
    return meta


def _sanitize_display_name(name: str) -> str:
    import re

    cleaned = re.sub(r"[<>&\"'\x00-\x1f]", "_", str(name))
    return cleaned[:120] or "(unnamed)"
