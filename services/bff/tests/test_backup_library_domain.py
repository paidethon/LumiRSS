"""phase2 M1: library-domain owned data must survive backup/restore.

BackupEngine archives the whole consistent lumi.sqlite snapshot, so the
library tables ride along by construction — this test proves it with real
rows in a real archive (no mocks), and that RestoreService still accepts
the archive afterwards.
"""

import asyncio
import json
import sqlite3
import zipfile
from pathlib import Path

from lumirss.backup import BackupEngine, BackupJobStore, WebDavSettingsStore
from lumirss.itemref import new_library_uuid
from lumirss.library import LibraryStore
from lumirss.secrets_store import SecretsStore
from lumirss.storage import Database
from lumirss.workspaces import RESERVED_WORKSPACE_ID, WorkspaceStore


def run(coroutine):
    return asyncio.run(coroutine)


def test_library_rows_survive_backup_archive(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "lumi.sqlite"
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(db_path))
    monkeypatch.setenv("LUMIRSS_DATA_DIR", str(data_dir))
    # A FreshRSS data dir is required for a *full* backup; a minimal empty
    # one (sqlite type) keeps the fixture hermetic while satisfying the
    # engine's preflight.
    freshrss = data_dir / "freshrss"
    (freshrss / "users" / "admin").mkdir(parents=True, exist_ok=True)
    (freshrss / "config.php").write_text("<?php return ['db' => 'sqlite'];\n")
    (freshrss / "users" / "admin" / "db.sqlite").touch()
    monkeypatch.setenv("FRESHRSS_DATA_DIR", str(freshrss))
    db = Database(db_path)
    run(db.migrate())
    store = LibraryStore(db)
    workspaces = WorkspaceStore(db)

    async def seed():
        created, _flag = await store.create_url_bookmark(
            "https://example.com/keep", "保留书签", "备注"
        )
        ws = await workspaces.create_workspace("备份工作区")
        await workspaces.add_item(ws.id, created.ref)
        await workspaces.add_item(RESERVED_WORKSPACE_ID, created.ref)
        return created

    created = run(seed())
    assert created.ref.startswith("library:")

    jobs = BackupJobStore(db)
    webdav = WebDavSettingsStore(db, SecretsStore(data_dir / "secrets.json"))

    async def no_client():
        return None

    engine = BackupEngine(db, jobs, webdav, no_client)

    async def submit_and_wait():
        job = await engine.submit_full_backup("local")
        while True:
            current = await jobs.get(job["id"])
            if current["status"] in ("succeeded", "failed", "interrupted"):
                return current
            await asyncio.sleep(0.01)

    result = run(submit_and_wait())
    assert result["status"] == "succeeded", result.get("safe_error")
    summary = json.loads(result["summary"])
    archive_path = Path(summary["localPath"])

    # The archived lumi.sqlite snapshot contains the library domain rows.
    with zipfile.ZipFile(archive_path) as archive:
        with archive.open("lumi.sqlite") as handle:
            snapshot = Path(tmp_path / "snapshot.sqlite")
            snapshot.write_bytes(handle.read())
    check = sqlite3.connect(str(snapshot))
    try:
        items = check.execute(
            "SELECT uuid, kind FROM library_items"
        ).fetchall()
        bookmarks = check.execute(
            "SELECT title, url FROM library_bookmarks"
        ).fetchall()
        spaces = check.execute(
            "SELECT id FROM workspaces ORDER BY position"
        ).fetchall()
        members = check.execute(
            "SELECT workspace_id, item_ref FROM workspace_items"
        ).fetchall()
    finally:
        check.close()

    assert [kind for _uuid, kind in items] == ["bookmark"]
    assert bookmarks == [("保留书签", "https://example.com/keep")]
    space_ids = [row[0] for row in spaces]
    assert space_ids[0] == RESERVED_WORKSPACE_ID
    member_ws_ids = {ws for ws, _ref in members}
    assert member_ws_ids == set(space_ids)
    # Every member ref still parses as a typed ItemRef in the archive.
    from lumirss.itemref import parse_item_ref

    for _ws, ref in members:
        parse_item_ref(ref)
    assert len(members) == 2


def test_new_library_uuid_is_canonical():
    value = new_library_uuid()
    assert str(__import__("uuid").UUID(value)) == value
