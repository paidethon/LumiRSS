"""N186 备份完整性自检独立 — verify 不建会话；四项发现 + 具体问题分类。"""

import asyncio
import hashlib
import json
import os
import sqlite3
import tempfile
import zipfile
from pathlib import Path

from lumirss.restore import verify_backup_findings
from lumirss.storage import Database


def run(coroutine):
    return asyncio.run(coroutine)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_freshrss_fixture(base: Path) -> Path:
    """最小的合法 FreshRSS 数据目录（否则完整备份诚实失败）。"""
    freshrss = base / "freshrss"
    (freshrss / "users" / "admin").mkdir(parents=True, exist_ok=True)
    (freshrss / "config.php").write_text("<?php return ['db' => 'sqlite'];\n")
    connection = sqlite3.connect(str(freshrss / "users" / "admin" / "db.sqlite"))
    connection.execute("CREATE TABLE feeds (id INTEGER PRIMARY KEY, name TEXT)")
    connection.execute("INSERT INTO feeds (name) VALUES ('Example')")
    connection.commit()
    connection.close()
    return freshrss


def _real_db_bytes() -> bytes:
    """一个真的 SQLite 文件（含一张表），integrity_check 会通过。"""
    fd, name = tempfile.mkstemp(suffix=".sqlite")
    os.close(fd)
    connection = sqlite3.connect(name)
    connection.execute("CREATE TABLE t (id INTEGER)")
    connection.execute("INSERT INTO t VALUES (1)")
    connection.commit()
    connection.close()
    return Path(name).read_bytes()


def _manifest_for(db_bytes: bytes, *, schema_version: int = 1, entries=None):
    return {
        "backupSchemaVersion": schema_version,
        "appName": "LumiRSS",
        "createdAt": "2026-09-20T00:00:00+00:00",
        "lumiVersion": "0.2.0",
        "lumiDbSchemaVersion": 3,
        "components": ["lumi.sqlite"],
        "secretPolicy": {"excludedSecrets": ["ai.api_key"], "configured": False},
        "files": entries
        or [{"path": "lumi.sqlite", "size": len(db_bytes), "sha256": _sha(db_bytes)}],
    }


def _write_package(
    zip_path: Path,
    db_bytes: bytes,
    *,
    schema_version: int = 1,
    entries=None,
    include_member: bool = True,
    manifest_override: dict | None = None,
):
    manifest = manifest_override or _manifest_for(
        db_bytes, schema_version=schema_version, entries=entries
    )
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        if include_member:
            archive.writestr("lumi.sqlite", db_bytes)


def _verify_db(tmp_path: Path) -> Database:
    db = Database(tmp_path / "live" / "lumi.sqlite")
    run(db.migrate())
    return db


def test_n186_healthy_package_all_findings_true(tmp_path):
    db_bytes = _real_db_bytes()
    zip_path = tmp_path / "healthy.backup"
    _write_package(zip_path, db_bytes)
    report = verify_backup_findings(zip_path, _verify_db(tmp_path))
    assert report["ok"] is True
    assert report["findings"] == {
        "checksumOk": True,
        "manifestCountsMatch": True,
        "readable": True,
        "versionCompatible": True,
    }
    assert report["issues"]["corruptFile"] == []
    assert report["issues"]["missingAttachment"] == []
    assert report["issues"]["versionIncompatible"] is None
    assert report["manifest"]["lumiDbSchemaVersion"] == 3


def test_n186_tampered_member_reports_corrupt_file(tmp_path):
    db_bytes = _real_db_bytes()
    zip_path = tmp_path / "tampered.backup"
    manifest = _manifest_for(db_bytes)
    tampered = db_bytes + b"--tampered"  # 归档内容被替换 → 校验和不匹配
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("lumi.sqlite", tampered)
    report = verify_backup_findings(zip_path, _verify_db(tmp_path))
    assert report["ok"] is False
    assert report["findings"]["checksumOk"] is False
    assert report["issues"]["corruptFile"] == ["lumi.sqlite"]


def test_n186_missing_attachment_listed(tmp_path):
    db_bytes = _real_db_bytes()
    zip_path = tmp_path / "missing.backup"
    entries = [
        {"path": "lumi.sqlite", "size": len(db_bytes), "sha256": _sha(db_bytes)},
        {"path": "library-assets/shot.png", "size": 3, "sha256": _sha(b"abc")},
    ]
    _write_package(zip_path, db_bytes, entries=entries)
    report = verify_backup_findings(zip_path, _verify_db(tmp_path))
    assert report["findings"]["checksumOk"] is False
    assert report["findings"]["manifestCountsMatch"] is False
    assert report["issues"]["missingAttachment"] == ["library-assets/shot.png"]


def test_n186_newer_version_incompatible(tmp_path):
    """较新 schema 的备份（旧服务器视角）：versionCompatible=false + 字段。"""
    db_bytes = _real_db_bytes()
    zip_path = tmp_path / "future.backup"
    manifest = _manifest_for(db_bytes)
    manifest["lumiDbSchemaVersion"] = 99999
    _write_package(zip_path, db_bytes, manifest_override=manifest, include_member=True)
    report = verify_backup_findings(zip_path, _verify_db(tmp_path))
    assert report["ok"] is False
    assert report["findings"]["versionCompatible"] is False
    issue = report["issues"]["versionIncompatible"]
    assert issue["field"] == "lumiDbSchemaVersion"
    assert issue["backup"] == 99999


def test_n186_older_version_still_compatible(tmp_path):
    """旧版本备份（较小 lumiDbSchemaVersion）：迁移可前滚 → 兼容为真；
    自检不因「旧」而误报不兼容（恢复路径本来支持前滚迁移）。"""
    db_bytes = _real_db_bytes()
    zip_path = tmp_path / "old.backup"
    manifest = _manifest_for(db_bytes)
    manifest["lumiDbSchemaVersion"] = 3
    _write_package(zip_path, db_bytes, manifest_override=manifest, include_member=True)
    report = verify_backup_findings(zip_path, _verify_db(tmp_path))
    assert report["ok"] is True
    assert report["findings"]["versionCompatible"] is True
    assert report["issues"]["versionIncompatible"] is None
    assert report["manifest"]["lumiDbSchemaVersion"] == 3
    assert report["manifest"]["currentDbSchemaVersion"] > 3


def test_n186_verify_api_reports_without_restore_session(tmp_path, monkeypatch):
    """API 层：POST/GET /backups/verify 只出报告——不产生 restore 会话/暂存。"""
    import time

    from fastapi.testclient import TestClient

    from lumirss.main import app

    freshrss = _make_freshrss_fixture(tmp_path)
    monkeypatch.setenv("FRESHRSS_DATA_DIR", str(freshrss))
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "lumi.sqlite"
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(db_path))
    monkeypatch.setenv("LUMIRSS_DATA_DIR", str(data_dir))

    with TestClient(app) as test_client:
        staging_root = data_dir / "restore-staging"
        # 经 API 创建完整备份（与应用相同的引擎路径）
        created = test_client.post("/api/v1/backups", json={"target": "local"})
        assert created.status_code == 202, created.text
        job_id = created.json()["id"]
        job = created.json()
        deadline = time.time() + 15
        while job["status"] in ("queued", "running") and time.time() < deadline:
            time.sleep(0.05)
            job = test_client.get(f"/api/v1/backups/{job_id}").json()
        assert job["status"] == "succeeded", job.get("safeError")

        assert not staging_root.exists() or not any(staging_root.iterdir())
        response = test_client.post(
            "/api/v1/backups/verify", json={"source": "local", "jobId": job_id}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["ok"] is True
        assert body["findings"]["readable"] is True
        # GET 形式同样可用
        get_response = test_client.get(
            "/api/v1/backups/verify", params={"source": "local", "jobId": job_id}
        )
        assert get_response.status_code == 200
        assert get_response.json()["ok"] is True
        # 未创建任何恢复会话/暂存目录
        assert not staging_root.exists() or not any(staging_root.iterdir())
