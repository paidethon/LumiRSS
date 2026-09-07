"""Full-backup capability preflight tests.

Covers the honest assessment shared by GET /api/v1/backups/capabilities
and the execution-time validation: every reason the engine could refuse a
full backup must be detectable BEFORE the user clicks, with the same
verdict at execution time. All fixtures live under tmp_path.
"""

import asyncio
import json
import sqlite3
import stat
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lumirss.backup import (
    BackupEngine,
    BackupJobStore,
    WebDavSettingsStore,
    assess_freshrss_backup,
)
from lumirss.main import app
from lumirss.secrets_store import SecretsStore
from lumirss.storage import Database


def run(coroutine):
    return asyncio.run(coroutine)


def _make_freshrss_fixture(base: Path, db_type: str = "sqlite") -> Path:
    freshrss = base / "freshrss"
    (freshrss / "users" / "admin").mkdir(parents=True, exist_ok=True)
    (freshrss / "config.php").write_text(
        f"<?php return ['db' => ['type' => '{db_type}']];\n"
    )
    connection = sqlite3.connect(str(freshrss / "users" / "admin" / "db.sqlite"))
    connection.execute("CREATE TABLE feeds (id INTEGER PRIMARY KEY, name TEXT)")
    connection.execute("INSERT INTO feeds (name) VALUES ('Example')")
    connection.commit()
    connection.close()
    return freshrss


# ---------------------------------------------------------------------------
# assess_freshrss_backup — each failure reason is detectable pre-click
# ---------------------------------------------------------------------------


def test_assess_not_configured():
    assessment = assess_freshrss_backup("")
    assert assessment.available is False
    assert assessment.reason_code == "not_configured"
    assert "not configured" in (assessment.safe_reason or "")


def test_assess_path_missing(tmp_path):
    assessment = assess_freshrss_backup(str(tmp_path / "nope"))
    assert assessment.available is False
    assert assessment.reason_code == "path_missing"


def test_assess_not_a_directory(tmp_path):
    plain_file = tmp_path / "plain.txt"
    plain_file.write_text("not a dir")
    assessment = assess_freshrss_backup(str(plain_file))
    assert assessment.available is False
    assert assessment.reason_code == "not_a_directory"


def test_assess_invalid_empty_directory(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    assessment = assess_freshrss_backup(str(empty))
    assert assessment.available is False
    assert assessment.reason_code == "invalid_data_dir"


def test_assess_external_database_is_rejected(tmp_path):
    freshrss = _make_freshrss_fixture(tmp_path, db_type="mysql")
    assessment = assess_freshrss_backup(str(freshrss))
    assert assessment.available is False
    assert assessment.reason_code == "external_database"
    assert assessment.db_type == "mysql"


def test_assess_unreadable_file(tmp_path):
    freshrss = _make_freshrss_fixture(tmp_path)
    locked = freshrss / "users" / "admin" / "secret.db"
    locked.write_bytes(b"locked")
    locked.chmod(0)
    try:
        assessment = assess_freshrss_backup(str(freshrss))
        assert assessment.available is False
        assert assessment.reason_code == "unreadable_entries"
    finally:
        locked.chmod(stat.S_IRUSR | stat.S_IWUSR)


def test_assess_untraversable_directory(tmp_path):
    """FreshRSS users/<name>/ is 0770: a BFF that cannot enter it must NOT
    get a green preflight while os.walk silently skips the user database."""
    freshrss = _make_freshrss_fixture(tmp_path)
    (freshrss / "users" / "secret").mkdir()
    (freshrss / "users" / "secret" / "db.sqlite").write_bytes(b"x")
    (freshrss / "users" / "secret").chmod(0)
    try:
        assessment = assess_freshrss_backup(str(freshrss))
        assert assessment.available is False
        assert assessment.reason_code == "unreadable_entries"
    finally:
        (freshrss / "users" / "secret").chmod(stat.S_IRWXU)


def test_assess_valid_sqlite_directory(tmp_path):
    freshrss = _make_freshrss_fixture(tmp_path)
    assessment = assess_freshrss_backup(str(freshrss))
    assert assessment.available is True
    assert assessment.reason_code is None
    assert assessment.db_type == "sqlite"
    assert assessment.sqlite_file_count == 1
    assert assessment.file_count >= 2  # config.php + users/admin/db.sqlite


# ---------------------------------------------------------------------------
# Execution-time: the engine refuses with the SAME verdict, not a vaguer one
# ---------------------------------------------------------------------------


def _setup(tmp_path, monkeypatch, freshrss_dir: str):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "lumi.sqlite"
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(db_path))
    monkeypatch.setenv("LUMIRSS_DATA_DIR", str(data_dir))
    monkeypatch.setenv("FRESHRSS_DATA_DIR", freshrss_dir)
    db = Database(db_path)
    run(db.migrate())
    secrets = SecretsStore(data_dir / "secrets.json")
    jobs = BackupJobStore(db)
    webdav = WebDavSettingsStore(db, secrets)

    async def no_client():
        return None

    engine = BackupEngine(db, jobs, webdav, no_client)
    return engine


async def _submit_and_wait(engine, jobs, target="local"):
    job = await engine.submit_full_backup(target)
    while True:
        current = await jobs.get(job["id"])
        if current["status"] in ("succeeded", "failed", "interrupted"):
            return current
        await asyncio.sleep(0.01)


def test_engine_refuses_when_not_configured(tmp_path, monkeypatch):
    engine = _setup(tmp_path, monkeypatch, "")
    current = run(_submit_and_wait(engine, engine._jobs))
    assert current["status"] == "failed"
    assert current["safe_error"] == (
        "FreshRSS data directory is not configured for backup."
    )


def test_engine_refuses_external_database(tmp_path, monkeypatch):
    freshrss = _make_freshrss_fixture(tmp_path, db_type="pgsql")
    engine = _setup(tmp_path, monkeypatch, str(freshrss))
    current = run(_submit_and_wait(engine, engine._jobs))
    assert current["status"] == "failed"
    assert "external MySQL/PostgreSQL" in (current["safe_error"] or "")


def test_engine_refuses_missing_directory(tmp_path, monkeypatch):
    engine = _setup(tmp_path, monkeypatch, str(tmp_path / "absent"))
    current = run(_submit_and_wait(engine, engine._jobs))
    assert current["status"] == "failed"
    assert current["safe_error"] == (
        "The configured FreshRSS data directory does not exist."
    )


def test_engine_still_succeeds_with_valid_directory(tmp_path, monkeypatch):
    freshrss = _make_freshrss_fixture(tmp_path)
    engine = _setup(tmp_path, monkeypatch, str(freshrss))
    current = run(_submit_and_wait(engine, engine._jobs))
    assert current["status"] == "succeeded"
    summary = json.loads(current["summary"])
    assert set(summary["components"]) == {"lumi.sqlite", "freshrss-data"}


# ---------------------------------------------------------------------------
# GET /api/v1/backups/capabilities
# ---------------------------------------------------------------------------


def _client(tmp_path, monkeypatch, freshrss_dir: str) -> TestClient:
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    db_path = tmp_path / "lumi.sqlite"
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(db_path))
    monkeypatch.setenv("LUMIRSS_DATA_DIR", str(data_dir))
    monkeypatch.setenv("FRESHRSS_DATA_DIR", freshrss_dir)
    run(Database(db_path).migrate())
    client = TestClient(app)
    client.__enter__()
    app.state.db = Database(db_path)
    app.state.secrets_store = SecretsStore(data_dir / "secrets.json")
    return client


def test_capabilities_ready(tmp_path, monkeypatch):
    freshrss = _make_freshrss_fixture(tmp_path)
    with _client(tmp_path, monkeypatch, str(freshrss)) as client:
        response = client.get("/api/v1/backups/capabilities")
        assert response.status_code == 200
        payload = response.json()
        assert payload["fullBackupReady"] is True
        assert payload["lumiDatabaseAvailable"] is True
        assert payload["includes"] == ["lumi.sqlite", "freshrss-data"]
        fresh = payload["freshrssData"]
        assert fresh["available"] is True
        assert fresh["reasonCode"] is None
        assert fresh["dbType"] == "sqlite"
        assert fresh["sqliteFileCount"] == 1


def test_capabilities_reports_not_configured(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch, "") as client:
        payload = client.get("/api/v1/backups/capabilities").json()
        assert payload["fullBackupReady"] is False
        assert payload["includes"] == ["lumi.sqlite"]
        fresh = payload["freshrssData"]
        assert fresh["available"] is False
        assert fresh["reasonCode"] == "not_configured"
        assert fresh["reason"]


@pytest.mark.parametrize("db_type", ["mysql", "pgsql"])
def test_capabilities_reports_external_database(tmp_path, monkeypatch, db_type):
    freshrss = _make_freshrss_fixture(tmp_path, db_type=db_type)
    with _client(tmp_path, monkeypatch, str(freshrss)) as client:
        payload = client.get("/api/v1/backups/capabilities").json()
        assert payload["fullBackupReady"] is False
        fresh = payload["freshrssData"]
        assert fresh["available"] is False
        assert fresh["reasonCode"] == "external_database"
        assert fresh["dbType"] == db_type
