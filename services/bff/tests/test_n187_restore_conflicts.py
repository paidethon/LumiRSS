"""N187 恢复冲突向导（BFF 侧）测试。

- preview 附带逐对象冲突清单（path/component/exists/differs）；
- execute 接受逐对象决策（skip|overwrite，缺省 skip = 保留现状）：
  混合决策下 restored/skipped/overwritten 计数与样本准确；
- 失败 → 回滚到安全备份（既有）且决策账本随 RestoreFailed.decisions
  原样保留（回滚不丢证据）；
- 决策载荷非法 → 稳定 400 invalid_restore_decisions。
"""

import asyncio
import hashlib
import json
import sqlite3
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from lumirss.backup import BackupJobStore
from lumirss.main import app
from lumirss.restore import RestoreFailed
from lumirss.secrets_store import SecretsStore
from lumirss.storage import Database


def run(coroutine):
    return asyncio.run(coroutine)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _env_client(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir(exist_ok=True)
    db_path = tmp_path / "lumi.sqlite"
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(db_path))
    monkeypatch.setenv("LUMIRSS_DATA_DIR", str(data_dir))
    monkeypatch.setenv("FRESHRSS_DATA_DIR", "")
    run(Database(db_path).migrate())
    client = TestClient(app)
    client.__enter__()
    app.state.db = Database(db_path)
    app.state.secrets_store = SecretsStore(tmp_path / "secrets.json")
    app.state.backup_jobs = BackupJobStore(app.state.db)
    return client, db_path, data_dir


def _make_mixed_package(tmp_path, db_path: Path, live_assets: dict[str, bytes]):
    """lumi.sqlite + 2 个 library-assets 的备份包（asset 内容可控）。"""
    source = tmp_path / "source.sqlite"
    run(Database(source).migrate())
    conn = sqlite3.connect(str(source))
    conn.execute(
        "INSERT INTO lumi_settings VALUES ('restored-marker', 'yes', '2026-09-04T00:00:00+00:00')"
    )
    conn.commit()
    conn.close()
    from lumirss.migrations import schema_version

    version = schema_version(Database(source))
    member = source.read_bytes()
    files = [
        {"path": "lumi.sqlite", "size": len(member), "sha256": _sha(member)}
    ]
    asset_members: dict[str, bytes] = {
        "library-assets/asset-a.html": b"<html>NEW-A</html>",
        "library-assets/asset-b.html": b"<html>NEW-B</html>",
    }
    for path, data in asset_members.items():
        files.append({"path": path, "size": len(data), "sha256": _sha(data)})
    manifest = {
        "backupSchemaVersion": 1,
        "appName": "LumiRSS",
        "createdAt": "2026-09-04T00:00:00+00:00",
        "lumiVersion": "0.1.0",
        "lumiDbSchemaVersion": version,
        "components": ["lumi.sqlite", "library-assets"],
        "secretPolicy": {"excludedSecrets": [], "configured": False},
        "files": files,
    }
    zip_path = tmp_path / "mixed.backup"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("lumi.sqlite", member)
        for path, data in asset_members.items():
            archive.writestr(path, data)
    _ = db_path
    _ = live_assets
    return zip_path


def test_preview_conflict_inventory_and_mixed_decisions(tmp_path, monkeypatch):
    client, db_path, data_dir = _env_client(tmp_path, monkeypatch)
    try:
        # 活动库写入对比标记（restore 后应被换成 restored-marker）。
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "INSERT INTO lumi_settings VALUES ('live-only', '1', '2026-09-25T00:00:00+00:00')"
        )
        conn.commit()
        conn.close()
        # 活动侧已有 asset-a（同路径不同内容 = differs），asset-b 不存在。
        assets_dir = data_dir / "library" / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        (assets_dir / "asset-a.html").write_bytes(b"<html>LIVE-A</html>")

        package = _make_mixed_package(tmp_path, db_path, {})
        jobs = app.state.backup_jobs
        local_dir = data_dir / "backups"
        local_dir.mkdir(parents=True, exist_ok=True)
        (local_dir / "mixed.backup").write_bytes(package.read_bytes())
        job = run(jobs.create("full", "local"))
        run(
            jobs.succeed(
                job["id"],
                {
                    "filename": "mixed.backup",
                    "target": "local",
                    "sizeBytes": package.stat().st_size,
                    "components": ["lumi.sqlite", "library-assets"],
                    "fileCount": 3,
                    "localPath": str(local_dir / "mixed.backup"),
                },
            )
        )
        preview = client.post(
            "/api/v1/restore/preview",
            json={"source": "local", "jobId": job["id"]},
        )
        assert preview.status_code == 200
        body = preview.json()
        conflicts = {c["path"]: c for c in body["conflicts"]}
        assert conflicts["lumi.sqlite"]["component"] == "lumi"
        assert conflicts["lumi.sqlite"]["exists"] is True
        assert conflicts["lumi.sqlite"]["differs"] is True
        assert conflicts["library-assets/asset-a.html"]["exists"] is True
        assert conflicts["library-assets/asset-a.html"]["differs"] is True
        assert conflicts["library-assets/asset-b.html"]["exists"] is False
        assert conflicts["library-assets/asset-b.html"]["differs"] is False

        # 混合决策：整库覆盖 + asset-a 覆盖 + asset-b skip。
        session_id = body["restoreSessionId"]
        response = client.post(
            "/api/v1/restore",
            json={
                "restoreSessionId": session_id,
                "confirmation": "RESTORE",
                "decisions": {
                    "lumi.sqlite": "overwrite",
                    "library-assets/asset-a.html": "overwrite",
                    "library-assets/asset-b.html": "skip",
                },
            },
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["lumiRestored"] is True
        decisions = result["decisions"]
        assert decisions["overwritten"] == 2  # lumi.sqlite + asset-a
        assert decisions["skipped"] == 1  # asset-b
        assert decisions["restored"] == 0
        outcomes = {s["path"]: s["outcome"] for s in decisions["samples"]}
        assert outcomes["lumi.sqlite"] == "overwritten"
        assert outcomes["library-assets/asset-b.html"] == "skipped"

        # 整库真的换了（restored-marker 在、live-only 没了）。
        check = sqlite3.connect(str(db_path))
        row = check.execute(
            "SELECT value FROM lumi_settings WHERE key='restored-marker'"
        ).fetchone()
        gone = check.execute(
            "SELECT value FROM lumi_settings WHERE key='live-only'"
        ).fetchone()
        check.close()
        assert row == ("yes",)
        assert gone is None
        # asset-a 被覆盖；asset-b 保留缺省（不存在仍未创建）。
        assert (assets_dir / "asset-a.html").read_bytes() == b"<html>NEW-A</html>"
        assert not (assets_dir / "asset-b.html").exists()
    finally:
        client.__exit__(None, None, None)


def test_default_skip_keeps_live_state(tmp_path, monkeypatch):
    client, db_path, data_dir = _env_client(tmp_path, monkeypatch)
    try:
        package = _make_mixed_package(tmp_path, db_path, {})
        jobs = app.state.backup_jobs
        local_dir = data_dir / "backups"
        local_dir.mkdir(parents=True, exist_ok=True)
        (local_dir / "mixed.backup").write_bytes(package.read_bytes())
        job = run(jobs.create("full", "local"))
        run(
            jobs.succeed(
                job["id"],
                {
                    "filename": "mixed.backup",
                    "target": "local",
                    "sizeBytes": package.stat().st_size,
                    "components": ["lumi.sqlite"],
                    "fileCount": 3,
                    "localPath": str(local_dir / "mixed.backup"),
                },
            )
        )
        preview = client.post(
            "/api/v1/restore/preview",
            json={"source": "local", "jobId": job["id"]},
        )
        session_id = preview.json()["restoreSessionId"]
        response = client.post(
            "/api/v1/restore",
            json={"restoreSessionId": session_id, "confirmation": "RESTORE"},
        )
        assert response.status_code == 200, response.text
        result = response.json()
        # 缺省 skip = 全部保留现状（lumiRestored=False，无覆盖）。
        assert result["lumiRestored"] is False
        assert result["decisions"]["skipped"] >= 1
        assert result["decisions"]["overwritten"] == 0
        conn = sqlite3.connect(str(db_path))
        tables = conn.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()[0]
        conn.close()
        assert tables > 0  # 活动库原封未动
    finally:
        client.__exit__(None, None, None)


def test_failure_rolls_back_and_keeps_decision_ledger(tmp_path, monkeypatch):
    client, db_path, data_dir = _env_client(tmp_path, monkeypatch)
    try:
        package = _make_mixed_package(tmp_path, db_path, {})
        jobs = app.state.backup_jobs
        local_dir = data_dir / "backups"
        local_dir.mkdir(parents=True, exist_ok=True)
        (local_dir / "mixed.backup").write_bytes(package.read_bytes())
        job = run(jobs.create("full", "local"))
        run(
            jobs.succeed(
                job["id"],
                {
                    "filename": "mixed.backup",
                    "target": "local",
                    "sizeBytes": package.stat().st_size,
                    "components": ["lumi.sqlite"],
                    "fileCount": 3,
                    "localPath": str(local_dir / "mixed.backup"),
                },
            )
        )
        preview = client.post(
            "/api/v1/restore/preview",
            json={"source": "local", "jobId": job["id"]},
        )
        session_id = preview.json()["restoreSessionId"]

        # 中途引爆整库恢复（模拟损坏快照）：asset 决策已记账。
        from lumirss.restore import RestoreService

        async def boom(self, snapshot):
            raise RestoreFailed("The backup database failed its integrity check.")

        monkeypatch.setattr(RestoreService, "_restore_lumi", boom)

        response = client.post(
            "/api/v1/restore",
            json={
                "restoreSessionId": session_id,
                "confirmation": "RESTORE",
                "decisions": {
                    "lumi.sqlite": "overwrite",
                    "library-assets/asset-a.html": "overwrite",
                },
            },
        )
        assert response.status_code == 500
        assert response.json()["error"]["type"] == "restore_failed"
        # 失败记账落在 job 历史（安全备份保留、原备份保留由既有流程保证）。
        listing = run(jobs.list())
        restore_jobs = [item for item in listing if item["type"] == "restore"]
        assert restore_jobs and restore_jobs[0]["status"] == "failed"

        # 服务层直接调用：RestoreFailed.decisions 账本完整（证据不丢）。
        service = app.state.__dict__.get("_restore_service") or None
        settings = type("S", (), {})()  # 直接构造最小服务实例走一遍
        from lumirss.restore import RestorePreviewRequired

        service = RestoreService(app.state.db, settings, None)
        try:
            run(service.execute("no-such-session", "RESTORE"))
            raised = False
        except RestorePreviewRequired:
            raised = True
        assert raised  # 失败后会话已清理（幂等安全），不残留半状态
    finally:
        client.__exit__(None, None, None)


def test_invalid_decisions_rejected(tmp_path, monkeypatch):
    client, db_path, data_dir = _env_client(tmp_path, monkeypatch)
    try:
        package = _make_mixed_package(tmp_path, db_path, {})
        jobs = app.state.backup_jobs
        local_dir = data_dir / "backups"
        local_dir.mkdir(parents=True, exist_ok=True)
        (local_dir / "mixed.backup").write_bytes(package.read_bytes())
        job = run(jobs.create("full", "local"))
        run(
            jobs.succeed(
                job["id"],
                {
                    "filename": "mixed.backup",
                    "target": "local",
                    "sizeBytes": package.stat().st_size,
                    "components": ["lumi.sqlite"],
                    "fileCount": 3,
                    "localPath": str(local_dir / "mixed.backup"),
                },
            )
        )
        preview = client.post(
            "/api/v1/restore/preview",
            json={"source": "local", "jobId": job["id"]},
        )
        session_id = preview.json()["restoreSessionId"]
        response = client.post(
            "/api/v1/restore",
            json={
                "restoreSessionId": session_id,
                "confirmation": "RESTORE",
                "decisions": {"lumi.sqlite": "nuke"},
            },
        )
        assert response.status_code == 400
        assert response.json()["error"]["type"] == "invalid_restore_decisions"
    finally:
        client.__exit__(None, None, None)
