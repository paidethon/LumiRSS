"""Inbox push source store (0021).

A machine-to-machine push source: external scripts/agents POST
authenticated JSON items to an ingest endpoint and the content lands as
Lumi-owned ``library_items`` rows of kind ``api_item`` (ADR 0004). The
store owns three invariants:

- idempotency: (source, guid) is unique — replaying the same item
  converges to ``exists`` instead of duplicating rows;
- atomicity: identity + payload + search projection commit in one
  transaction (``db_tx``), so a failed write leaves no orphan identity
  row and no half-updated projection;
- honest connector state: ``last_success_at`` / ``last_error`` are
  recorded per source so the unified source registry can surface health
  without probing the connector.

Untrusted HTML is sanitized by the ROUTE before it reaches this store;
the store never sees raw markup. Secrets follow the ``api_sources``
pattern: generated per source, returned exactly once at creation, never
echoed by list/read paths.
"""

import json
import uuid as _uuid
from typing import Any

from lumirss.db_tx import transaction
from lumirss.storage import Database
from lumirss.token_hash import hash_token, verify_token
from lumirss.util import utc_now


class InboxSourceNotFound(Exception):
    """The referenced inbox connector does not exist."""


class InboxItemNotFound(Exception):
    """The referenced inbox item does not exist."""


class InvalidInboxPayload(Exception):
    """A pushed/managed inbox payload failed explicit (non-Pydantic)
    validation, e.g. a non-http(s) URL or an unparseable timestamp."""


_MAX_PAGE = 50


def new_source_secret() -> str:
    """High-entropy per-connector credential (shown once at creation)."""
    import secrets


    return secrets.token_hex(16)


def secrets_match(supplied: str, stored: str) -> bool:
    """§13.4：哈希化存储的单向验证（旧明文行走兼容分支）。"""
    return verify_token(supplied, stored)


class InboxStore:
    """Push-inbox connectors and their Lumi-owned items."""

    def __init__(self, db: Database) -> None:
        self._db = db

    @staticmethod
    def secrets_match(supplied: str, stored: str) -> bool:
        """Constant-time bearer comparison (never logged)."""
        return secrets_match(supplied, stored)

    async def create_source(self, name: str) -> dict[str, Any]:
        source_uuid = str(_uuid.uuid4())
        secret = new_source_secret()
        now = utc_now()
        await self._db.migrate()
        # §13.4：只存哈希；明文仅在创建响应出现一次。
        await self._db.execute(
            "INSERT INTO inbox_sources (uuid, name, enabled, secret, last_success_at, last_error, created_at, secret_is_hash) VALUES (?, ?, 1, ?, NULL, NULL, ?, 1)",
            (source_uuid, name, hash_token(secret), now),
        )
        return {
            "uuid": source_uuid,
            "name": name,
            "enabled": True,
            "secret": secret,
            "createdAt": now,
        }

    async def list_sources(self) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT uuid, name, enabled, last_success_at, last_error, created_at FROM inbox_sources ORDER BY created_at ASC, uuid ASC",
            (),
        )
        return [self._source_view(row) for row in rows]

    async def get_source(self, source_uuid: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT uuid, name, enabled, secret, last_success_at, last_error, created_at FROM inbox_sources WHERE uuid = ?",
            (source_uuid,),
        )
        if row is None:
            return None
        return {
            "uuid": str(row["uuid"]),
            "name": str(row["name"]),
            "enabled": bool(row["enabled"]),
            "secret": str(row["secret"]),
            "lastSuccessAt": row["last_success_at"],
            "lastError": row["last_error"],
            "createdAt": str(row["created_at"]),
        }

    async def rotate_secret(self, source_uuid: str) -> str | None:
        """Replace the bearer secret (pool #28): the old token stops
        working immediately, pushed items are untouched, and the new
        secret is returned exactly once (never logged). ``None`` when
        the source is unknown."""
        source = await self.get_source(source_uuid)
        if source is None:
            return None
        secret = new_source_secret()
        await self._db.migrate()
        # §13.4：落库哈希；明文仅在轮换响应出现一次。
        await self._db.execute(
            "UPDATE inbox_sources SET secret = ?, secret_is_hash = 1 WHERE uuid = ?",
            (hash_token(secret), source_uuid),
        )
        return secret

    async def delete_source(self, source_uuid: str) -> list[str] | None:
        """Delete a connector and every item it pushed.

        Returns the deleted ItemRefs so the caller can invalidate
        derived indexes (RAG); ``None`` when the source is unknown (the
        caller turns that into a stable 404). An existing connector with
        zero items returns ``[]``.
        """
        await self._db.migrate()
        if await self.get_source(source_uuid) is None:
            return None
        rows = await self._db.fetch_all(
            "SELECT item_uuid FROM library_inbox WHERE source_uuid = ?",
            (source_uuid,),
        )
        item_uuids = [str(row["item_uuid"]) for row in rows]

        def _tx(connection: Any) -> None:
            # Identity rows AND the search projection commit together —
            # deleting them in two transactions let a crash between the
            # two leave permanently-orphaned projection rows (Q-P1-04).
            for item_uuid in item_uuids:
                connection.execute(
                    "DELETE FROM library_items WHERE uuid = ?", (item_uuid,)
                )
            connection.execute(
                "DELETE FROM inbox_sources WHERE uuid = ?", (source_uuid,)
            )
            for item_uuid in item_uuids:
                connection.execute(
                    "DELETE FROM search_library WHERE ref = ?",
                    (f"library:{item_uuid}",),
                )

        await transaction(self._db, _tx)
        return [f"library:{u}" for u in item_uuids]

    async def ingest(
        self,
        source: dict[str, Any],
        *,
        guid: str,
        title: str,
        url: str | None,
        author: str | None,
        content_html: str,
        content_text: str,
        published_at: str | None,
        categories: list[str],
    ) -> tuple[str, str]:
        """Store one pushed item; (status, ref) with status in
        ``created`` | ``exists``. Replaying (source, guid) never
        duplicates — the existing row wins and the connector health is
        still refreshed."""
        await self._db.migrate()
        now = utc_now()
        source_uuid = source["uuid"]

        def _tx(connection: Any) -> tuple[str, str]:
            existing = connection.execute(
                "SELECT item_uuid FROM library_inbox WHERE source_uuid = ? AND guid = ?",
                (source_uuid, guid),
            ).fetchone()
            if existing is not None:
                ref = f"library:{existing['item_uuid']}"
                connection.execute(
                    "UPDATE inbox_sources SET last_success_at = ?, last_error = NULL WHERE uuid = ?",
                    (now, source_uuid),
                )
                return "exists", ref
            item_uuid = str(_uuid.uuid4())
            connection.execute(
                "INSERT INTO library_items (uuid, kind, created_at) VALUES (?, 'api_item', ?)",
                (item_uuid, now),
            )
            connection.execute(
                "INSERT INTO library_inbox (item_uuid, source_uuid, guid, title, url, author, content_html, content_text, published_at, categories, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    item_uuid,
                    source_uuid,
                    guid,
                    title,
                    url,
                    author,
                    content_html,
                    content_text,
                    published_at,
                    json.dumps(categories, ensure_ascii=False),
                    now,
                ),
            )
            connection.execute(
                "INSERT INTO search_library (ref, kind, title, body, url, updated_at) VALUES (?, 'api_item', ?, ?, ?, ?)",
                (f"library:{item_uuid}", title, _projection_body(content_text, url), url, now),
            )
            connection.execute(
                "UPDATE inbox_sources SET last_success_at = ?, last_error = NULL WHERE uuid = ?",
                (now, source_uuid),
            )
            return "created", f"library:{item_uuid}"

        return await transaction(self._db, _tx)

    async def record_error(self, source_uuid: str, message: str) -> None:
        await self._db.migrate()
        await self._db.execute(
            "UPDATE inbox_sources SET last_error = ? WHERE uuid = ?",
            (message[:280], source_uuid),
        )

    async def list_items(
        self,
        *,
        source_uuid: str | None = None,
        keyset: tuple[str, str] | None = None,
        limit: int = 20,
    ) -> tuple[list[dict[str, Any]], bool]:
        """Newest-first item page; keyset is (created_at, item_uuid).

        Returns minimal rows (ref + ordering metadata); callers render
        through the ItemRef registry (batch resolve), never from this
        table directly.
        """
        await self._db.migrate()
        page = max(1, min(limit, _MAX_PAGE))
        params: list[Any] = []
        where = "WHERE (? IS NULL OR i.source_uuid = ?)"
        params.extend([source_uuid, source_uuid])
        if keyset is not None:
            where += " AND (i.created_at < ? OR (i.created_at = ? AND i.item_uuid < ?))"
            params.extend([keyset[0], keyset[0], keyset[1]])
        params.append(page + 1)
        rows = await self._db.fetch_all(
            f"SELECT i.item_uuid, i.created_at, i.source_uuid FROM library_inbox i {where} ORDER BY i.created_at DESC, i.item_uuid DESC LIMIT ?",
            tuple(params),
        )
        has_more = len(rows) > page
        rows = rows[:page]
        items = [
            {
                "ref": f"library:{row['item_uuid']}",
                "createdAt": str(row["created_at"]),
                "sourceUuid": str(row["source_uuid"]),
            }
            for row in rows
        ]
        return items, has_more

    async def get_item(self, item_uuid: str) -> dict[str, Any] | None:
        """Resolve-shaped row for the ItemRef registry."""
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT i.item_uuid, i.title, i.url, i.author, i.content_text, i.content_html, i.published_at, i.created_at, s.name AS source_name FROM library_inbox i JOIN inbox_sources s ON s.uuid = i.source_uuid WHERE i.item_uuid = ?",
            (item_uuid,),
        )
        if row is None:
            return None
        return {
            "uuid": str(row["item_uuid"]),
            "title": str(row["title"]),
            "url": row["url"],
            "author": row["author"],
            "contentText": str(row["content_text"] or ""),
            "contentHtml": str(row["content_html"] or ""),
            "publishedAt": row["published_at"],
            "createdAt": str(row["created_at"]),
            "sourceName": str(row["source_name"]),
        }

    async def delete_item(self, item_uuid: str) -> str | None:
        """Delete one item (identity row cascades the payload row) plus
        its search projection; returns the ref or None when unknown."""
        await self._db.migrate()
        ref = f"library:{item_uuid}"

        def _tx(connection: Any) -> int:
            cursor = connection.execute(
                "DELETE FROM library_items WHERE uuid = ?", (item_uuid,)
            )
            connection.execute(
                "DELETE FROM search_library WHERE ref = ?", (ref,)
            )
            return cursor.rowcount

        deleted = await transaction(self._db, _tx)
        if not deleted:
            return None
        return ref

    async def counts(self) -> dict[str, int]:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM library_inbox", ()
        )
        sources = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM inbox_sources", ()
        )
        return {"sources": int(sources["n"]), "items": int(row["n"])}

    def _source_view(self, row: Any) -> dict[str, Any]:
        return {
            "uuid": str(row["uuid"]),
            "name": str(row["name"]),
            "enabled": bool(row["enabled"]),
            "lastSuccessAt": row["last_success_at"],
            "lastError": row["last_error"],
            "createdAt": str(row["created_at"]),
        }


def _projection_body(content_text: str, url: str | None) -> str:
    body = content_text.strip()
    if not body and url:
        body = url
    return body[:100_000]
