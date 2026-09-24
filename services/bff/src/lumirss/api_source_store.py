"""API source config store (phase2 M3). All single-line inline SQL."""

import json
import sqlite3
from dataclasses import replace
from typing import Any

from lumirss.api_sources import (
    ApiSourceInvalid,
    ApiSourceRecord,
    new_source_secret,
    observe_schema,
    serialize_baseline,
    validate_endpoint,
    validate_field_map,
    validate_items_expr,
    validate_pagination,
)
from lumirss.storage import Database
from lumirss.token_hash import hash_token
from lumirss.util import UTC, utc_now

_MAX_NAME_LENGTH = 100
_MAX_SOURCES = 100
# N129: per-source fetch budget bounds (hourly token bucket).
_MIN_RUNS_PER_HOUR = 1
_MAX_RUNS_PER_HOUR = 60
_RUN_WINDOW_SECONDS = 3600


def validate_max_runs_per_hour(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiSourceInvalid("maxRunsPerHour must be an integer.")
    if not _MIN_RUNS_PER_HOUR <= value <= _MAX_RUNS_PER_HOUR:
        raise ApiSourceInvalid(
            f"maxRunsPerHour must be within {_MIN_RUNS_PER_HOUR}..{_MAX_RUNS_PER_HOUR}."
        )
    return value


class ApiSourceStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self,
        *,
        name: str,
        endpoint: str,
        items_expr: str,
        field_map: dict[str, str],
        pagination: dict[str, Any] | None = None,
        max_runs_per_hour: int = 4,
    ) -> ApiSourceRecord:
        await self._db.migrate()
        clean_name = _validate_name(name)
        clean_endpoint = validate_endpoint(endpoint)
        clean_items = validate_items_expr(items_expr)
        clean_fields = validate_field_map(field_map)
        clean_pagination = validate_pagination(pagination)
        clean_budget = validate_max_runs_per_hour(max_runs_per_hour)
        count = await self._count()
        if count >= _MAX_SOURCES:
            raise ApiSourceInvalid(f"Too many API sources (max {_MAX_SOURCES}).")
        source_uuid = _new_uuid()
        secret = new_source_secret()
        now = utc_now()
        try:
            # §13.4：只存哈希（secret_is_hash=1）；明文仅在创建响应出现
            # 一次（FreshRSS 订阅 URL 也用本次明文——订阅后存储值不可再
            # 重建，取消订阅按 uuid 路径段匹配，见 routers/api_sources）。
            await self._db.execute(
                "INSERT INTO api_sources (uuid, name, endpoint, items_expr, field_map, enabled, secret, etag, last_status, last_success_at, last_error, created_at, pagination, secret_is_hash, max_runs_per_hour, respect_retry_after) VALUES (?, ?, ?, ?, ?, 1, ?, NULL, NULL, NULL, NULL, ?, ?, 1, ?, 1)",
                (
                    source_uuid,
                    clean_name,
                    clean_endpoint,
                    clean_items,
                    clean_fields,
                    hash_token(secret),
                    now,
                    clean_pagination,
                    clean_budget,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ApiSourceInvalid("A source with this id already exists.") from exc
        record = await self.get(source_uuid)
        assert record is not None  # 刚插入必然存在
        # 一次性：创建响应/订阅 URL 用原始值（数据类冻结 → replace）。
        return replace(record, secret=secret)

    async def get(self, source_uuid: str) -> ApiSourceRecord | None:
        await self._db.migrate()
        row = await self._db.fetch_one("SELECT uuid, name, endpoint, items_expr, field_map, enabled, secret, etag, last_status, last_success_at, last_error, created_at, atom_body, feed_updated, pagination, confirmed_schema, schema_drift, max_runs_per_hour, respect_retry_after, next_allowed_run FROM api_sources WHERE uuid = ?", (source_uuid,))
        return _record_from_row(row) if row is not None else None

    async def list_sources(self) -> list[ApiSourceRecord]:
        await self._db.migrate()
        rows = await self._db.fetch_all("SELECT uuid, name, endpoint, items_expr, field_map, enabled, secret, etag, last_status, last_success_at, last_error, created_at, atom_body, feed_updated, pagination, confirmed_schema, schema_drift, max_runs_per_hour, respect_retry_after, next_allowed_run FROM api_sources ORDER BY created_at ASC, uuid ASC")
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
        pagination: dict[str, Any] | None = None,
        max_runs_per_hour: int | None = None,
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
        new_pagination = (
            validate_pagination(pagination)
            if pagination is not None
            else current.pagination
        )
        new_budget = (
            validate_max_runs_per_hour(max_runs_per_hour)
            if max_runs_per_hour is not None
            else current.max_runs_per_hour
        )
        # Config change invalidates cache identity and prior status —
        # including the last-known-good body and its content timestamp
        # (the old feed no longer describes the new configuration).
        # F043: a saved mapping also invalidates the confirmed structure
        # baseline (re-snapshot via POST .../confirm-schema; drift stays
        # silent — honest — until then).
        await self._db.execute(
            "UPDATE api_sources SET name = ?, endpoint = ?, items_expr = ?, field_map = ?, enabled = ?, pagination = ?, max_runs_per_hour = ?, etag = NULL, atom_body = NULL, feed_updated = NULL, last_status = NULL, last_error = NULL, confirmed_schema = NULL, schema_drift = NULL WHERE uuid = ?",
            (
                new_name,
                new_endpoint,
                new_items,
                new_fields,
                new_enabled,
                new_pagination,
                new_budget,
                source_uuid,
            ),
        )
        return await self.get(source_uuid)

    async def confirm_schema(
        self, source_uuid: str, items: list[dict[str, Any]]
    ) -> str | None:
        """F043: snapshot the user-confirmed baseline from mapped items."""
        baseline = serialize_baseline(observe_schema(items))
        await self._db.execute(
            "UPDATE api_sources SET confirmed_schema = ?, schema_drift = NULL WHERE uuid = ?",
            (baseline, source_uuid),
        )
        return baseline

    async def mark_drift(self, source_uuid: str, drift: dict[str, Any]) -> None:
        """Persist the latest drift report (advisory, alongside ok status)."""
        await self._db.execute(
            "UPDATE api_sources SET schema_drift = ? WHERE uuid = ?",
            (json.dumps(drift, ensure_ascii=False, separators=(",", ":")), source_uuid),
        )

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

    async def mark_success(
        self, source_uuid: str, etag: str, atom_body: str, feed_updated: str
    ) -> None:
        """Persist the last-known-good Atom atomically with its status."""
        await self._db.execute(
            "UPDATE api_sources SET last_status = 'ok', etag = ?, atom_body = ?, feed_updated = ?, last_success_at = ?, last_error = NULL WHERE uuid = ?",
            (etag, atom_body, feed_updated, utc_now(), source_uuid),
        )

    async def mark_error(self, source_uuid: str, status: str, error: str) -> None:
        await self._db.execute(
            "UPDATE api_sources SET last_status = ?, last_error = ? WHERE uuid = ?",
            (status, error[:500], source_uuid),
        )

    async def _count(self) -> int:
        row = await self._db.fetch_one("SELECT COUNT(*) AS n FROM api_sources")
        return int(row["n"]) if row is not None else 0

    # -- N129: per-source fetch budget (persisted token bucket) ------------

    async def record_run(self, source_uuid: str) -> None:
        """One upstream run consumed a bucket token; prune the trailing
        hour in the same statement batch so the table stays bounded."""
        now = utc_now()
        cutoff = _iso_seconds_ago(_RUN_WINDOW_SECONDS)
        await self._db.execute(
            "INSERT INTO api_source_runs (source_uuid, ran_at) VALUES (?, ?)",
            (source_uuid, now),
        )
        await self._db.execute(
            "DELETE FROM api_source_runs WHERE ran_at < ?", (cutoff,)
        )

    async def exhausted_until(
        self, source_uuid: str, max_runs_per_hour: int
    ) -> str | None:
        """RFC3339 time when the next run is allowed, or None now.

        The bucket counts runs recorded in the trailing hour; when the
        source's budget is spent the next allowed moment is one hour
        after the OLDEST run still in the window (tokens refill in
        order). An upstream Retry-After verdict (``next_allowed_run``
        column) can push that moment later — never earlier."""
        cutoff = _iso_seconds_ago(_RUN_WINDOW_SECONDS)
        rows = await self._db.fetch_all(
            "SELECT ran_at FROM api_source_runs WHERE source_uuid = ? AND ran_at >= ? ORDER BY ran_at ASC",
            (source_uuid, cutoff),
        )
        if len(rows) < max_runs_per_hour:
            return None
        oldest = str(rows[0]["ran_at"])
        next_refill = _iso_plus_seconds(oldest, _RUN_WINDOW_SECONDS)
        record = await self.get(source_uuid)
        blocked_until = record.next_allowed_run if record else None
        if blocked_until is not None and blocked_until > next_refill:
            return blocked_until
        return next_refill

    async def set_next_allowed_run(
        self, source_uuid: str, when: str | None
    ) -> None:
        await self._db.execute(
            "UPDATE api_sources SET next_allowed_run = ? WHERE uuid = ?",
            (when, source_uuid),
        )

    # -- N130: credential rotation (atomic hash swap) -----------------------

    async def swap_secret_hash(
        self, source_uuid: str, new_credential: str
    ) -> str | None:
        """Replace the stored secret hash with the hash of the caller's
        new credential; returns the OLD stored hash (for the fallback
        window) or None when the source is unknown. Callers must run the
        credential test BEFORE calling this — the swap itself is a single
        statement, so the previous credential never coexists in the row."""
        record = await self.get(source_uuid)
        if record is None:
            return None
        old_hash = record.secret
        await self._db.execute(
            "UPDATE api_sources SET secret = ?, secret_is_hash = 1 WHERE uuid = ?",
            (hash_token(new_credential), source_uuid),
        )
        return old_hash


def _iso_seconds_ago(seconds: int) -> str:
    from datetime import datetime, timedelta

    moment = datetime.now(UTC) - timedelta(seconds=seconds)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_plus_seconds(iso_timestamp: str, seconds: int) -> str:
    from datetime import datetime, timedelta

    base = datetime.fromisoformat(iso_timestamp.replace("Z", "+00:00"))
    return (base + timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


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
        atom_body=row["atom_body"],
        feed_updated=row["feed_updated"],
        pagination=str(row["pagination"]) if row["pagination"] else '{"mode":"none"}',
        confirmed_schema=row["confirmed_schema"],
        schema_drift=row["schema_drift"],
        max_runs_per_hour=int(row["max_runs_per_hour"] or 4),
        respect_retry_after=bool(row["respect_retry_after"]),
        next_allowed_run=row["next_allowed_run"],
    )


_ = Any  # typing import kept for readers of dict[str, Any]
