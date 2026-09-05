"""0020 Gate 1 regression: BackupEngine → archive → RestoreService roundtrip.

The single most important new test in 0020. It proves that a backup Lumi
creates is accepted by Lumi's own restore validation — specifically for a
FreshRSS SQLite database left in WAL mode, where the online-backup snapshot
that is actually archived has a different size than the live main-db file.

Before the AUDIT-001 fix the manifest stored the LIVE file size while the
archive held the SNAPSHOT, so ``_verify_checksums`` rejected Lumi's own backup
with a size/checksum mismatch. All work happens under tmp_path; no real data.
"""

import asyncio
import json
import sqlite3
import zipfile
from pathlib import Path

from lumirss.backup import BackupEngine, BackupJobStore, WebDavSettingsStore
from lumirss.config import LumiSettings
from lumirss.restore import RestoreService
from lumirss.secrets_store import SecretsStore
from lumirss.storage import Database


def run(coroutine):
    return asyncio.run(coroutine)


def _make_wal_freshrss(base: Path):
    """A FreshRSS data dir whose db.sqlite is in WAL mode with uncheckpointed
    data, so the archived snapshot size differs from the live main-db size."""
    freshrss = base / "freshrss"
    (freshrss / "users" / "admin").mkdir(parents=True, exist_ok=True)
    (freshrss / "config.php").write_text("<?php return ['db' => 'sqlite'];\n")
    db_file = freshrss / "users" / "admin" / "db.sqlite"
    conn = sqlite3.connect(str(db_file))
    conn.execute("PRAGMA journal_mode=WAL")
    # Keep committed data in the -wal sidecar (no auto checkpoint) so the main
    # db file stays small while the logical content is large.
    conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.execute("CREATE TABLE feeds (id INTEGER PRIMARY KEY, name TEXT, payload TEXT)")
    for index in range(800):
        conn.execute(
            "INSERT INTO feeds (name, payload) VALUES (?, ?)",
            (f"feed-{index}", "x" * 240),
        )
    conn.commit()
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert str(mode).lower() == "wal"
    # The connection stays OPEN during backup: WAL is not checkpointed, so the
    # live main-db file size differs from the online-backup snapshot size.
    return freshrss, conn, db_file


def _setup(tmp_path, monkeypatch, freshrss: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "lumi.sqlite"
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(db_path))
    monkeypatch.setenv("LUMIRSS_DATA_DIR", str(data_dir))
    monkeypatch.setenv("FRESHRSS_DATA_DIR", str(freshrss))
    db = Database(db_path)
    run(db.migrate())
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


def test_wal_snapshot_size_differs_from_live_file(tmp_path):
    """Guard the fixture itself: the WAL scenario really produces a size delta,
    otherwise the roundtrip test below would not exercise AUDIT-001."""
    freshrss, conn, db_file = _make_wal_freshrss(tmp_path)
    try:
        live_size = db_file.stat().st_size
        snapshot = tmp_path / "snapshot.sqlite"
        from lumirss.backup import _sqlite_backup

        _sqlite_backup(db_file, snapshot, read_only=True)
        snapshot_size = snapshot.stat().st_size
        # A read-only online backup must still capture the committed WAL rows.
        check = sqlite3.connect(str(snapshot))
        count = check.execute("SELECT count(*) FROM feeds").fetchone()[0]
        check.close()
        assert count == 800
        assert snapshot_size != live_size
    finally:
        conn.close()


def test_backup_restore_roundtrip_wal_freshrss(tmp_path, monkeypatch):
    """BackupEngine → archive → RestoreService.preview accepts Lumi's backup."""
    freshrss, conn, _db_file = _make_wal_freshrss(tmp_path)
    try:
        data_dir, db, jobs, engine = _setup(tmp_path, monkeypatch, freshrss)
        result = run(_submit_and_wait(engine, jobs, "local"))
        assert result["status"] == "succeeded", result.get("safe_error")

        summary = json.loads(result["summary"])
        archive_path = Path(summary["localPath"])
        assert archive_path.is_file()

        # AUDIT-001 direct proof: every manifest size equals the archived
        # member's real size (this is exactly what restore validation checks).
        with zipfile.ZipFile(archive_path) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            freshrss_entries = [
                entry
                for entry in manifest["files"]
                if entry["path"].endswith("db.sqlite")
            ]
            assert freshrss_entries, "expected the FreshRSS SQLite in the manifest"
            for entry in manifest["files"]:
                info = archive.getinfo(entry["path"])
                assert info.file_size == entry["size"], (
                    f"manifest size {entry['size']} != archived member size "
                    f"{info.file_size} for {entry['path']}"
                )

        # The roundtrip: Lumi restore validation must ACCEPT the Lumi backup.
        settings = LumiSettings()
        service = RestoreService(Database(settings.LUMIRSS_DB_PATH), settings, None)
        preview = run(service.preview(archive_path))
        assert preview["compatible"] is True
        assert "lumi.sqlite" in preview["components"]
        assert "freshrss-data" in preview["components"]
        assert preview["restoreSessionId"]
    finally:
        conn.close()
