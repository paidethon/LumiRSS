"""Tests for the Lumi backup engine (0018).

Covers: manifest structure, consistent SQLite snapshots (online backup API,
never a raw copy), SHA-256 checksums, archive safety, single-concurrency and
interrupted-job recovery. All file work happens under tmp_path / monkeypatched
env — the real Lumi / FreshRSS data is never touched.
"""

import asyncio
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from lumirss.backup import (
    BackupBusy,
    BackupEngine,
    BackupFreshrssUnavailable,
    BackupInvalid,
    BackupJobStore,
    WebDavSettingsStore,
    _sha256,
    _sqlite_backup,
    build_manifest,
    _collect_freshrss_files,
)
from lumirss.secrets_store import SecretsStore
from lumirss.storage import Database


def run(coroutine):
    return asyncio.run(coroutine)


def _make_freshrss_fixture(base: Path) -> Path:
    freshrss = base / "freshrss"
    (freshrss / "users" / "admin").mkdir(parents=True, exist_ok=True)
    (freshrss / "config.php").write_text("<?php return ['db' => 'sqlite'];\n")
    connection = sqlite3.connect(str(freshrss / "users" / "admin" / "db.sqlite"))
    connection.execute("CREATE TABLE feeds (id INTEGER PRIMARY KEY, name TEXT)")
    connection.execute("INSERT INTO feeds (name) VALUES ('Example')")
    connection.commit()
    connection.close()
    return freshrss


def _setup(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "lumi.sqlite"
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(db_path))
    monkeypatch.setenv("LUMIRSS_DATA_DIR", str(data_dir))
    db = Database(db_path)
    run(db.migrate())
    run(
        db.execute(
            "INSERT INTO lumi_settings (key, value, updated_at) VALUES (?, ?, ?)",
            ("app.settings", '{"schemaVersion":1}', "2026-09-04T00:00:00+00:00"),
        )
    )
    secrets = SecretsStore(data_dir / "secrets.json")
    jobs = BackupJobStore(db)
    webdav = WebDavSettingsStore(db, secrets)

    async def no_client():
        return None

    engine = BackupEngine(db, jobs, webdav, no_client)
    return data_dir, db, jobs, engine


async def _submit_and_wait(engine, jobs, target="local"):
    job = await engine.submit_full_backup(target)
    while True:
        current = await jobs.get(job["id"])
        if current["status"] in ("succeeded", "failed", "interrupted"):
            return current
        await asyncio.sleep(0.01)


def test_sqlite_backup_produces_consistent_snapshot(tmp_path):
    src = tmp_path / "src.sqlite"
    conn = sqlite3.connect(str(src))
    conn.execute("CREATE TABLE t (id INTEGER)")
    conn.execute("INSERT INTO t VALUES (42)")
    conn.commit()
    conn.close()

    dst = tmp_path / "dst.sqlite"
    _sqlite_backup(src, dst, read_only=False)

    check = sqlite3.connect(str(dst))
    value = check.execute("SELECT id FROM t").fetchone()
    check.close()
    assert value == (42,)


def test_build_manifest_contains_required_fields():
    files = [
        {"path": "lumi.sqlite", "size": 123, "sha256": "a" * 64, "component": "lumi.sqlite"},
    ]
    manifest = build_manifest(db_schema_version=3, files=files, secret_configured=True)
    assert manifest["backupSchemaVersion"] == 1
    assert manifest["appName"] == "LumiRSS"
    assert manifest["lumiDbSchemaVersion"] == 3
    assert manifest["components"] == ["lumi.sqlite"]
    assert manifest["secretPolicy"]["configured"] is True
    assert manifest["files"][0]["sha256"] == "a" * 64


def test_full_backup_local_end_to_end(tmp_path, monkeypatch):
    freshrss = _make_freshrss_fixture(tmp_path)
    monkeypatch.setenv("FRESHRSS_DATA_DIR", str(freshrss))
    data_dir, db, jobs, engine = _setup(tmp_path, monkeypatch)

    result = run(_submit_and_wait(engine, jobs, "local"))
    assert result["status"] == "succeeded"

    summary = json.loads(result["summary"])
    archive_path = Path(summary["localPath"])
    assert archive_path.is_file()

    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        assert "manifest.json" in names
        assert "lumi.sqlite" in names
        assert "freshrss-data/config.php" in names
        assert "freshrss-data/users/admin/db.sqlite" in names
        manifest = json.loads(archive.read("manifest.json"))
        for entry in manifest["files"]:
            assert _sha256(archive.read(entry["path"])) == entry["sha256"]


def test_full_backup_requires_freshrss_when_missing(tmp_path, monkeypatch):
    data_dir, db, jobs, engine = _setup(tmp_path, monkeypatch)
    result = run(_submit_and_wait(engine, jobs, "local"))
    assert result["status"] == "failed"
    assert "FreshRSS" in result["safe_error"]


def test_corrupt_freshrss_sqlite_fails_backup_instead_of_raw_copy(tmp_path, monkeypatch):
    """AD-0018-5 回归：在线备份失败必须让整个备份诚实失败，
    绝不静默回退成对可能正在写入的 db 的逐字节复制。"""
    freshrss = _make_freshrss_fixture(tmp_path)
    # 一个扩展名是 .sqlite 但内容不是 SQLite 的文件（例如写入中途损坏）
    (freshrss / "users" / "admin" / "broken.sqlite").write_bytes(b"definitely not a database")
    monkeypatch.setenv("FRESHRSS_DATA_DIR", str(freshrss))
    data_dir, db, jobs, engine = _setup(tmp_path, monkeypatch)

    result = run(_submit_and_wait(engine, jobs, "local"))
    assert result["status"] == "failed"
    assert result["safe_error"]  # 有安全错误信息
    # 不产半成品：本地备份目录里没有归档文件
    backups_dir = data_dir / "backups"
    assert not backups_dir.exists() or not any(backups_dir.iterdir())


def test_concurrent_backup_is_rejected(tmp_path, monkeypatch):
    freshrss = _make_freshrss_fixture(tmp_path)
    monkeypatch.setenv("FRESHRSS_DATA_DIR", str(freshrss))
    data_dir, db, jobs, engine = _setup(tmp_path, monkeypatch)

    async def scenario():
        first = await engine.submit_full_backup("local")
        with pytest.raises(BackupBusy):
            await engine.submit_full_backup("local")
        # wait for the first to finish so _busy resets
        while engine.running:
            await asyncio.sleep(0.01)
        current = await jobs.get(first["id"])
        assert current["status"] == "succeeded"
        assert engine.running is False

    run(scenario())


def test_interrupted_jobs_marked_on_startup(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    jobs = BackupJobStore(db)
    run(db.migrate())
    # Simulate leftover jobs from a previous process (old created_at).
    run(
        db.execute(
            "INSERT INTO backup_jobs (id, type, status, stage, target, created_at) "
            "VALUES ('old-running', 'full', 'running', 'preparing', 'local', '2020-01-01T00:00:00+00:00')"
        )
    )
    run(
        db.execute(
            "INSERT INTO backup_jobs (id, type, status, stage, target, created_at) "
            "VALUES ('old-queued', 'full', 'queued', 'preparing', 'local', '2020-01-01T00:00:00+00:00')"
        )
    )

    count = run(jobs.mark_interrupted())
    assert count == 2

    listing = run(jobs.list())
    assert {item["id"]: item["status"] for item in listing} == {
        "old-running": "interrupted",
        "old-queued": "interrupted",
    }


def test_current_process_jobs_not_interrupted(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    jobs = BackupJobStore(db)
    run(jobs.create("full", "local"))  # created now (this process)
    run(jobs.mark_interrupted())
    listing = run(jobs.list())
    assert listing[0]["status"] != "interrupted"


def test_job_ledger_roundtrip(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    jobs = BackupJobStore(db)
    job = run(jobs.create("full", "webdav"))
    assert job["status"] == "queued"
    run(jobs.start(job["id"]))
    run(jobs.succeed(job["id"], {"filename": "x.backup"}))
    fetched = run(jobs.get(job["id"]))
    assert fetched["status"] == "succeeded"
    assert fetched["stage"] == "completed"
