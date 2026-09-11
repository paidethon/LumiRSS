"""API source config store (phase2 M3). All single-line inline SQL."""

import sqlite3
from typing import Any

from lumirss.api_sources import (
    ApiSourceInvalid,
    ApiSourceRecord,
    new_source_secret,
    validate_endpoint,
    validate_field_map,
    validate_items_expr,
)
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_NAME_LENGTH = 100
_MAX_SOURCES = 100


class ApiSourceStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self, *, name: str, endpoint: str, items_expr: str, field_map: dict[str, str]
    ) -> ApiSourceRecord:
        await self._db.migrate()
        clean_name = _validate_name(name)
        clean_endpoint = validate_endpoint(endpoint)
        clean_items = validate_items_expr(items_expr)
        clean_fields = validate_field_map(field_map)
        count = await self._count()
        if count >= _MAX_SOURCES:
            raise ApiSourceInvalid(f"Too many API sources (max {_MAX_SOURCES}).")
        source_uuid = _new_uuid()
        secret = new_source_secret()
        now = utc_now()
        try:
            await self._db.execute(
                "INSERT INTO api_sources (uuid, name, endpoint, items_expr, field_map, enabled, secret, etag, last_status, last_success_at, last_error, created_at) VALUES (?, ?, ?, ?, ?, 1, ?, NULL, NULL, NULL, NULL, ?)",
                (
                    source_uuid,
                    clean_name,
                    clean_endpoint,
                    clean_items,
                    clean_fields,
                    secret,
                    now,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ApiSourceInvalid("A source with this id already exists.") from exc
        return (await self.get(source_uuid))  # type: ignore[return-value]

    async def get(self, source_uuid: str) -> ApiSourceRecord | None:
        await self._db.migrate()
        row = await self._db.fetch_one("SELECT uuid, name, endpoint, items_expr, field_map, enabled, secret, etag, last_status, last_success_at, last_error, created_at FROM api_sources WHERE uuid = ?", (source_uuid,))
        return _record_from_row(row) if row is not None else None

    async def list_sources(self) -> list[ApiSourceRecord]:
        await self._db.migrate()
        rows = await self._db.fetch_all("SELECT uuid, name, endpoint, items_expr, field_map, enabled, secret, etag, last_status, last_success_at, last_error, created_at FROM api_sources ORDER BY created_at ASC, uuid ASC")
        return [_record_from_row(row) for row in rows if row is not None]

    async def update(
        self,
        source_uuid: str,
        *,
        name: str | None = None,
        endpoint: str | None = None,
        items_expr: str | None = None,
        field_map: dict[str, str] | None = None,
        enabled: bool | None = None,
    ) -> ApiSourceRecord | None:
        current = await self.get(source_uuid)
        if current is None:
            return None
        new_name = _validate_name(name) if name is not None else current.name
        new_endpoint = (
            validate_endpoint(endpoint) if endpoint is not None else current.endpoint
        )
        new_items = (
            validate_items_expr(items_expr)
            if items_expr is not None
            else current.items_expr
        )
        new_fields = (
            validate_field_map(field_map)
            if field_map is not None
            else current.field_map
        )
        new_enabled = current.enabled if enabled is None else (1 if enabled else 0)
        # Config change invalidates cache identity and prior status.
        await self._db.execute(
            "UPDATE api_sources SET name = ?, endpoint = ?, items_expr = ?, field_map = ?, enabled = ?, etag = NULL, last_status = NULL, last_error = NULL WHERE uuid = ?",
            (
                new_name,
                new_endpoint,
                new_items,
                new_fields,
                new_enabled,
                source_uuid,
            ),
        )
        return await self.get(source_uuid)

    async def delete(self, source_uuid: str) -> bool:
        row = await self._db.fetch_one(
            "SELECT uuid FROM api_sources WHERE uuid = ?", (source_uuid,)
        )
        if row is None:
            return False
        await self._db.execute(
            "DELETE FROM api_sources WHERE uuid = ?", (source_uuid,)
        )
        return True

    async def mark_success(self, source_uuid: str, etag: str) -> None:
        await self._db.execute(
            "UPDATE api_sources SET last_status = 'ok', etag = ?, last_success_at = ?, last_error = NULL WHERE uuid = ?",
            (etag, utc_now(), source_uuid),
        )

    async def mark_error(self, source_uuid: str, status: str, error: str) -> None:
        await self._db.execute(
            "UPDATE api_sources SET last_status = ?, last_error = ? WHERE uuid = ?",
            (status, error[:500], source_uuid),
        )

    async def _count(self) -> int:
        row = await self._db.fetch_one("SELECT COUNT(*) AS n FROM api_sources")
        return int(row["n"]) if row is not None else 0


def _new_uuid() -> str:
    import uuid as _uuid

    return str(_uuid.uuid4())


def _validate_name(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ApiSourceInvalid("API source name must not be empty.")
    clean = name.strip()
    if len(clean) > _MAX_NAME_LENGTH:
        raise ApiSourceInvalid("API source name is too long.")
    return clean


def _record_from_row(row: sqlite3.Row) -> ApiSourceRecord:
    return ApiSourceRecord(
        uuid=str(row["uuid"]),
        name=str(row["name"]),
        endpoint=str(row["endpoint"]),
        items_expr=str(row["items_expr"]),
        field_map=str(row["field_map"]),
        enabled=bool(row["enabled"]),
        secret=str(row["secret"]),
        etag=row["etag"],
        last_status=row["last_status"],
        last_success_at=row["last_success_at"],
        last_error=row["last_error"],
        created_at=str(row["created_at"]),
    )


_ = Any  # typing import kept for readers of dict[str, Any]
