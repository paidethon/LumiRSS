"""Staging pool for sources under evaluation (N016) + N011 bundle drafts.

Rows in ``staged_sources`` are NEITHER subscriptions NOR content: a
staged URL is parked with a bounded preview snapshot so the operator can
decide later; subscribing runs the normal subscribe path exactly once
and removes the row. Nothing here ever counts toward unread — unread
counts live in FreshRSS, and staging never touches it.

The same table also holds N011 bundle-import drafts for source types
that need credentials (api/mail): a bundle is credential-free by
construction, so those rows import as ``enabled=0`` drafts
(``origin='bundle_draft'``) the operator must re-create deliberately.
"""

import json
import uuid as _uuid
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_NOTE_LENGTH = 200
_MAX_SAMPLE_ENTRIES = 10
_MAX_SAMPLE_JSON_BYTES = 64 * 1024


class StagedSourceInvalid(Exception):
    """A staging payload failed validation (400 stable)."""


class StagedSourceNotFound(Exception):
    """No such staged row (404 stable)."""


class StagedSourceConflict(Exception):
    """The URL is already staged / the row cannot be subscribed (409)."""


def validate_note(note: str | None) -> str | None:
    if note is None:
        return None
    clean = note.strip()
    if not clean:
        return None
    if len(clean) > _MAX_NOTE_LENGTH:
        raise StagedSourceInvalid("备注过长（≤200 字符）。")
    return clean


def validate_sample_entries(entries: list[dict[str, Any]]) -> str:
    """Serialize the preview snapshot (≤10 entries, metadata only) with a
    hard byte cap; oversize input is rejected, never silently truncated
    into a lie."""
    trimmed = entries[:_MAX_SAMPLE_ENTRIES]
    payload = json.dumps(trimmed, ensure_ascii=False, separators=(",", ":"))
    while len(payload.encode("utf-8")) > _MAX_SAMPLE_JSON_BYTES and trimmed:
        trimmed.pop()
        payload = json.dumps(trimmed, ensure_ascii=False, separators=(",", ":"))
    return payload


class StagedSourceStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def add(
        self,
        *,
        url: str,
        title: str = "",
        note: str | None = None,
        source_type: str = "rss",
        origin: str = "staging",
        sample_entries: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id FROM staged_sources WHERE url = ?", (url,)
        )
        if row is not None:
            raise StagedSourceConflict("该 URL 已在暂存列表中。")
        source_id = str(_uuid.uuid4())
        await self._db.execute(
            "INSERT INTO staged_sources (id, url, title, added_at, note, sample_json, source_type, origin, enabled) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                source_id,
                url,
                (title or "").strip()[:300],
                utc_now(),
                validate_note(note),
                validate_sample_entries(sample_entries or []),
                source_type,
                origin,
                1 if origin == "staging" else 0,
            ),
        )
        stored = await self.get(source_id)
        assert stored is not None
        return stored

    async def get(self, source_id: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, url, title, added_at, note, sample_json, source_type, origin, enabled FROM staged_sources WHERE id = ?",
            (source_id,),
        )
        return _row_to_view(row) if row is not None else None

    async def find_by_url(self, url: str) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, url, title, added_at, note, sample_json, source_type, origin, enabled FROM staged_sources WHERE url = ?",
            (url,),
        )
        return _row_to_view(row) if row is not None else None

    async def list_all(self, origin: str | None = None) -> list[dict[str, Any]]:
        await self._db.migrate()
        if origin is None:
            rows = await self._db.fetch_all(
                "SELECT id, url, title, added_at, note, sample_json, source_type, origin, enabled FROM staged_sources ORDER BY added_at DESC, id ASC",
                (),
            )
        else:
            rows = await self._db.fetch_all(
                "SELECT id, url, title, added_at, note, sample_json, source_type, origin, enabled FROM staged_sources WHERE origin = ? ORDER BY added_at DESC, id ASC",
                (origin,),
            )
        return [_row_to_view(row) for row in rows]

    async def remove(self, source_id: str) -> bool:
        """Discard one row; False when the id is unknown."""
        await self._db.migrate()
        cursor = await self._db.execute(
            "DELETE FROM staged_sources WHERE id = ?", (source_id,)
        )
        return bool(cursor)


def _row_to_view(row: Any) -> dict[str, Any]:
    try:
        sample = json.loads(row["sample_json"] or "[]")
    except json.JSONDecodeError:
        sample = []
    if not isinstance(sample, list):
        sample = []
    return {
        "id": str(row["id"]),
        "url": str(row["url"]),
        "title": str(row["title"] or ""),
        "addedAt": str(row["added_at"]),
        "note": row["note"],
        "sample": sample,
        "sourceType": str(row["source_type"] or "rss"),
        "origin": str(row["origin"] or "staging"),
        "enabled": bool(row["enabled"]),
    }
