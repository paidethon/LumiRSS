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
import tempfile
import time
import uuid
import zipfile
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
    """The restore failed; a recovery path exists (browser-safe message).

    N187：失败时携带已发生的逐对象决策账本（decisions），回滚到安全
    备份后账本原样呈现——绝不静默丢弃「做到哪一步」的证据。"""

    def __init__(self, message: str, decisions: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.decisions = decisions


class RestoreInvalidDecision(Exception):
    """N187：决策载荷非法（未知路径 / 非法策略值）。"""


def _validate_decisions(decisions: dict[str, str] | None) -> dict[str, str]:
    """N187：决策清洗——只接受 {'skip','overwrite'}；未知值拒绝（400）。"""
    if not decisions:
        return {}
    clean: dict[str, str] = {}
    for path, strategy in decisions.items():
        value = str(strategy).strip().lower()
        if value not in ("skip", "overwrite"):
            raise RestoreInvalidDecision(
                f"Invalid strategy for {str(path)[:100]}: {value[:40]}"
            )
        clean[str(path)] = value
    return clean


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


def verify_backup_findings(zip_path: Path, db: Database) -> dict[str, Any]:
    """N186 独立完整性自检（只读；不建恢复会话、不写任何状态）。

    复用 preview 的校验内核——_load_manifest 的 manifest 结构/版本规则、
    _sha256_stream 的流式哈希口径、_sqlite_snapshot_is_valid 的
    integrity 口径——但逐项分类为发现（findings + 具体问题），而不是
    首个失败即抛异常中断，让「哪里坏了」显式呈现。"""
    findings: dict[str, bool] = {
        "checksumOk": True,
        "manifestCountsMatch": True,
        "readable": True,
        "versionCompatible": True,
    }
    issues: dict[str, Any] = {
        "corruptFile": [],
        "missingAttachment": [],
        "versionIncompatible": None,
    }
    manifest_summary: dict[str, Any] | None = None

    def _report() -> dict[str, Any]:
        ok = all(findings.values())
        manifest_block = dict(manifest_summary) if manifest_summary is not None else None
        return {
            "ok": ok,
            "findings": findings,
            "issues": issues,
            "manifest": manifest_block,
        }

    def _fail_version(field: str, backup: Any, current: Any) -> None:
        findings["versionCompatible"] = False
        issues["versionIncompatible"] = {
            "field": field,
            "backup": backup,
            "current": current,
        }

    try:
        archive = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, EOFError, RuntimeError, OSError):
        # 归档整体不可读：四项发现按「无法验证 = 不通过」如实报告。
        findings["checksumOk"] = False
        findings["manifestCountsMatch"] = False
        findings["readable"] = False
        issues["corruptFile"].append(zip_path.name)
        return _report()

    with archive:
        names = set(archive.namelist())
        manifest: dict[str, Any] | None = None
        try:
            manifest = _load_manifest(archive)
        except BackupUnsupportedVersion:
            # manifest 本身可解析，只是版本更新：继续对余下内容做诚实
            # 自检（re-parse 一次以获得 files），并标注不兼容。
            try:
                candidate = json.loads(archive.read("manifest.json").decode("utf-8"))
            except Exception:  # noqa: BLE001 — 损坏如实报告
                candidate = None
            if (
                isinstance(candidate, dict)
                and isinstance(candidate.get("files"), list)
                and candidate["files"]
            ):
                manifest = candidate
            else:
                findings["manifestCountsMatch"] = False
                findings["readable"] = False
                issues["corruptFile"].append("manifest.json")
        except BackupInvalid:
            findings["manifestCountsMatch"] = False
            findings["readable"] = False
            issues["corruptFile"].append("manifest.json")

        if manifest is None:
            return _report()

        manifest_summary = {
            "createdAt": manifest.get("createdAt"),
            "lumiVersion": manifest.get("lumiVersion"),
            "lumiDbSchemaVersion": manifest.get("lumiDbSchemaVersion"),
            "currentDbSchemaVersion": _current_db_schema(db),
            "components": manifest.get("components", []),
        }

        # ---- 版本兼容（与 preview 同口径：backupSchemaVersion 上限 +
        #      lumiDbSchemaVersion 不得超过当前库）----
        schema_version = manifest.get("backupSchemaVersion")
        if schema_version != BACKUP_SCHEMA_VERSION:
            _fail_version("backupSchemaVersion", schema_version, BACKUP_SCHEMA_VERSION)
        db_version = manifest.get("lumiDbSchemaVersion")
        if not isinstance(db_version, int):
            findings["versionCompatible"] = False
            issues["versionIncompatible"] = {
                "field": "lumiDbSchemaVersion",
                "backup": db_version,
                "current": _current_db_schema(db),
            }
        elif db_version > _current_db_schema(db):
            _fail_version("lumiDbSchemaVersion", db_version, _current_db_schema(db))

        # ---- 逐文件 checksum / size（缺 → missingAttachment；不匹配 →
        #      corruptFile），复用 restore 的流式哈希口径 ----
        declared: set[str] = {"manifest.json"}
        for entry in manifest["files"]:
            path = entry.get("path")
            if not isinstance(path, str) or not path:
                findings["manifestCountsMatch"] = False
                issues["corruptFile"].append("manifest.json")
                continue
            declared.add(path)
            if path not in names:
                findings["checksumOk"] = False
                findings["manifestCountsMatch"] = False
                issues["missingAttachment"].append(path)
                continue
            expected_sha = entry.get("sha256")
            expected_size = entry.get("size")
            if not isinstance(expected_sha, str) or not isinstance(expected_size, int):
                findings["manifestCountsMatch"] = False
                issues["corruptFile"].append(path)
                continue
            try:
                info = archive.getinfo(path)
                if info.file_size > MAX_MEMBER_BYTES:
                    raise BackupInvalid("Backup contains an oversized file.")
                with archive.open(path) as member:
                    digest = _sha256_stream(member)
                if digest != expected_sha or info.file_size != expected_size:
                    findings["checksumOk"] = False
                    issues["corruptFile"].append(path)
            except (
                zipfile.BadZipFile,
                EOFError,
                RuntimeError,
                OSError,
                BackupInvalid,
            ):
                findings["checksumOk"] = False
                findings["readable"] = False
                issues["corruptFile"].append(path)

        # ---- 计数一致：声明集合与归档成员一一对应（多余成员同属失配）----
        undeclared = names - declared
        if undeclared:
            findings["manifestCountsMatch"] = False
            issues["corruptFile"].extend(sorted(undeclared)[:10])

        # ---- 可读性：lumi.sqlite 成员 integrity_check（有界落盘后检查）----
        if "lumi.sqlite" in names and findings["checksumOk"]:
            fd, tmp_name = tempfile.mkstemp(prefix=".verify-", suffix=".sqlite")
            os.close(fd)
            tmp = Path(tmp_name)
            try:
                info = archive.getinfo("lumi.sqlite")
                if info.file_size <= MAX_MEMBER_BYTES:
                    with archive.open("lumi.sqlite") as member, tmp.open("wb") as out:
                        while True:
                            chunk = member.read(1024 * 1024)
                            if not chunk:
                                break
                            out.write(chunk)
                    if not _sqlite_snapshot_is_valid(tmp):
                        findings["readable"] = False
                        issues["corruptFile"].append("lumi.sqlite")
            except (zipfile.BadZipFile, EOFError, RuntimeError, OSError):
                findings["readable"] = False
                issues["corruptFile"].append("lumi.sqlite")
            finally:
                tmp.unlink(missing_ok=True)

    return _report()


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
        """Validate a backup package and return a preview + session id.

        N187：preview 附带逐对象冲突清单（components 预览）——每个可
        恢复对象与活动状态比对 exists/differs，Web 恢复向导的冲突步骤
        由此渲染（策略 skip|overwrite，缺省 skip = 保留现状）。"""
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

        files = manifest.get("files", [])
        conflicts = await asyncio.to_thread(
            self._conflict_inventory, files
        )
        preview = {
            "restoreSessionId": session_id,
            "createdAt": manifest.get("createdAt"),
            "lumiVersion": manifest.get("lumiVersion"),
            "lumiDbSchemaVersion": db_version,
            "currentDbSchemaVersion": current_schema,
            "compatible": db_version <= current_schema,
            "components": manifest.get("components", []),
            "files": files,
            "excludedSecrets": manifest.get("secretPolicy", {}).get(
                "excludedSecrets", []
            ),
            "secretConfigured": manifest.get("secretPolicy", {}).get(
                "configured", False
            ),
            # N187：逐对象冲突清单（[{path, component, exists, differs}]）。
            "conflicts": conflicts,
        }
        return preview

    def _conflict_inventory(self, files: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """N187：备份成员 vs 活动状态的存在/内容差异清单（纯只读）。

        - lumi.sqlite 整库对象与活动库文件比对（大小/存在性）；
        - library-assets/ 与 freshrss-data/ 成员逐个比对同相对路径。"""
        entries: list[dict[str, Any]] = []
        live_db = Path(str(self._settings.LUMIRSS_DB_PATH)).expanduser()
        for entry in files:
            path = entry.get("path")
            if not isinstance(path, str) or not path:
                continue
            component = (
                "lumi"
                if path == "lumi.sqlite"
                else (
                    "library-assets"
                    if path.startswith("library-assets/")
                    else "freshrss" if path.startswith("freshrss-data/") else "other"
                )
            )
            if component == "lumi":
                live = live_db
            elif component == "library-assets":
                live = (
                    Path(self._settings.data_dir)
                    / "library"
                    / "assets"
                    / Path(path).relative_to("library-assets")
                )
            elif component == "freshrss":
                live = (
                    self._settings.restore_staging_dir
                    / "restore-ready"
                    / "freshrss"
                    / Path(path).relative_to("freshrss-data")
                )
            else:
                continue
            exists = live.is_file()
            differs = False
            if exists:
                expected_size = entry.get("size")
                if isinstance(expected_size, int) and expected_size != live.stat().st_size:
                    differs = True
                else:
                    expected_sha = entry.get("sha256")
                    if isinstance(expected_sha, str) and exists:
                        try:
                            differs = _sha256_file(live) != expected_sha
                        except OSError:
                            differs = True
            entries.append(
                {
                    "path": path,
                    "component": component,
                    "exists": exists,
                    "differs": exists and differs,
                }
            )
        return entries

    async def execute(
        self,
        session_id: str,
        confirmation: str,
        decisions: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Run the destructive restore (already previewed + explicitly confirmed).

        N187：``decisions`` 逐对象策略（path → 'skip'|'overwrite'；缺省
        skip = 保留活动现状）。对象级语义：

        - lumi.sqlite：overwrite → 整库在线恢复；skip → 活动库原封不动；
        - library-assets/*：overwrite → 逐文件复制覆盖；skip → 不动该文件；
        - freshrss-data/*：overwrite → 暂存离线恢复；skip → 不暂存。

        会话记录决策账本（restored/skipped/overwritten 计数 + 样本）；
        失败 → 安全备份保留（既有）且账本随 RestoreFailed.decisions 呈现。"""
        if confirmation.strip() != "RESTORE":
            raise RestoreConfirmationRequired(
                'Type "RESTORE" to confirm the destructive restore.'
            )
        session = self._sessions.get(session_id)
        if session is None:
            raise RestorePreviewRequired("Run a restore preview first.")
        clean_decisions = _validate_decisions(decisions)
        zip_path = session["zip"]
        stage = session["stage"]
        if not zip_path.is_file():
            raise BackupNotFound("The backup file is no longer available.")

        ledger: dict[str, Any] = {
            "restored": 0,
            "skipped": 0,
            "overwritten": 0,
            "samples": [],
            "decisions": dict(clean_decisions),
        }
        session["decisions"] = ledger
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

            # 4. Restore lumi.sqlite in place (online backup API) — only when
            # the operator chose overwrite for the whole-db object (N187:
            # default skip keeps the live database untouched).
            result: dict[str, Any] = {
                "lumiRestored": False,
                "freshrss": "not_included",
                "libraryAssets": "not_included",
                "safetyBackupId": safety_job["id"] if safety_job else None,
            }
            if "lumi.sqlite" in extracted:
                if clean_decisions.get("lumi.sqlite", "skip") == "overwrite":
                    await self._restore_lumi(extracted["lumi.sqlite"])
                    result["lumiRestored"] = True
                    ledger["overwritten"] += 1
                    ledger["samples"].append({"path": "lumi.sqlite", "outcome": "overwritten"})
                else:
                    ledger["skipped"] += 1
                    ledger["samples"].append({"path": "lumi.sqlite", "outcome": "skipped"})

            # 4b. Library assets are Lumi-owned bytes (ADR 0004): restore
            # them in place — unlike FreshRSS data they need no offline
            # staging, the app owns this directory exclusively.
            assets_files = [p for p in extracted if p.startswith("library-assets/")]
            if assets_files:
                assets_target = Path(self._settings.data_dir) / "library" / "assets"
                restored_assets, skipped_assets = await asyncio.to_thread(
                    self._restore_library_assets,
                    assets_files,
                    extracted,
                    assets_target,
                    clean_decisions,
                    ledger,
                )
                result["libraryAssets"] = restored_assets

            # 5. FreshRSS: stage for offline restore (never write live).
            freshrss_files = [p for p in extracted if p.startswith("freshrss-data/")]
            if freshrss_files and clean_decisions.get("freshrss-data/", "overwrite") == "overwrite":
                ready_dir = self._settings.restore_staging_dir / "restore-ready" / "freshrss"
                await asyncio.to_thread(
                    self._stage_freshrss_offline, freshrss_files, extracted, ready_dir
                )
                result["freshrss"] = "offline_restore_required"
                result["freshrssStagedAt"] = str(ready_dir)
            elif freshrss_files:
                ledger["skipped"] += len(freshrss_files)
                ledger["samples"].append(
                    {"path": "freshrss-data/", "outcome": "skipped"}
                )

            shutil.rmtree(extract_dir, ignore_errors=True)
            result["health"] = await self._health_after_restore()
            result["decisions"] = {
                "restored": ledger["restored"],
                "skipped": ledger["skipped"],
                "overwritten": ledger["overwritten"],
                "samples": ledger["samples"][:10],
            }
            self._sessions.pop(session_id, None)
            return result
        except RestoreFailed as exc:
            self._sessions.pop(session_id, None)
            raise RestoreFailed(str(exc), decisions=ledger) from exc
        except Exception as exc:
            # Keep the safety backup and the original backup; no stacktrace,
            # no credentials. Every unexpected failure becomes a safe,
            # recoverable RestoreFailed — with the decision ledger intact.
            self._sessions.pop(session_id, None)
            raise RestoreFailed(
                "Restore failed. The current state was backed up and the "
                "original backup was kept; review the backup history.",
                decisions=ledger,
            ) from exc

    @staticmethod
    def _restore_library_assets(
        assets_files: list[str],
        extracted: dict[str, Path],
        target_root: Path,
        decisions: dict[str, str] | None = None,
        ledger: dict[str, Any] | None = None,
    ) -> tuple[int, int]:
        """Copy archived asset bytes back into the live assets directory
        (runs in a thread). Existing files with the same relative path
        are replaced; the manifest sha256 was verified during extraction.

        N187：逐文件策略（skip = 保留活动文件不动；overwrite/缺省决策
        仅当显式 overwrite 才覆盖）。返回 (restored, skipped)。"""
        restored = 0
        skipped = 0
        for rel in assets_files:
            strategy = (decisions or {}).get(rel, "skip")
            if strategy != "overwrite":
                skipped += 1
                if ledger is not None:
                    ledger["skipped"] += 1
                    ledger["samples"].append({"path": rel, "outcome": "skipped"})
                continue
            source = extracted[rel]
            target = target_root / Path(rel).relative_to("library-assets")
            target.parent.mkdir(parents=True, exist_ok=True)
            exists_before = target.is_file()
            shutil.copy2(source, target)
            restored += 1
            if ledger is not None:
                if exists_before:
                    ledger["overwritten"] += 1
                    ledger["samples"].append(
                        {"path": rel, "outcome": "overwritten"}
                    )
                else:
                    ledger["restored"] += 1
                    ledger["samples"].append({"path": rel, "outcome": "restored"})
        return restored, skipped

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
