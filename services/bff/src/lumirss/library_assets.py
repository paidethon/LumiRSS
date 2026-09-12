"""Assets storage for user-saved offline snapshots (phase2 M2, recovery P0-04).

Layout: ``<LUMIRSS_DATA_DIR>/library/assets/<asset uuid>.html`` — paths
are always server-generated uuids, never user input. Saved snapshots are
user content, NOT a cache: they are never evicted automatically. Space
is bounded by an explicit quota (default 2GB) charged in PHYSICAL bytes
(each sha256 stored once, regardless of how many snapshot rows reference
it); when full, creation fails with a quota error the UI surfaces
honestly. Identical bytes are stored once (sha256 dedupe with rows as
references — ``deduplicated`` on a save means "this save reused already
stored bytes"). Deleting the last reference removes the file AND the
library_items identity row. Multi-row writes run in one transaction
(db_tx.transaction); file-vs-DB ordering is orphan-minimizing: the file
lands first and is compensated away if the transaction fails, so a
committed row can always be read, and leftover files are swept by
``reconcile()``. Backup/restore include the assets directory.
"""

import contextlib
import hashlib
import shutil
from dataclasses import dataclass
from pathlib import Path

from lumirss.db_tx import transaction
from lumirss.itemref import new_library_uuid
from lumirss.storage import Database
from lumirss.util import utc_now

DEFAULT_QUOTA_BYTES = 2 * 1024 * 1024 * 1024  # 2GB
_MAX_SNAPSHOT_BYTES = 50 * 1024 * 1024  # 50MB per artifact

# Earliest row per sha256 pays the quota; later rows are free references.
# (created_at, uuid) is the same total order the list endpoints use.
_UNIQUE_BYTES_SQL = "SELECT COALESCE(SUM(bytes), 0) AS total FROM library_assets a WHERE NOT EXISTS (SELECT 1 FROM library_assets b WHERE b.sha256 = a.sha256 AND (b.created_at < a.created_at OR (b.created_at = a.created_at AND b.uuid < a.uuid)))"


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
    url: str
    created_at: str

    def to_dict(self) -> dict:
        return {
            "uuid": self.uuid,
            "itemRef": f"library:{self.item_uuid}",
            "url": self.url,
            "bytes": self.bytes,
            "sha256": self.sha256,
            "mime": self.mime,
            "createdAt": self.created_at,
        }


@dataclass(frozen=True)
class SnapshotListRow:
    """One list row with its real dedupe provenance."""

    record: AssetRecord
    deduplicated: bool


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
        self, *, data: bytes, mime: str = "text/html", url: str = ""
    ) -> tuple[AssetRecord, bool]:
        """Store one artifact; dedupe by sha256 (rows are references).

        Returns (record, deduplicated) where ``deduplicated`` is True
        exactly when THIS save reused already-stored bytes (no new file).
        """
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
        stored = await self._unique_bytes_on_disk()
        would_add = 0 if existing is not None else len(data)
        if stored + would_add > self._quota:
            raise AssetQuotaExceeded(
                "存储配额不足：请删除不需要的快照后重试。"
            )
        asset_uuid = new_library_uuid()
        now = utc_now()

        def _tx(conn) -> None:
            conn.execute(
                "INSERT INTO library_items (uuid, kind, created_at) VALUES (?, 'snapshot', ?)",
                (asset_uuid, now),
            )
            if existing is not None:
                # Dedupe: new row referencing the same file (refcount = rows).
                conn.execute(
                    "INSERT INTO library_assets (uuid, item_uuid, path, bytes, sha256, mime, url, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        asset_uuid,
                        asset_uuid,
                        str(existing["path"]),
                        int(existing["bytes"]),
                        digest,
                        mime,
                        url,
                        now,
                    ),
                )
            else:
                conn.execute(
                    "INSERT INTO library_assets (uuid, item_uuid, path, bytes, sha256, mime, url, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (asset_uuid, asset_uuid, f"{asset_uuid}.html", len(data), digest, mime, url, now),
                )

        if existing is None:
            # Orphan-minimizing order: the file lands first (a crash
            # before commit leaves at worst an unreferenced file, which
            # reconcile() sweeps — never an unreadable committed row);
            # if the transaction fails, the file is compensated away.
            relative = f"{asset_uuid}.html"
            self._root.mkdir(parents=True, exist_ok=True)
            target = self._root / relative
            tmp = self._root / f".{asset_uuid}.tmp"
            try:
                tmp.write_bytes(data)
                shutil.move(str(tmp), str(target))
            except OSError:
                tmp.unlink(missing_ok=True)
                raise
            try:
                await transaction(self._db, _tx)
            except BaseException:
                target.unlink(missing_ok=True)
                raise
        else:
            await transaction(self._db, _tx)
        record = await self.get_asset(asset_uuid)
        assert record is not None
        return record, existing is not None

    async def get_asset(self, asset_uuid: str) -> AssetRecord | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT uuid, item_uuid, path, bytes, sha256, mime, url, created_at FROM library_assets WHERE uuid = ?",
            (asset_uuid,),
        )
        if row is None:
            return None
        return _record_from_row(row)

    async def read_bytes(self, asset_uuid: str) -> bytes:
        record = await self.get_asset(asset_uuid)
        if record is None:
            raise AssetNotFound(asset_uuid)
        path = self.file_path(record)
        if not path.is_file():
            raise AssetNotFound(asset_uuid)
        return path.read_bytes()

    async def delete_asset(self, asset_uuid: str) -> bool:
        """Delete one snapshot; identity row + last-reference file die too.

        Atomic-enough contract: both rows (library_assets + the
        kind='snapshot' library_items identity, which cascades any
        remaining asset rows) disappear in ONE transaction. The file is
        unlinked only after that commit and only when no other row
        references the bytes; a failed unlink (or a crash before it)
        leaves at worst an unreferenced file that reconcile() sweeps —
        never a dangling row.
        """
        record = await self.get_asset(asset_uuid)
        if record is None:
            return False
        await self._db.migrate()

        def _tx(conn) -> bool:
            conn.execute(
                "DELETE FROM library_assets WHERE uuid = ?", (asset_uuid,)
            )
            conn.execute(
                "DELETE FROM library_items WHERE uuid = ?", (record.item_uuid,)
            )
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM library_assets WHERE sha256 = ?",
                (record.sha256,),
            ).fetchone()
            return int(row["n"]) == 0

        was_last_reference = await transaction(self._db, _tx)
        if was_last_reference:
            path = self.file_path(record)
            if path.is_file():
                # Orphan-file risk only; reconcile() sweeps it.
                with contextlib.suppress(OSError):
                    path.unlink()
        return True

    async def _unique_bytes_on_disk(self) -> int:
        """Physical bytes: each sha256 charged once (earliest row pays)."""
        row = await self._db.fetch_one(_UNIQUE_BYTES_SQL)
        return int(row["total"]) if row is not None else 0

    async def usage(self) -> dict:
        """count = snapshot rows (references); bytes = unique physical."""
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM library_assets"
        )
        return {
            "count": int(row["n"]) if row is not None else 0,
            "bytes": await self._unique_bytes_on_disk(),
            "quotaBytes": self._quota,
        }

    async def list_snapshots(self, limit: int = 200) -> list[SnapshotListRow]:
        """List rows with the REAL dedupe flag (an earlier same-sha256
        row exists → this row was stored as a dedupe reference)."""
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT a.uuid AS uuid, a.item_uuid AS item_uuid, a.path AS path, a.bytes AS bytes, a.sha256 AS sha256, a.mime AS mime, a.url AS url, a.created_at AS created_at, EXISTS(SELECT 1 FROM library_assets b WHERE b.sha256 = a.sha256 AND (b.created_at < a.created_at OR (b.created_at = a.created_at AND b.uuid < a.uuid))) AS deduplicated FROM library_assets a ORDER BY a.created_at DESC, a.uuid DESC LIMIT ?",
            (max(1, min(limit, 500)),),
        )
        return [
            SnapshotListRow(record=_record_from_row(row), deduplicated=bool(row["deduplicated"]))
            for row in rows
        ]

    async def reconcile(self) -> dict[str, int]:
        """Best-effort compensation sweep (crash/IO aftermath):

        - files under the asset root that NO row references (including
          ``.<uuid>.tmp`` leftovers) are deleted;
        - rows whose backing file disappeared are deleted together with
          their library_items identity rows (they could never be read).

        Returns counts; never raises on individual cleanup failures.
        """
        await self._db.migrate()
        files_removed = 0
        rows_dropped = 0
        try:
            referenced: set[str] = {
                str(row["path"])
                for row in await self._db.fetch_all(
                    "SELECT DISTINCT path FROM library_assets"
                )
            }
        except Exception:
            referenced = set()
        if self._root.is_dir():
            for path in self._root.iterdir():
                name = path.name
                if name in referenced:
                    continue
                if not path.is_file():
                    continue
                try:
                    path.unlink()
                    files_removed += 1
                except OSError:
                    pass
        try:
            rows = await self._db.fetch_all(
                "SELECT DISTINCT path FROM library_assets"
            )
        except Exception:
            rows = []
        for row in rows:
            path = str(row["path"])
            if (self._root / path).is_file():
                continue

            def _tx(conn, _path: str = path) -> None:
                item_rows = conn.execute(
                    "SELECT DISTINCT item_uuid FROM library_assets WHERE path = ?",
                    (_path,),
                ).fetchall()
                for item_row in item_rows:
                    conn.execute(
                        "DELETE FROM library_items WHERE uuid = ?",
                        (str(item_row["item_uuid"]),),
                    )
                conn.execute(
                    "DELETE FROM library_assets WHERE path = ?", (_path,)
                )

            try:
                await transaction(self._db, _tx)
                rows_dropped += 1
            except Exception:
                pass
        return {"filesRemoved": files_removed, "rowsDropped": rows_dropped}


def _record_from_row(row) -> AssetRecord:
    # ``url`` exists since migration 0016; every caller ran migrate().
    return AssetRecord(
        uuid=str(row["uuid"]),
        item_uuid=str(row["item_uuid"]),
        path=str(row["path"]),
        bytes=int(row["bytes"]),
        sha256=str(row["sha256"]),
        mime=str(row["mime"]),
        url=str(row["url"]),
        created_at=str(row["created_at"]),
    )
