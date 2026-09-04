"""Tests for the restore state machine (0018).

Restore is the highest-risk feature: every test uses tmp paths and a crafted
backup package — the real Lumi/FreshRSS data is never touched, and no
destructive restore ever runs against real data.
"""

import asyncio
import hashlib
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from lumirss.backup import (
    BackupChecksumMismatch,
    BackupUnsupportedVersion,
)
from lumirss.restore import (
    RestoreConfirmationRequired,
    RestoreFailed,
    RestoreService,
)
from lumirss.config import LumiSettings
from lumirss.storage import Database


def run(coroutine):
    return asyncio.run(coroutine)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_package(zip_path: Path, *, schema_version: int = 3, tamper: bool = False):
    """Build a valid backup ZIP with one lumi.sqlite member."""
    db_bytes = b"sqlite-placeholder"
    if tamper:
        entry_sha = "0" * 64
    else:
        entry_sha = _sha(db_bytes)
    manifest = {
        "backupSchemaVersion": 1,
        "appName": "LumiRSS",
        "createdAt": "2026-09-04T00:00:00+00:00",
        "lumiVersion": "0.1.0",
        "lumiDbSchemaVersion": schema_version,
        "components": ["lumi.sqlite"],
        "secretPolicy": {"excludedSecrets": ["ai.api_key"], "configured": True},
        "files": [
            {"path": "lumi.sqlite", "size": len(db_bytes), "sha256": entry_sha}
        ],
    }
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("lumi.sqlite", db_bytes)


def _make_real_lumi(tmp_path: Path) -> Path:
    """A properly-migrated lumi.sqlite with a marker row."""
    db_path = tmp_path / "live" / "lumi.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    run(Database(db_path).migrate())
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO lumi_settings VALUES ('marker', 'restored-value', '2026-09-04T00:00:00+00:00')"
    )
    conn.commit()
    conn.close()
    return db_path


def _service(tmp_path, monkeypatch, db_path, safety=None):
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(db_path))
    monkeypatch.setenv("LUMIRSS_DATA_DIR", str(data_dir))
    settings = LumiSettings()
    db = Database(db_path)
    return RestoreService(db, settings, safety)


def test_valid_preview_returns_metadata(tmp_path, monkeypatch):
    zip_path = tmp_path / "pkg.backup"
    _make_package(zip_path)
    db_path = _make_real_lumi(tmp_path)
    service = _service(tmp_path, monkeypatch, db_path)
    preview = run(service.preview(zip_path))
    assert preview["restoreSessionId"]
    assert preview["compatible"] is True
    assert preview["lumiDbSchemaVersion"] == 3
    assert "lumi.sqlite" in preview["components"]


def test_future_schema_version_rejected(tmp_path, monkeypatch):
    zip_path = tmp_path / "pkg.backup"
    _make_package(zip_path, schema_version=9999)
    db_path = _make_real_lumi(tmp_path)
    service = _service(tmp_path, monkeypatch, db_path)
    with pytest.raises(BackupUnsupportedVersion):
        run(service.preview(zip_path))


def test_checksum_failure_rejected(tmp_path, monkeypatch):
    zip_path = tmp_path / "pkg.backup"
    _make_package(zip_path, tamper=True)
    db_path = _make_real_lumi(tmp_path)
    service = _service(tmp_path, monkeypatch, db_path)
    with pytest.raises(BackupChecksumMismatch):
        run(service.preview(zip_path))


def test_execute_requires_confirmation(tmp_path, monkeypatch):
    zip_path = tmp_path / "pkg.backup"
    _make_package(zip_path)
    db_path = _make_real_lumi(tmp_path)
    service = _service(tmp_path, monkeypatch, db_path)
    preview = run(service.preview(zip_path))
    with pytest.raises(RestoreConfirmationRequired):
        run(service.execute(preview["restoreSessionId"], "yes"))


def test_execute_requires_prior_preview(tmp_path, monkeypatch):
    db_path = _make_real_lumi(tmp_path)
    service = _service(tmp_path, monkeypatch, db_path)
    with pytest.raises(Exception):
        run(service.execute("nonexistent-session", "RESTORE"))


def test_restore_creates_safety_backup_and_restores(tmp_path, monkeypatch):
    # A real valid lumi.sqlite to restore INTO (live) and one to restore FROM.
    live_db = tmp_path / "live" / "lumi.sqlite"
    live_db.parent.mkdir(parents=True, exist_ok=True)
    live = Database(live_db)
    run(live.migrate())

    source_db = tmp_path / "source.sqlite"
    conn = sqlite3.connect(str(source_db))
    conn.execute("CREATE TABLE t (id INTEGER)")
    conn.execute("INSERT INTO t VALUES (777)")
    conn.commit()
    conn.close()
    source_bytes = source_db.read_bytes()

    zip_path = tmp_path / "pkg.backup"
    manifest = {
        "backupSchemaVersion": 1,
        "appName": "LumiRSS",
        "createdAt": "2026-09-04T00:00:00+00:00",
        "lumiVersion": "0.1.0",
        "lumiDbSchemaVersion": 3,
        "components": ["lumi.sqlite"],
        "secretPolicy": {"excludedSecrets": [], "configured": False},
        "files": [
            {"path": "lumi.sqlite", "size": len(source_bytes), "sha256": _sha(source_bytes)}
        ],
    }
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("lumi.sqlite", source_bytes)

    called = {"safety": 0}

    async def fake_safety():
        called["safety"] += 1
        return {"id": "safety-1", "type": "safety", "status": "succeeded"}

    service = _service(tmp_path, monkeypatch, live_db, safety=fake_safety)
    preview = run(service.preview(zip_path))
    result = run(service.execute(preview["restoreSessionId"], "RESTORE"))

    assert called["safety"] == 1
    assert result["lumiRestored"] is True
    assert result["safetyBackupId"] == "safety-1"
    assert result["health"]["sqlite"] == "healthy"

    check = sqlite3.connect(str(live_db))
    value = check.execute("SELECT id FROM t").fetchone()
    check.close()
    assert value == (777,)


def test_failed_safety_backup_reports_recovery(tmp_path, monkeypatch):
    zip_path = tmp_path / "pkg.backup"
    _make_package(zip_path)
    live_db = tmp_path / "live" / "lumi.sqlite"
    live_db.parent.mkdir(parents=True, exist_ok=True)
    run(Database(live_db).migrate())

    async def failing_safety():
        raise RuntimeError("safety backup exploded")

    service = _service(tmp_path, monkeypatch, live_db, safety=failing_safety)
    preview = run(service.preview(zip_path))
    with pytest.raises(RestoreFailed):
        run(service.execute(preview["restoreSessionId"], "RESTORE"))
