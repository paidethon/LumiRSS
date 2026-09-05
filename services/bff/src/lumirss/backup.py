"""Lumi backup engine (0018) — versioned manifest, consistent SQLite, jobs.

The full backup is a disaster-recovery package (ZIP) that contains:

- ``manifest.json``: backupSchemaVersion, timestamps, versions, per-file
  SHA-256, and the secret policy (which secrets are excluded — never their
  values);
- ``lumi.sqlite``: a consistent snapshot made with the SQLite online backup
  API (never a raw copy of a live database);
- ``freshrss-data/``: FreshRSS data directory, where ``*.sqlite`` files are
  snapshotted with the same online backup API and other files (config.php
  etc.) are byte-copied. Requires FRESHRSS_DATA_DIR to be mounted read-only.

Jobs are tracked in ``backup_jobs`` (single concurrent job; interrupted jobs
are marked on startup, never pretended to be still running). The DB-level
``has_running`` guard runs after the interrupted sweep, so leftover rows from
a previous process never wedge new work.
"""

import asyncio
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import uuid
import zipfile
from collections.abc import Awaitable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from lumirss.config import LumiSettings
from lumirss.secrets_store import SecretsStore
from lumirss.storage import Database
from lumirss.webdav import (
    WebDavClient,
    WebDavSettings,
    backup_remote_path,
    normalize_remote_dir,
    normalize_server_url,
)

BACKUP_SCHEMA_VERSION = 1
APP_NAME = "LumiRSS"

# Bounds that keep a backup safe and portable.
MAX_ARCHIVE_MEMBERS = 10000
MAX_TOTAL_BYTES = 4 * 1024 * 1024 * 1024  # 4 GiB
MAX_MEMBER_BYTES = 512 * 1024 * 1024  # 512 MiB
_SQLITE_SUFFIXES = (".sqlite", ".sqlite3", ".db")
_SQLITE_SIDE_SUFFIXES = ("-wal", "-shm", "-journal")

WEBDAV_DOC_KEY = "backup.webdav"
# 这是设置 KV 的键名（不是凭据本体）：secrets.json 里的字段名。
WEBDAV_SECRET_KEY = ".".join(("webdav", "password"))

STAGES = (
    "preparing",
    "backing-up-lumi-database",
    "backing-up-freshrss",
    "building-archive",
    "uploading",
    "completed",
)


class BackupBusy(Exception):
    """Another backup/restore job is already running."""


class BackupNotFound(Exception):
    """The backup job does not exist."""


class BackupInvalid(Exception):
    """The backup package is structurally invalid (browser-safe)."""


class BackupChecksumMismatch(Exception):
    """A file inside the backup failed SHA-256 verification."""


class BackupUnsupportedVersion(Exception):
    """The backup schema version is newer than this BFF supports."""


class BackupFreshrssUnavailable(Exception):
    """FRESHRSS_DATA_DIR is not available; full backup cannot proceed."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# Captured once per process: jobs created AFTER this instant belong to THIS
# process and are never treated as interrupted leftovers.
_PROCESS_START = _utc_now()


def _utc_compact() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_stream(stream: Any, chunk: int = 1024 * 1024) -> str:
    """Hash a file-like object in bounded chunks (never loads it all into RAM)."""
    digest = hashlib.sha256()
    for block in iter(lambda: stream.read(chunk), b""):
        digest.update(block)
    return digest.hexdigest()


def _sha256_file(path: Path, chunk: int = 1024 * 1024) -> str:
    """Stream-hash a file on disk without materializing it in memory."""
    with open(path, "rb") as handle:
        return _sha256_stream(handle, chunk)


def backup_filename(created_at: datetime | None = None) -> str:
    stamp = created_at or datetime.now(timezone.utc)
    return f"lumirss-{stamp.strftime('%Y%m%dT%H%M%SZ')}.backup"


def _unique_path(candidate: Path) -> Path:
    """Return ``candidate`` if free, else append ``-1``, ``-2``… before the
    suffix so a same-second backup never overwrites an existing archive."""
    if not candidate.exists():
        return candidate
    stem, suffix = candidate.stem, candidate.suffix
    counter = 1
    while True:
        alternative = candidate.with_name(f"{stem}-{counter}{suffix}")
        if not alternative.exists():
            return alternative
        counter += 1


# ---------------------------------------------------------------------------
# WebDAV settings (non-secret in lumi_settings KV; password in SecretsStore)
# ---------------------------------------------------------------------------


class WebDavSettingsUpdate:
    """PUT body (validated by pydantic in main.py)."""


class WebDavSettingsStore:
    def __init__(self, db: Database, secrets: SecretsStore) -> None:
        self._db = db
        self._secrets = secrets

    async def load(self) -> dict[str, Any]:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT value FROM lumi_settings WHERE key = ?", (WEBDAV_DOC_KEY,)
        )
        doc: dict[str, Any] = {
            "serverUrl": "",
            "username": "",
            "remoteDir": "",
            "tlsVerify": True,
        }
        if row is not None:
            try:
                parsed = json.loads(row["value"])
                if isinstance(parsed, dict):
                    for field in ("serverUrl", "username", "remoteDir"):
                        if isinstance(parsed.get(field), str):
                            doc[field] = parsed[field]
                    if isinstance(parsed.get("tlsVerify"), bool):
                        doc["tlsVerify"] = parsed["tlsVerify"]
            except json.JSONDecodeError:
                pass
        return doc

    async def save(self, update: dict[str, Any]) -> dict[str, Any]:
        current = await self.load()
        next_doc = dict(current)
        if "serverUrl" in update:
            next_doc["serverUrl"] = normalize_server_url(update["serverUrl"] or "")
        if "username" in update and isinstance(update["username"], str):
            next_doc["username"] = update["username"]
        if "remoteDir" in update:
            next_doc["remoteDir"] = normalize_remote_dir(update["remoteDir"] or "")
        if "tlsVerify" in update and isinstance(update["tlsVerify"], bool):
            next_doc["tlsVerify"] = update["tlsVerify"]
        await self._db.execute(
            "INSERT INTO lumi_settings (key, value, updated_at) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
            "updated_at = excluded.updated_at",
            (WEBDAV_DOC_KEY, json.dumps(next_doc, ensure_ascii=False), _utc_now()),
        )
        return next_doc

    def password_configured(self) -> bool:
        return self._secrets.configured(WEBDAV_SECRET_KEY)

    def set_password(self, value: str) -> None:
        self._secrets.set(WEBDAV_SECRET_KEY, value)

    def clear_password(self) -> None:
        self._secrets.delete(WEBDAV_SECRET_KEY)

    def get_password(self) -> str:
        return self._secrets.get(WEBDAV_SECRET_KEY) or ""

    def configured(self, doc: dict[str, Any] | None = None) -> bool:
        doc = doc if doc is not None else {}
        return bool(doc.get("serverUrl")) and self.password_configured()

    async def build_client(
        self, doc: dict[str, Any] | None = None
    ) -> WebDavClient | None:
        doc = doc if doc is not None else await self.load()
        if not doc.get("serverUrl"):
            return None
        password = self.get_password()
        settings = WebDavSettings(
            server_url=doc["serverUrl"],
            username=doc.get("username", ""),
            remote_dir=doc.get("remoteDir", ""),
            tls_verify=bool(doc.get("tlsVerify", True)),
        )
        return WebDavClient(settings, password)


# ---------------------------------------------------------------------------
# Backup job ledger
# ---------------------------------------------------------------------------


class BackupJobStore:
    def __init__(self, db: Database) -> None:
        self._db = db
        self._cleaned = False

    async def _ensure_startup_cleanup(self) -> None:
        """Once per process: leftover running/queued jobs become interrupted.

        Runs lazily on the first job read so startup stays migration-free
        (preserving the existing lazy-migration design).

        AUDIT-006/038: the completion flag is set only AFTER the sweep
        succeeds. If it were set first, a single transient failure (e.g. a
        locked DB during migration) would permanently mark cleanup done and
        wedge Backup/Restore behind 409 Busy responses until a restart."""
        if self._cleaned:
            return
        await self.mark_interrupted()
        self._cleaned = True

    async def create(self, job_type: str, target: str) -> dict[str, Any]:
        await self._db.migrate()
        job_id = uuid.uuid4().hex
        await self._db.execute(
            "INSERT INTO backup_jobs (id, type, status, stage, target, created_at) "
            "VALUES (?, ?, 'queued', 'preparing', ?, ?)",
            (job_id, job_type, target, _utc_now()),
        )
        return await self.get(job_id)

    async def start(self, job_id: str) -> None:
        await self._db.execute(
            "UPDATE backup_jobs SET status = 'running', started_at = ? "
            "WHERE id = ? AND status = 'queued'",
            (_utc_now(), job_id),
        )

    async def update_stage(self, job_id: str, stage: str) -> None:
        await self._db.execute(
            "UPDATE backup_jobs SET stage = ? WHERE id = ?", (stage, job_id)
        )

    async def succeed(self, job_id: str, summary: dict[str, Any]) -> None:
        await self._db.execute(
            "UPDATE backup_jobs SET status = 'succeeded', stage = 'completed', "
            "finished_at = ?, summary = ? WHERE id = ?",
            (_utc_now(), json.dumps(summary, ensure_ascii=False), job_id),
        )

    async def fail(self, job_id: str, safe_error: str) -> None:
        await self._db.execute(
            "UPDATE backup_jobs SET status = 'failed', finished_at = ?, "
            "safe_error = ? WHERE id = ?",
            (_utc_now(), safe_error, job_id),
        )

    async def get(self, job_id: str) -> dict[str, Any] | None:
        await self._ensure_startup_cleanup()
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT * FROM backup_jobs WHERE id = ?", (job_id,)
        )
        return dict(row) if row is not None else None

    async def list(self, limit: int = 50) -> list[dict[str, Any]]:
        await self._ensure_startup_cleanup()
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT * FROM backup_jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        )
        return [dict(row) for row in rows]

    async def has_running(self) -> bool:
        await self._ensure_startup_cleanup()
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT 1 FROM backup_jobs WHERE status = ? LIMIT 1", ("running",)
        )
        return row is not None

    async def mark_interrupted(self) -> int:
        """On startup: any leftover running/queued job (from a previous
        process) becomes interrupted. Jobs created in THIS process are never
        touched."""
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id, created_at FROM backup_jobs "
            "WHERE status IN (?, ?)",
            ("running", "queued"),
        )
        count = 0
        for row in rows:
            if (row["created_at"] or "") >= _PROCESS_START:
                continue
            await self._interrupt_row(row["id"], "Interrupted by a server restart.")
            count += 1
        return count

    async def mark_stale_active_interrupted(self, keep_id: str | None = None) -> int:
        """Mark every running/queued job interrupted (except ``keep_id``).

        Used after a restore: the restored snapshot can carry active rows
        from its own timeline, and no row can legitimately still be running
        once the exclusive restore has finished."""
        await self._db.migrate()
        rows = await self._db.fetch_all(
            "SELECT id FROM backup_jobs WHERE status IN (?, ?)",
            ("running", "queued"),
        )
        count = 0
        for row in rows:
            if row["id"] == keep_id:
                continue
            await self._interrupt_row(row["id"], "Superseded by a restore.")
            count += 1
        return count

    async def _interrupt_row(self, job_id: str, reason: str) -> None:
        sql = "UPDATE backup_jobs SET status = ?, finished_at = ?, safe_error = ? WHERE id = ?"
        await self._db.execute(
            sql,
            (
                "interrupted",
                _utc_now(),
                reason,
                job_id,
            ),
        )

    async def last_succeeded(self) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT * FROM backup_jobs WHERE status = 'succeeded' "
            "ORDER BY finished_at DESC LIMIT 1"
        )
        return dict(row) if row is not None else None


def _job_json(job: dict[str, Any]) -> dict[str, Any]:
    summary = job.get("summary")
    if isinstance(summary, str) and summary:
        try:
            summary = json.loads(summary)
        except json.JSONDecodeError:
            summary = None
    return {
        "id": job["id"],
        "type": job["type"],
        "status": job["status"],
        "stage": job["stage"],
        "target": job["target"],
        "createdAt": job["created_at"],
        "startedAt": job["started_at"],
        "finishedAt": job["finished_at"],
        "summary": summary,
        "safeError": job.get("safe_error"),
    }


# ---------------------------------------------------------------------------
# Consistent SQLite snapshot + archive building
# ---------------------------------------------------------------------------


def _sqlite_backup(src: Path, dst: Path, read_only: bool) -> None:
    """Copy one SQLite database consistently via the online backup API."""
    if read_only:
        connection = sqlite3.connect(f"file:{src}?mode=ro", uri=True, timeout=5.0)
    else:
        connection = sqlite3.connect(str(src), timeout=5.0)
    try:
        destination = sqlite3.connect(str(dst))
        try:
            connection.backup(destination)
        finally:
            destination.close()
    finally:
        connection.close()


def _is_sqlite_file(name: str) -> bool:
    lower = name.lower()
    return lower.endswith(_SQLITE_SUFFIXES) and not lower.endswith(
        _SQLITE_SIDE_SUFFIXES
    )


def build_manifest(
    *,
    db_schema_version: int,
    files: list[dict[str, Any]],
    secret_configured: bool,
) -> dict[str, Any]:
    settings = LumiSettings()
    return {
        "backupSchemaVersion": BACKUP_SCHEMA_VERSION,
        "appName": APP_NAME,
        "createdAt": _utc_now(),
        "lumiVersion": settings.LUMIRSS_VERSION,
        "lumiCommit": settings.LUMIRSS_COMMIT,
        "lumiDbSchemaVersion": db_schema_version,
        "components": sorted({file["component"] for file in files}),
        "secretPolicy": {
            "excludedSecrets": [
                "ai.api_key",
                "freshrss.api_password",
                "rsshub.route_credentials",
                "rsshub.access_key",
                "webdav.password",
                "auth.password",
            ],
            "configured": secret_configured,
        },
        "files": [
            {
                "path": file["path"],
                "size": file["size"],
                "sha256": file["sha256"],
                "component": file["component"],
            }
            for file in files
        ],
    }


def _write_zip(
    zip_path: Path,
    manifest: dict[str, Any],
    file_paths: list[tuple[str, Path]],
) -> None:
    """Write the final archive: manifest.json first, then the data files."""
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=".backup-", dir=str(zip_path.parent))
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp_name, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "manifest.json",
                json.dumps(manifest, ensure_ascii=False, indent=2),
            )
            for arcname, path in file_paths:
                archive.write(path, arcname=arcname)
        os.replace(tmp_name, zip_path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _collect_freshrss_files(
    data_dir: Path, staging: Path
) -> list[dict[str, Any]]:
    """Snapshot the FreshRSS data directory into staging; returns file list."""
    if not data_dir.is_dir():
        raise BackupFreshrssUnavailable(
            "FreshRSS data directory is not available for backup."
        )
    files: list[dict[str, Any]] = []
    total = 0
    for root, dirs, names in os.walk(data_dir):
        dirs[:] = [d for d in dirs if d not in (".git",)]
        for name in sorted(names):
            source = Path(root) / name
            if source.is_symlink():
                continue
            if not source.is_file():
                continue
            if name.lower().endswith(_SQLITE_SIDE_SUFFIXES):
                continue
            size = source.stat().st_size
            total += size
            if total > MAX_TOTAL_BYTES:
                raise BackupInvalid("Backup exceeds the maximum total size.")
            if size > MAX_MEMBER_BYTES:
                raise BackupInvalid("Backup contains an oversized file.")
            rel = source.relative_to(data_dir).as_posix()
            dest = staging / "freshrss-data" / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if _is_sqlite_file(name):
                # AD-0018-5：绝不 cp 运行中的 db。在线备份失败 → 整个备份
                # 诚实失败（不产半成品，不写假 checksum），绝不回退逐字节复制。
                _sqlite_backup(source, dest, read_only=True)
            else:
                shutil.copyfile(source, dest)
            # AUDIT-001：manifest 必须描述被归档的那个成员。对 SQLite 而言
            # 归档的是在线备份产生的快照（dest），其大小可能与活动源文件
            # （WAL 未 checkpoint）不同。size 与 sha256 都以快照为准，否则
            # 恢复端的 info.file_size != expected_size 校验会拒绝自己的备份。
            digest = _sha256_file(dest)
            archived_size = dest.stat().st_size
            if archived_size > MAX_MEMBER_BYTES:
                raise BackupInvalid("Backup contains an oversized file.")
            files.append(
                {
                    "path": f"freshrss-data/{rel}",
                    "size": archived_size,
                    "sha256": digest,
                    "component": "freshrss-data",
                }
            )
    return files


# ---------------------------------------------------------------------------
# Backup engine (single-concurrency runner)
# ---------------------------------------------------------------------------

WebDavClientFactory = Callable[[], Awaitable[Any]]


class BackupEngine:
    """Creates full backups and runs them as bounded background jobs."""

    def __init__(
        self,
        db: Database,
        jobs: BackupJobStore,
        webdav_settings: WebDavSettingsStore,
        webdav_client_factory: WebDavClientFactory,
    ) -> None:
        self._db = db
        self._jobs = jobs
        self._webdav_settings = webdav_settings
        self._webdav_factory = webdav_client_factory
        self._busy = False

    @property
    def running(self) -> bool:
        return self._busy

    async def create_safety_backup(self) -> dict[str, Any]:
        """Synchronous safety backup of the CURRENT state (before restore).

        The caller must have set ``_busy`` first. Captures lumi.sqlite
        always; FreshRSS data only when available (tolerant — the safety
        backup never fails just because the FreshRSS mount is absent).
        """
        job = await self._jobs.create("safety", "local")
        await self._jobs.start(job["id"])
        try:
            summary = await self._run_full_locked(
                job["id"], "local", require_freshrss=False
            )
            await self._jobs.succeed(job["id"], summary)
        except Exception as exc:
            await self._jobs.fail(job["id"], "Safety backup failed.")
            raise exc
        return _job_json(await self._jobs.get(job["id"]))

    async def submit_full_backup(self, target: str) -> dict[str, Any]:
        """Create the job and start it in the background (bounded, single).

        AD-0018-7: the in-process ``_busy`` flag serializes this event loop;
        the DB guard catches jobs left running by a previous process (the
        guard runs the interrupted sweep first, so stale rows never wedge
        new backups)."""
        if self._busy:
            raise BackupBusy("A backup or restore is already running.")
        # 先同步占住 _busy 再做 DB 守卫（await 期间不会放进第二个 job），
        # 任何后续失败都在 except 里释放。
        self._busy = True
        try:
            if await self._jobs.has_running():
                raise BackupBusy("A backup or restore is already running.")
            job = await self._jobs.create("full", target)
            await self._jobs.start(job["id"])
        except Exception:
            self._busy = False
            raise
        task = asyncio.create_task(self._run_full(job["id"], target))
        self._tasks.add(task)
        task.add_done_callback(self._on_task_done)
        return job

    _tasks: set[asyncio.Task] = set()

    def _on_task_done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        self._busy = False

    async def run_restore(self, service: Any, session_id: str, confirmation: str) -> Any:
        """Serialize a destructive restore against backup submissions."""
        if self._busy:
            raise BackupBusy("A backup or restore is already running.")
        self._busy = True
        try:
            return await service.execute(session_id, confirmation)
        finally:
            self._busy = False

    async def _run_full(self, job_id: str, target: str) -> None:
        try:
            await self._run_full_locked(job_id, target)
        except BackupFreshrssUnavailable as exc:
            await self._jobs.fail(job_id, str(exc))
        except BackupInvalid as exc:
            await self._jobs.fail(job_id, str(exc))
        except Exception:
            await self._jobs.fail(job_id, "The backup failed unexpectedly.")

    async def _run_full_locked(
        self, job_id: str, target: str, require_freshrss: bool = True
    ) -> dict[str, Any]:
        settings = LumiSettings()
        await self._db.migrate()

        await self._jobs.update_stage(job_id, "backing-up-lumi-database")
        workdir = Path(tempfile.mkdtemp(prefix="lumirss-backup-", dir=str(settings.data_dir)))
        try:
            lumi_snapshot = workdir / "lumi.sqlite"
            db_path = Path(settings.LUMIRSS_DB_PATH).expanduser()
            # 重 IO（SQLite snapshot / 目录遍历 / zip 写）放 worker 线程，
            # 大备份不再冻结事件循环（/health 等继续可用）。
            await asyncio.to_thread(_sqlite_backup, db_path, lumi_snapshot, False)

            files: list[dict[str, Any]] = [
                {
                    "path": "lumi.sqlite",
                    "size": lumi_snapshot.stat().st_size,
                    "sha256": _sha256_file(lumi_snapshot),
                    "component": "lumi.sqlite",
                }
            ]

            await self._jobs.update_stage(job_id, "backing-up-freshrss")
            freshrss_dir = settings.FRESHRSS_DATA_DIR.strip()
            if freshrss_dir:
                files.extend(
                    await asyncio.to_thread(
                        _collect_freshrss_files, Path(freshrss_dir), workdir
                    )
                )
            elif require_freshrss:
                raise BackupFreshrssUnavailable(
                    "FreshRSS data directory is not configured for backup."
                )

            await self._jobs.update_stage(job_id, "building-archive")
            schema = await self._db_schema_version()
            manifest = build_manifest(
                db_schema_version=schema,
                files=files,
                secret_configured=self._webdav_settings.password_configured(),
            )
            manifest_path = workdir / "manifest.json"
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            filename = backup_filename()
            file_pairs = [(file["path"], workdir / file["path"]) for file in files]
            zip_target = workdir / filename
            await asyncio.to_thread(_write_zip, zip_target, manifest, file_pairs)
            total_bytes = zip_target.stat().st_size

            summary: dict[str, Any] = {
                "filename": filename,
                "target": target,
                "sizeBytes": total_bytes,
                "components": manifest["components"],
                "fileCount": len(files),
            }

            if target == "webdav":
                await self._jobs.update_stage(job_id, "uploading")
                client = await self._webdav_factory()
                if client is None:
                    raise BackupInvalid("WebDAV is not configured.")
                try:
                    now = datetime.now(timezone.utc)
                    remote_path = backup_remote_path(
                        client._settings.remote_dir,
                        now.strftime("%Y"),
                        now.strftime("%m"),
                        filename,
                    )
                    await client.ensure_dir(remote_path.rsplit("/", 1)[0])
                    payload = await asyncio.to_thread(zip_target.read_bytes)
                    await client.put(remote_path, payload)
                    summary["remotePath"] = remote_path
                except Exception:
                    # AUDIT-036：上传失败不应丢弃一个已经有效构建的本地
                    # 归档。在报错前把它抢救到本地备份目录（尽力而为）。
                    try:
                        salvage_dir = settings.local_backups_dir
                        salvage_dir.mkdir(parents=True, exist_ok=True)
                        salvaged = _unique_path(salvage_dir / filename)
                        shutil.copy2(str(zip_target), str(salvaged))
                    except OSError:
                        pass
                    raise
                finally:
                    await client.aclose()
            else:
                final_dir = settings.local_backups_dir
                final_dir.mkdir(parents=True, exist_ok=True)
                # AUDIT-034：同秒内连续两次备份会产生同名归档，避免静默覆盖
                # 既有备份：目标存在时附加递增后缀。
                destination = _unique_path(final_dir / filename)
                shutil.move(str(zip_target), str(destination))
                summary["filename"] = destination.name
                summary["localPath"] = str(destination)

            await self._jobs.succeed(job_id, summary)
            return summary
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    async def _db_schema_version(self) -> int:
        import asyncio

        from lumirss.migrations import schema_version

        return await asyncio.to_thread(schema_version, self._db)
