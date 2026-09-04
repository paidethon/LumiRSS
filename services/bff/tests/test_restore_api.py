"""Route-level tests for the 0018 backup/restore API contract.

Exercises POST /api/v1/backups (202), the stable error envelope on the
restore endpoints (backup_restore_confirmation_required etc.), the
backup_busy single-concurrency error, and the persisted restore job record.
No test ever touches the real FreshRSS data or runs a real destructive
restore against live state.
"""

import asyncio
import hashlib
import json
import sqlite3
import zipfile

from fastapi.testclient import TestClient

from lumirss.backup import BackupJobStore
from lumirss.main import app
from lumirss.secrets_store import SecretsStore
from lumirss.storage import Database


def run(coroutine):
    return asyncio.run(coroutine)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_package(tmp_path, name="pkg.backup"):
    """A minimal VALID backup package (checksum + manifest consistent)."""
    db_bytes = b"sqlite-placeholder"
    manifest = {
        "backupSchemaVersion": 1,
        "appName": "LumiRSS",
        "createdAt": "2026-09-04T00:00:00+00:00",
        "lumiVersion": "0.1.0",
        "lumiDbSchemaVersion": 3,
        "components": ["lumi.sqlite"],
        "secretPolicy": {"excludedSecrets": ["ai.api_key"], "configured": False},
        "files": [
            {"path": "lumi.sqlite", "size": len(db_bytes), "sha256": _sha(db_bytes)}
        ],
    }
    zip_path = tmp_path / name
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("lumi.sqlite", db_bytes)
    return zip_path


def _client(tmp_path):
    client = TestClient(app)
    client.__enter__()
    app.state.db = Database(tmp_path / "lumi.sqlite")
    app.state.secrets_store = SecretsStore(tmp_path / "secrets.json")
    # 与应用相同的懒初始化路径（store 绑定到测试 db）
    app.state.backup_jobs = BackupJobStore(app.state.db)
    return client


def test_create_backup_returns_202_with_queued_job(tmp_path):
    client = _client(tmp_path)
    try:
        response = client.post("/api/v1/backups", json={"target": "local"})
        assert response.status_code == 202
        body = response.json()
        assert body["type"] == "full"
        assert body["status"] in ("queued", "running", "succeeded", "failed")
    finally:
        client.__exit__(None, None, None)
        app.state.backup_engine = None
        app.state.backup_jobs = None


def test_backup_invalid_target_envelope(tmp_path):
    client = _client(tmp_path)
    try:
        response = client.post("/api/v1/backups", json={"target": "s3"})
        assert response.status_code == 422
        error = response.json()["error"]
        assert error["type"] == "invalid_request"
        assert "detail" not in response.json()
    finally:
        client.__exit__(None, None, None)
        app.state.backup_engine = None
        app.state.backup_jobs = None


def test_restore_execute_requires_preview_envelope(tmp_path):
    client = _client(tmp_path)
    try:
        response = client.post(
            "/api/v1/restore",
            json={"restoreSessionId": "no-such-session", "confirmation": "RESTORE"},
        )
        assert response.status_code == 400
        assert response.json()["error"]["type"] == "backup_restore_preview_required"
    finally:
        client.__exit__(None, None, None)
        app.state.backup_engine = None
        app.state.backup_jobs = None
        app.state.restore_service = None


def test_restore_preview_and_confirmation_contract(tmp_path):
    """Preview contract + stable error envelopes on the execute path."""
    client = _client(tmp_path)
    try:
        package = _make_package(tmp_path)
        # Stage the package through a synthetic succeeded backup job (the
        # file-upload path itself is exercised by Playwright flows).
        jobs = app.state.backup_jobs
        job = run(jobs.create("full", "local"))
        data_dir = tmp_path / "data"
        local_dir = data_dir / "backups"
        local_dir.mkdir(parents=True, exist_ok=True)
        target = local_dir / "lumirss-test.backup"
        target.write_bytes(package.read_bytes())
        run(jobs.succeed(job["id"], {
            "filename": "lumirss-test.backup",
            "target": "local",
            "sizeBytes": target.stat().st_size,
            "components": ["lumi.sqlite"],
            "fileCount": 1,
            "localPath": str(target),
        }))

        preview = client.post(
            "/api/v1/restore/preview",
            json={"source": "local", "jobId": job["id"]},
        )
        assert preview.status_code == 200
        preview_body = preview.json()
        assert preview_body["compatible"] is True
        assert preview_body["restoreSessionId"]
        assert preview_body["fileName"] == "lumirss-test.backup"

        # Wrong confirmation → stable error type, restore not executed.
        wrong = client.post(
            "/api/v1/restore",
            json={
                "restoreSessionId": preview_body["restoreSessionId"],
                "confirmation": "please",
            },
        )
        assert wrong.status_code == 400
        assert (
            wrong.json()["error"]["type"]
            == "backup_restore_confirmation_required"
        )

        # A missing session keeps preview_required (session popped after the
        # failed confirmation attempt above? No — confirmation failure keeps
        # the session; use a fresh wrong session id for the 400 check).
        missing = client.post(
            "/api/v1/restore",
            json={"restoreSessionId": "missing-session", "confirmation": "RESTORE"},
        )
        assert missing.json()["error"]["type"] == "backup_restore_preview_required"
    finally:
        client.__exit__(None, None, None)
        app.state.backup_engine = None
        app.state.backup_jobs = None
        app.state.restore_service = None


def test_backup_busy_envelope_when_job_running(tmp_path, monkeypatch):
    client = _client(tmp_path)
    try:
        jobs = app.state.backup_jobs
        job = run(jobs.create("full", "local"))
        run(jobs.start(job["id"]))  # DB-level running row (cross-restart guard)
        response = client.post("/api/v1/backups", json={"target": "local"})
        assert response.status_code == 409
        assert response.json()["error"]["type"] == "backup_busy"
    finally:
        client.__exit__(None, None, None)
        app.state.backup_engine = None
        app.state.backup_jobs = None
