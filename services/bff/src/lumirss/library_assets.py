"""Assets storage for user-saved offline snapshots (phase2 M2).

Layout: ``<LUMIRSS_DATA_DIR>/library/assets/<asset uuid>.html`` — paths
are always server-generated uuids, never user input. Saved snapshots are
user content, NOT a cache: they are never evicted automatically. Space
is bounded by an explicit quota (default 2GB); when full, creation fails
with a quota error the UI surfaces honestly (the user deletes or raises
the quota). Identical bytes are stored once (sha256 dedupe with
refcounting across snapshot rows); deleting the last reference removes
the file. Backup/restore include the assets directory.
"""

import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path

from lumirss.itemref import new_library_uuid
from lumirss.storage import Database
from lumirss.util import utc_now

DEFAULT_QUOTA_BYTES = 2 * 1024 * 1024 * 1024  # 2GB
_MAX_SNAPSHOT_BYTES = 50 * 1024 * 1024  # 50MB per artifact


class AssetQuotaExceeded(Exception):
    """Saving this snapshot would exceed the configured quota."""


class AssetTooLarge(Exception):
    """A single snapshot artifact exceeds the per-file cap."""


class AssetNotFound(Exception):
    """No such asset row (or the backing file went missing)."""


@dataclass(frozen=True)
class AssetRecord:
    uuid: str
    item_uuid: str
    path: str
    bytes: int
    sha256: str
    mime: str
    created_at: str

    def to_dict(self) -> dict:
        return {
            "uuid": self.uuid,
            "itemRef": f"library:{self.item_uuid}",
            "bytes": self.bytes,
            "sha256": self.sha256,
            "mime": self.mime,
            "createdAt": self.created_at,
        }


class AssetStore:
    """Filesystem + row bookkeeping for snapshot artifacts."""

    def __init__(self, db: Database, root: Path, quota_bytes: int = DEFAULT_QUOTA_BYTES) -> None:
        self._db = db
        self._root = Path(root)
        self._quota = quota_bytes

    @property
    def root(self) -> Path:
        return self._root

    def file_path(self, asset: AssetRecord) -> Path:
        return self._root / asset.path

    async def save_snapshot(
        self, *, data: bytes, mime: str = "text/html"
    ) -> tuple[AssetRecord, bool]:
        """Store one artifact; dedupe by sha256 (refcount across rows)."""
        if len(data) > _MAX_SNAPSHOT_BYTES:
            raise AssetTooLarge(
                f"Snapshot exceeds the {_MAX_SNAPSHOT_BYTES // (1024 * 1024)}MB limit."
            )
        await self._db.migrate()
        digest = hashlib.sha256(data).hexdigest()
        existing = await self._db.fetch_one(
            "SELECT uuid, item_uuid, path, bytes, sha256, mime, created_at FROM library_assets WHERE sha256 = ? LIMIT 1",
            (digest,),
        )
        stored = await self._bytes_on_disk()
        would_add = 0 if existing is not None else len(data)
        if stored + would_add > self._quota:
            raise AssetQuotaExceeded(
                "存储配额不足：请删除不需要的快照后重试。"
            )
        if existing is not None:
            # Dedupe: new row referencing the same file path (refcount = rows).
            asset_uuid = new_library_uuid()
            await self._db.execute(
                "INSERT INTO library_items (uuid, kind, created_at) VALUES (?, 'snapshot', ?)",
                (asset_uuid, utc_now()),
            )
            await self._db.execute(
                "INSERT INTO library_assets (uuid, item_uuid, path, bytes, sha256, mime, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    asset_uuid,
                    asset_uuid,
                    str(existing["path"]),
                    int(existing["bytes"]),
                    digest,
                    mime,
                    utc_now(),
                ),
            )
            record = await self.get_asset(asset_uuid)
            assert record is not None
            return record, False

        asset_uuid = new_library_uuid()
        relative = f"{asset_uuid}.html"
        self._root.mkdir(parents=True, exist_ok=True)
        target = self._root / relative
        tmp = self._root / f".{asset_uuid}.tmp"
        tmp.write_bytes(data)
        shutil.move(str(tmp), str(target))
        # Every asset is a first-class LibraryItem (kind='snapshot') so
        # library:<uuid> refs resolve to it like any other owned content.
        await self._db.execute(
            "INSERT INTO library_items (uuid, kind, created_at) VALUES (?, 'snapshot', ?)",
            (asset_uuid, utc_now()),
        )
        await self._db.execute(
            "INSERT INTO library_assets (uuid, item_uuid, path, bytes, sha256, mime, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (asset_uuid, asset_uuid, relative, len(data), digest, mime, utc_now()),
        )
        record = await self.get_asset(asset_uuid)
        assert record is not None
        return record, True

    async def get_asset(self, asset_uuid: str) -> AssetRecord | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT uuid, item_uuid, path, bytes, sha256, mime, created_at FROM library_assets WHERE uuid = ?",
            (asset_uuid,),
        )
        if row is None:
            return None
        return AssetRecord(
            uuid=str(row["uuid"]),
            item_uuid=str(row["item_uuid"]),
            path=str(row["path"]),
            bytes=int(row["bytes"]),
            sha256=str(row["sha256"]),
            mime=str(row["mime"]),
            created_at=str(row["created_at"]),
        )

    async def read_bytes(self, asset_uuid: str) -> bytes:
        record = await self.get_asset(asset_uuid)
        if record is None:
            raise AssetNotFound(asset_uuid)
        path = self.file_path(record)
        if not path.is_file():
            raise AssetNotFound(asset_uuid)
        return path.read_bytes()

    async def delete_asset(self, asset_uuid: str) -> bool:
        """Delete one row; the file dies with its last reference."""
        record = await self.get_asset(asset_uuid)
        if record is None:
            return False
        await self._db.migrate()
        await self._db.execute(
            "DELETE FROM library_assets WHERE uuid = ?",
            (asset_uuid,),
        )
        siblings = await self._db.fetch_one(
            "SELECT uuid FROM library_assets WHERE sha256 = ? LIMIT 1",
            (record.sha256,),
        )
        if siblings is None:
            path = self.file_path(record)
            if path.is_file():
                path.unlink()
        return True

    async def _bytes_on_disk(self) -> int:
        row = await self._db.fetch_one(
            "SELECT COALESCE(SUM(bytes), 0) AS total FROM library_assets"
        )
        return int(row["total"]) if row is not None else 0

    async def usage(self) -> dict:
        row = await self._db.fetch_one(
            "SELECT COUNT(*) AS n, COALESCE(SUM(bytes), 0) AS total FROM library_assets"
        )
        return {
            "count": int(row["n"]) if row is not None else 0,
            "bytes": int(row["total"]) if row is not None else 0,
            "quotaBytes": self._quota,
        }

    async def list_assets(self, limit: int = 200) -> list[AssetRecord]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT uuid, item_uuid, path, bytes, sha256, mime, created_at FROM library_assets ORDER BY created_at DESC LIMIT ?",
            (max(1, min(limit, 500)),),
        )
        return [
            AssetRecord(
                uuid=str(row["uuid"]),
                item_uuid=str(row["item_uuid"]),
                path=str(row["path"]),
                bytes=int(row["bytes"]),
                sha256=str(row["sha256"]),
                mime=str(row["mime"]),
                created_at=str(row["created_at"]),
            )
            for row in rows
        ]
