"""Restore state machine (0018) — the highest-risk feature.

A restore NEVER overwrites live data immediately. The flow is:

    select → download → checksum → manifest → compatibility → preview
    → safety backup (current state) → explicit confirm ("RESTORE")
    → restore → health validation → success / recovery

Component-specific behavior:

- lumi.sqlite is restored IN PLACE using the SQLite online backup API,
  after a safety backup of the current state and after integrity checks;
- FreshRSS data is NEVER written into the running FreshRSS volume: it is
  staged under ``restore-ready/freshrss/`` and the operator is given the
  official offline steps. The UI must say "Ready for offline restore",
  not "restored".

All failures keep the safety backup, keep the original backup, record the
failure stage and return a safe (stacktrace-free, credential-free) message.
"""

import asyncio
import json
import os
import posixpath
import shutil
import sqlite3
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from lumirss.backup import (
    BACKUP_SCHEMA_VERSION,
    MAX_ARCHIVE_MEMBERS,
    MAX_MEMBER_BYTES,
    MAX_TOTAL_BYTES,
    BackupChecksumMismatch,
    BackupInvalid,
    BackupNotFound,
    BackupUnsupportedVersion,
    _sha256_file,
    _sha256_stream,
)
from lumirss.config import LumiSettings
from lumirss.storage import Database


class RestoreConfirmationRequired(Exception):
    """The confirmation word was missing or wrong."""


class RestorePreviewRequired(Exception):
    """Execute was called before a successful preview."""


class RestoreFailed(Exception):
    """The restore failed; a recovery path exists (browser-safe message)."""


def _current_db_schema(db: Database) -> int:
    from lumirss.migrations import schema_version

    return schema_version(db)


def _sqlite_snapshot_is_valid(path: Path) -> bool:
    """True only when ``PRAGMA integrity_check`` reports ``ok`` for the file.

    A non-SQLite / corrupt snapshot raises ``sqlite3.Error`` and is treated as
    invalid, so the caller never swaps it into the live database."""
    try:
        connection = sqlite3.connect(str(path))
        try:
            row = connection.execute("PRAGMA integrity_check").fetchone()
        finally:
            connection.close()
    except sqlite3.Error:
        return False
    return row is not None and str(row[0]).lower() == "ok"


def _load_manifest(archive: zipfile.ZipFile) -> dict[str, Any]:
    try:
        raw = archive.read("manifest.json")
    except KeyError as exc:
        raise BackupInvalid("Backup is missing its manifest.") from exc
    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BackupInvalid("Backup manifest is not valid JSON.") from exc
    if not isinstance(manifest, dict):
        raise BackupInvalid("Backup manifest has an invalid shape.")
    version = manifest.get("backupSchemaVersion")
    if not isinstance(version, int):
        raise BackupInvalid("Backup manifest is missing a schema version.")
    if version > BACKUP_SCHEMA_VERSION:
        raise BackupUnsupportedVersion(
            "This backup was created by a newer LumiRSS version."
        )
    if version < 1:
        raise BackupInvalid("Backup manifest has an unsupported schema version.")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise BackupInvalid("Backup manifest has no file list.")
    return manifest


def _verify_checksums(archive: zipfile.ZipFile, manifest: dict[str, Any]) -> None:
    names = set(archive.namelist())
    declared: set[str] = {"manifest.json"}
    total = 0
    for entry in manifest["files"]:
        path = entry.get("path")
        if not isinstance(path, str):
            raise BackupInvalid("Backup manifest has an invalid file entry.")
        if path not in names:
            raise BackupInvalid("Backup is missing a declared file.")
        declared.add(path)
        info = archive.getinfo(path)
        expected_sha = entry.get("sha256")
        expected_size = entry.get("size")
        if not isinstance(expected_sha, str) or not isinstance(expected_size, int):
            raise BackupInvalid("Backup manifest has an invalid file entry.")
        # AUDIT-005：在对成员做昂贵读取之前先强制边界。声明大小、
        # 实际大小、压缩比与总量均在流式哈希前校验，避免将任意大
        # 成员一次性读入内存。
        if expected_size > MAX_MEMBER_BYTES or info.file_size > MAX_MEMBER_BYTES:
            raise BackupInvalid("Backup contains an oversized file.")
        if info.compress_size > 0 and info.file_size / info.compress_size > 200:
            raise BackupInvalid("Backup contains a suspicious compression ratio.")
        total += info.file_size
        if total > MAX_TOTAL_BYTES:
            raise BackupInvalid("Backup exceeds the maximum total size.")
        if info.file_size != expected_size:
            raise BackupChecksumMismatch("Backup file size does not match the manifest.")
        with archive.open(path) as member:
            digest = _sha256_stream(member)
        if digest != expected_sha:
            raise BackupChecksumMismatch("Backup failed checksum verification.")
    # 未在 manifest.files 声明的成员没有 checksum 覆盖 = 不可信内容，
    # 直接拒绝（manifest.json 是归档自身元数据，除外）。
    undeclared = names - declared
    if undeclared:
        raise BackupInvalid("Backup contains files not declared in the manifest.")


def _reject_unsafe_member(name: str, info: zipfile.ZipInfo) -> str:
    """Return the normalized safe relative path, or raise BackupInvalid."""
    if "\x00" in name:
        raise BackupInvalid("Backup contains an invalid file name.")
    normalized = posixpath.normpath(name.replace("\\", "/"))
    if normalized.startswith(("/", "..")) or normalized == "..":
        raise BackupInvalid("Backup contains an unsafe path.")
    drive = normalized.split("/", 1)[0]
    if ":" in drive:
        raise BackupInvalid("Backup contains an unsafe path.")
    mode = (info.external_attr >> 16) & 0o170000
    if mode == 0o120000:
        raise BackupInvalid("Backup contains a symbolic link.")
    return normalized


def safe_extract(
    archive: zipfile.ZipFile,
    dest_dir: Path,
    manifest: dict[str, Any],
) -> dict[str, Path]:
    """Verify then extract; rejects traversal, symlinks, duplicates, bombs."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    members = archive.infolist()
    if len(members) > MAX_ARCHIVE_MEMBERS:
        raise BackupInvalid("Backup contains too many files.")
    seen: set[str] = set()
    total = 0
    planned: list[tuple[str, zipfile.ZipInfo]] = []
    for info in members:
        if info.is_dir():
            continue
        name = _reject_unsafe_member(info.filename, info)
        if name in seen:
            raise BackupInvalid("Backup contains duplicate file entries.")
        seen.add(name)
        if info.file_size > MAX_MEMBER_BYTES:
            raise BackupInvalid("Backup contains an oversized file.")
        if info.compress_size > 0 and info.file_size / info.compress_size > 200:
            raise BackupInvalid("Backup contains a suspicious compression ratio.")
        total += info.file_size
        if total > MAX_TOTAL_BYTES:
            raise BackupInvalid("Backup exceeds the maximum total size.")
        planned.append((name, info))

    expected = {entry["path"]: entry for entry in manifest["files"]}
    extracted: dict[str, Path] = {}
    root = dest_dir.resolve()
    for name, info in planned:
        # zipfile.extract 会自行清洗成员路径（去除绝对路径前缀、'.',
        # '..' 段），返回清洗后的实际落盘路径；随后再做一次解析后
        # 包含检查，确认仍在目标目录内才允许继续。
        written = Path(archive.extract(info, dest_dir))
        target = written.resolve()
        if target != root and not target.is_relative_to(root):
            raise BackupInvalid("Backup contains an unsafe path.")
        manifest_entry = expected.get(name)
        if manifest_entry is not None:
            digest = _sha256_file(target)
            if digest != manifest_entry["sha256"]:
                raise BackupChecksumMismatch(
                    "Backup failed checksum verification."
                )
        extracted[name] = target
    return extracted


class RestoreService:
    """Preview + execute restore over a validated package."""

    def __init__(
        self,
        db: Database,
        settings: LumiSettings,
        safety_backup: Any,
    ) -> None:
        self._db = db
        self._settings = settings
        self._safety_backup = safety_backup
        self._sessions: dict[str, dict[str, Any]] = {}

    def _stage_dir(self, session_id: str) -> Path:
        return self._settings.restore_staging_dir / session_id

    # 单用户场景下的有界保留：最多同时持有 8 个 preview 会话 + 最近 24h
    # 的远端下载缓存；超出的会话/下载物在下次 preview 时清理。
    MAX_SESSIONS = 8
    DOWNLOAD_MAX_AGE_SECONDS = 24 * 3600

    def _prune_staging(self) -> None:
        staging = self._settings.restore_staging_dir
        live_ids = set(self._sessions)
        if staging.is_dir():
            for entry in staging.iterdir():
                if not entry.is_dir():
                    continue
                if entry.name in ("downloads", "restore-ready"):
                    continue
                if entry.name not in live_ids:
                    shutil.rmtree(entry, ignore_errors=True)
            downloads = staging / "downloads"
            if downloads.is_dir():
                cutoff = time.time() - self.DOWNLOAD_MAX_AGE_SECONDS
                for file in downloads.iterdir():
                    try:
                        if file.is_file() and file.stat().st_mtime < cutoff:
                            file.unlink()
                    except OSError:
                        pass
        # 会话数上限：最旧的先出
        overflow = len(self._sessions) - self.MAX_SESSIONS
        if overflow > 0:
            for session_id in list(self._sessions)[:overflow]:
                session = self._sessions.pop(session_id)
                shutil.rmtree(session["stage"], ignore_errors=True)

    @staticmethod
    def _verify_package(zip_path: Path) -> dict[str, Any]:
        """CPU/IO-bound manifest + checksum verification (runs in a thread)."""
        try:
            with zipfile.ZipFile(zip_path) as archive:
                manifest = _load_manifest(archive)
                _verify_checksums(archive, manifest)
        except (zipfile.BadZipFile, EOFError, RuntimeError, OSError) as exc:
            # AUDIT：损坏/截断/非 ZIP 的用户输入必须返回稳定的 Lumi
            # 错误（400 backup_invalid），而不是泄漏一个通用 500。
            raise BackupInvalid("Backup is not a valid archive.") from exc
        return manifest

    @staticmethod
    def _extract_package(zip_path: Path, extract_dir: Path) -> dict[str, Any]:
        """Re-verify then safe-extract (runs in a thread)."""
        try:
            with zipfile.ZipFile(zip_path) as archive:
                manifest = _load_manifest(archive)
                _verify_checksums(archive, manifest)
                extract_dir.mkdir(parents=True, exist_ok=True)
                safe_extract(archive, extract_dir, manifest)
        except (zipfile.BadZipFile, EOFError, RuntimeError) as exc:
            raise BackupInvalid("Backup is not a valid archive.") from exc
        return manifest

    async def preview(self, zip_path: Path) -> dict[str, Any]:
        """Validate a backup package and return a preview + session id."""
        self._prune_staging()
        session_id = uuid.uuid4().hex
        stage = self._stage_dir(session_id)
        stage.mkdir(parents=True, exist_ok=True)
        self._sessions[session_id] = {"zip": zip_path, "stage": stage}

        try:
            manifest = await asyncio.to_thread(self._verify_package, zip_path)
        except Exception:
            shutil.rmtree(stage, ignore_errors=True)
            self._sessions.pop(session_id, None)
            raise

        db_version = manifest.get("lumiDbSchemaVersion")
        if not isinstance(db_version, int):
            shutil.rmtree(stage, ignore_errors=True)
            self._sessions.pop(session_id, None)
            raise BackupInvalid("Backup manifest is missing the database schema version.")
        current_schema = _current_db_schema(self._db)
        if db_version > current_schema:
            shutil.rmtree(stage, ignore_errors=True)
            self._sessions.pop(session_id, None)
            raise BackupUnsupportedVersion(
                "This backup has a newer database schema than this server."
            )

        preview = {
            "restoreSessionId": session_id,
            "createdAt": manifest.get("createdAt"),
            "lumiVersion": manifest.get("lumiVersion"),
            "lumiDbSchemaVersion": db_version,
            "currentDbSchemaVersion": current_schema,
            "compatible": db_version <= current_schema,
            "components": manifest.get("components", []),
            "files": manifest.get("files", []),
            "excludedSecrets": manifest.get("secretPolicy", {}).get(
                "excludedSecrets", []
            ),
            "secretConfigured": manifest.get("secretPolicy", {}).get(
                "configured", False
            ),
        }
        return preview

    async def execute(self, session_id: str, confirmation: str) -> dict[str, Any]:
        """Run the destructive restore (already previewed + explicitly confirmed)."""
        if confirmation.strip() != "RESTORE":
            raise RestoreConfirmationRequired(
                'Type "RESTORE" to confirm the destructive restore.'
            )
        session = self._sessions.get(session_id)
        if session is None:
            raise RestorePreviewRequired("Run a restore preview first.")
        zip_path = session["zip"]
        stage = session["stage"]
        if not zip_path.is_file():
            raise BackupNotFound("The backup file is no longer available.")

        safety_job = None
        try:
            # 1. Re-verify (tamper check between preview and execute), then
            # 2/3. safety backup + safe extraction (heavy IO in worker threads).
            await asyncio.to_thread(self._verify_package, zip_path)

            # 2. Safety backup of the CURRENT state.
            safety_job = await self._safety_backup()

            # 3. Extract safely.
            extract_dir = stage / "extracted"
            manifest = await asyncio.to_thread(self._extract_package, zip_path, extract_dir)
            extracted = {
                entry["path"]: extract_dir / entry["path"] for entry in manifest["files"]
            }

            # 4. Restore lumi.sqlite in place (online backup API).
            result: dict[str, Any] = {
                "lumiRestored": False,
                "freshrss": "not_included",
                "safetyBackupId": safety_job["id"] if safety_job else None,
            }
            if "lumi.sqlite" in extracted:
                await self._restore_lumi(extracted["lumi.sqlite"])
                result["lumiRestored"] = True

            # 5. FreshRSS: stage for offline restore (never write live).
            freshrss_files = [p for p in extracted if p.startswith("freshrss-data/")]
            if freshrss_files:
                ready_dir = self._settings.restore_staging_dir / "restore-ready" / "freshrss"
                await asyncio.to_thread(
                    self._stage_freshrss_offline, freshrss_files, extracted, ready_dir
                )
                result["freshrss"] = "offline_restore_required"
                result["freshrssStagedAt"] = str(ready_dir)

            shutil.rmtree(extract_dir, ignore_errors=True)
            result["health"] = await self._health_after_restore()
            self._sessions.pop(session_id, None)
            return result
        except RestoreFailed:
            self._sessions.pop(session_id, None)
            raise
        except Exception as exc:
            # Keep the safety backup and the original backup; no stacktrace,
            # no credentials. Every unexpected failure becomes a safe,
            # recoverable RestoreFailed.
            self._sessions.pop(session_id, None)
            raise RestoreFailed(
                "Restore failed. The current state was backed up and the "
                "original backup was kept; review the backup history."
            ) from exc

    @staticmethod
    def _stage_freshrss_offline(
        freshrss_files: list[str],
        extracted: dict[str, Path],
        ready_dir: Path,
    ) -> None:
        """Copy staged FreshRSS files to restore-ready (runs in a thread)."""
        if ready_dir.exists():
            shutil.rmtree(ready_dir)
        ready_dir.mkdir(parents=True, exist_ok=True)
        for rel in freshrss_files:
            source = extracted[rel]
            target = ready_dir / Path(rel).relative_to("freshrss-data")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)

    def _restore_lumi_sync(self, restored_snapshot: Path) -> None:
        db_path = Path(self._settings.LUMIRSS_DB_PATH).expanduser()
        # AUDIT-004：先用 PRAGMA integrity_check 验证待恢复快照，绝不把
        # 已知会失败的快照写回活动数据库。预检查失败 → 活动库原封不动。
        if not _sqlite_snapshot_is_valid(restored_snapshot):
            raise RestoreFailed(
                "The backup database failed its integrity check; the live "
                "database was left untouched."
            )
        source = sqlite3.connect(str(restored_snapshot))
        try:
            destination = sqlite3.connect(str(db_path), timeout=10.0)
            try:
                source.backup(destination)  # snapshot -> live (online restore)
            finally:
                destination.close()
        finally:
            source.close()
        # 防御性：交换后再次验证已恢复的活动数据库（defense-in-depth）。
        check = sqlite3.connect(str(db_path), timeout=10.0)
        try:
            result = check.execute("PRAGMA integrity_check").fetchone()
        finally:
            check.close()
        if result is None or str(result[0]).lower() != "ok":
            raise RestoreFailed("The restored database failed its integrity check.")
        self._db.invalidate_migration_cache()

    async def _restore_lumi(self, restored_snapshot: Path) -> None:
        await asyncio.to_thread(self._restore_lumi_sync, restored_snapshot)

    async def _health_after_restore(self) -> dict[str, Any]:
        try:
            await self._db.migrate()
            return {"sqlite": "healthy"}
        except Exception:
            return {"sqlite": "unavailable"}
