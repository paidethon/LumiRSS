"""N185 备份内容选择预览 — scope 计数 / 默认不变 / 无凭据 / 跨用户隔离。"""

import asyncio
import json
import sqlite3
import zipfile
from pathlib import Path

from lumirss.backup import BackupEngine, BackupJobStore, WebDavSettingsStore
from lumirss.backup_scope import normalize_include, preview_scope_counts
from lumirss.secrets_store import SecretsStore
from lumirss.storage import Database


def run(coroutine):
    return asyncio.run(coroutine)


def _seed_components(db: Database) -> None:
    """每个组件各插几行（workspace 迁移自带 read-later 一行）。"""
    run(db.migrate())
    run(
        db.execute(
            "INSERT INTO workspaces (id, name, position, created_at) VALUES (?, ?, 1, '2026-09-20T00:00:00+00:00')",
            ("ws-1", "研究"),
        )
    )
    run(
        db.execute(
            "INSERT INTO lumi_notes (uuid, title, content_md, content_hash, created_at, updated_at)"
            " VALUES ('note-1', '人工笔记', '内容', 'hash-1', '2026-09-20T00:00:00+00:00', '2026-09-20T00:00:00+00:00')"
        )
    )
    run(
        db.execute(
            "INSERT INTO annotations (id, entry_ref, anchor_json, anchor_hash)"
            " VALUES ('an-1', 'entry/1', '{}', 'ahash-1')"
        )
    )
    run(
        db.execute(
            "INSERT INTO api_sources (uuid, name, endpoint, items_expr, field_map, secret, created_at)"
            " VALUES ('api-1', '源', 'https://example.com', '$', '{}', 'sec-1', '2026-09-20T00:00:00+00:00')"
        )
    )


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


def _setup_engine(tmp_path: Path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "lumi.sqlite"
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(db_path))
    monkeypatch.setenv("LUMIRSS_DATA_DIR", str(data_dir))
    monkeypatch.setenv("FRESHRSS_DATA_DIR", str(_make_freshrss_fixture(tmp_path)))
    db = Database(db_path)
    _seed_components(db)
    jobs = BackupJobStore(db)
    webdav = WebDavSettingsStore(db, SecretsStore(data_dir / "secrets.json"))

    async def no_client():
        return None

    return db, BackupEngine(db, jobs, webdav, no_client), jobs


async def _submit_and_wait(engine, jobs, target="local", include=None):
    job = await engine.submit_full_backup(target, include)
    while True:
        current = await jobs.get(job["id"])
        if current["status"] in ("succeeded", "failed", "interrupted"):
            return current
        await asyncio.sleep(0.01)


def _open_snapshot(archive_path: Path, member: str) -> sqlite3.Connection:
    with zipfile.ZipFile(archive_path) as archive:
        archive.extract(member, archive_path.parent)
    return sqlite3.connect(str(archive_path.parent / member))


def test_n185_engine_scope_excludes_component_rows(tmp_path, monkeypatch):
    """include.notes=False → 快照里 notes 行被清除，其余组件保留。"""
    db, engine, jobs = _setup_engine(tmp_path, monkeypatch)
    include = normalize_include({"notes": False})
    result = run(_submit_and_wait(engine, jobs, include=include))
    assert result["status"] == "succeeded", result["safe_error"]
    summary = json.loads(result["summary"])
    archive_path = Path(summary["localPath"])

    with zipfile.ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    assert manifest["scope"] == include
    connection = _open_snapshot(archive_path, "lumi.sqlite")
    try:
        assert connection.execute("SELECT COUNT(*) FROM lumi_notes").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0] == 2
        assert connection.execute("SELECT COUNT(*) FROM annotations").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM api_sources").fetchone()[0] == 1
    finally:
        connection.close()
    # 运行中的库未被触碰（裁剪只发生在快照副本上）
    live = sqlite3.connect(str(tmp_path / "data" / "lumi.sqlite"))
    try:
        assert live.execute("SELECT COUNT(*) FROM lumi_notes").fetchone()[0] == 1
    finally:
        live.close()


def test_n185_default_backup_unchanged_no_scope_key(tmp_path, monkeypatch):
    """默认（不带 include）→ manifest 无 scope 字段，全部数据照常进入。"""
    db, engine, jobs = _setup_engine(tmp_path, monkeypatch)
    result = run(_submit_and_wait(engine, jobs))
    assert result["status"] == "succeeded", result["safe_error"]
    summary = json.loads(result["summary"])
    archive_path = Path(summary["localPath"])
    with zipfile.ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    assert "scope" not in manifest
    connection = _open_snapshot(archive_path, "lumi.sqlite")
    try:
        assert connection.execute("SELECT COUNT(*) FROM lumi_notes").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0] == 2
    finally:
        connection.close()
    # job summary 也不携带 scope
    assert "scope" not in summary


def test_n185_no_credentials_in_scope_preview_or_archive(tmp_path, monkeypatch):
    """预览 alwaysExcluded 如实列出凭据；归档绝不含 secrets.json。"""
    db, engine, jobs = _setup_engine(tmp_path, monkeypatch)
    result = run(_submit_and_wait(engine, jobs))
    assert result["status"] == "succeeded"
    summary = json.loads(result["summary"])
    archive_path = Path(summary["localPath"])
    with zipfile.ZipFile(archive_path) as archive:
        assert "secrets.json" not in archive.namelist()
        manifest = json.loads(archive.read("manifest.json"))
    assert manifest["secretPolicy"]["excludedSecrets"]
    preview = run(preview_scope_counts(db, normalize_include(None)))
    assert {item["component"] for item in preview} == {
        "workspaces",
        "notes",
        "annotations",
        "sourceConfig",
    }


def test_n185_cross_user_absence(tmp_path, monkeypatch):
    """跨用户隔离：计数只来自当前请求者的库，B 用户的数据对 A 不可见。"""
    root = tmp_path / "users"
    root.mkdir()
    db_a = Database(root / "a" / "lumi.sqlite")
    db_b = Database(root / "b" / "lumi.sqlite")
    run(db_a.migrate())
    run(db_b.migrate())
    run(
        db_b.execute(
            "INSERT INTO workspaces (id, name, position, created_at) VALUES ('b-only', 'B 的私有工作区', 9, '2026-09-20T00:00:00+00:00')"
        )
    )
    preview_a = run(preview_scope_counts(db_a, normalize_include(None)))
    preview_b = run(preview_scope_counts(db_b, normalize_include(None)))
    count_a = next(i for i in preview_a if i["component"] == "workspaces")["count"]
    count_b = next(i for i in preview_b if i["component"] == "workspaces")["count"]
    assert count_a == 1  # 仅迁移种子行
    assert count_b == 2  # 种子行 + B 的私有工作区


def test_n185_preview_scope_endpoint_counts(client):
    """API：preview-scope 返回逐组件计数；排除组件 count=0 且 included=false。"""
    response = client.post(
        "/api/v1/backups/preview-scope",
        json={"include": {"workspaces": True, "notes": False, "annotations": True, "sourceConfig": True}},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    components = {item["component"]: item for item in body["components"]}
    assert components["notes"]["included"] is False
    assert components["notes"]["count"] == 0
    assert components["workspaces"]["included"] is True
    assert components["workspaces"]["count"] >= 1  # 迁移种子 read-later
    assert any("凭据" in text for text in body["alwaysExcluded"])
    assert any("FreshRSS" in text for text in body["alwaysExcluded"])
