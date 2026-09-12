"""Gate 4 obsidian regressions (P0-09).

Duplicate-content identities, unambiguous rename adoption, explicit
truncation, indexed-snapshot consistency, env-pinned vault root, and
honest 404 for missing notes.
"""

import asyncio

import pytest

from lumirss.obsidian import ObsidianService, VaultRootLocked
from lumirss.storage import Database

NOTE = "---\ntitle: 笔记A\n---\n正文内容 [[target]]。"


@pytest.fixture()
def db(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")

    async def _migrate():
        await db.migrate()

    asyncio.run(_migrate())
    return db


def _service(db: Database) -> ObsidianService:
    return ObsidianService(db)


def _seed_vault(tmp_path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        target = tmp_path / "vault" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def _scan(service: ObsidianService, vault) -> dict:
    async def _run_scan():
        await service.set_vault_path(str(vault))
        return await service.rescan()

    return asyncio.run(_run_scan())


def test_duplicate_content_is_two_notes_not_a_rename(db, tmp_path):
    service = _service(db)
    vault = tmp_path / "vault"
    _seed_vault(tmp_path, {"a.md": NOTE})
    report = _scan(service, vault)
    assert report["added"] == 1
    # A second file with IDENTICAL content must become a second identity,
    # never steal the first one's uuid (P0-09g).
    _seed_vault(tmp_path, {"b.md": NOTE})
    report = _scan(service, vault)
    assert report["added"] == 1
    assert report["removed"] == 0
    rows = asyncio.run(
        db.fetch_all("SELECT item_uuid, rel_path FROM obsidian_notes")
    )
    assert len(rows) == 2
    assert {str(r["rel_path"]) for r in rows} == {"a.md", "b.md"}


def test_rename_single_file_adopts_uuid(db, tmp_path):
    service = _service(db)
    vault = tmp_path / "vault"
    _seed_vault(tmp_path, {"old/笔记.md": NOTE})
    _scan(service, vault)
    (vault / "old").rename(vault / "renamed")
    report = _scan(service, vault)
    assert report["renames"] == 1
    rows = asyncio.run(
        db.fetch_all("SELECT item_uuid, rel_path FROM obsidian_notes")
    )
    assert len(rows) == 1
    assert str(rows[0]["rel_path"]).startswith("renamed")


def test_ambiguous_content_change_is_delete_plus_create(db, tmp_path):
    service = _service(db)
    vault = tmp_path / "vault"
    _seed_vault(tmp_path, {"keep.md": "---\ntitle: k\n---\nunique-内容"})
    _scan(service, vault)
    # Remove keep.md and create TWO files with its exact old content:
    # ownership is ambiguous, so no rename may be adopted.
    (vault / "keep.md").unlink()
    _seed_vault(
        tmp_path,
        {
            "x1.md": "---\ntitle: k\n---\nunique-内容",
            "x2.md": "---\ntitle: k\n---\nunique-内容",
        },
    )
    report = _scan(service, vault)
    assert report["renames"] == 0
    assert report["added"] == 2
    assert report["removed"] == 1


def test_truncation_is_explicit(db, tmp_path):
    service = _service(db)
    big_body = "词" * 25000
    vault = tmp_path / "vault"
    _seed_vault(tmp_path, {"big.md": f"---\ntitle: big\n---\n{big_body}"})
    _seed_vault(tmp_path, {"small.md": "---\ntitle: s\n---\n短文"})
    report = _scan(service, vault)
    assert report["truncatedNotes"] == 1
    rows = asyncio.run(
        db.fetch_all("SELECT rel_path, truncated FROM obsidian_notes")
    )
    flags = {str(r["rel_path"]): int(r["truncated"]) for r in rows}
    assert flags["big.md"] == 1
    assert flags["small.md"] == 0


def test_note_view_is_indexed_snapshot_not_live_file(db, tmp_path):
    service = _service(db)
    vault = tmp_path / "vault"
    _seed_vault(tmp_path, {"n.md": NOTE})
    _scan(service, vault)
    # Mutate the live file: the projection view stays self-consistent
    # (body/tags/html from one indexed snapshot) until the next scan.
    _seed_vault(tmp_path, {"n.md": "---\ntitle: 改了\n---\n全新的正文"})
    row = asyncio.run(
        db.fetch_one("SELECT item_uuid FROM obsidian_notes")
    )
    view = asyncio.run(service.get_note(str(row["item_uuid"])))
    assert view is not None
    assert view["title"] == "笔记A"
    assert "正文内容" in view["bodyText"]
    # And the next scan picks the change up.
    _scan(service, vault)
    view = asyncio.run(service.get_note(str(row["item_uuid"])))
    assert view["title"] == "改了"


def test_get_note_survives_vault_unmount(db, tmp_path):
    service = _service(db)
    vault = tmp_path / "vault"
    _seed_vault(tmp_path, {"n.md": NOTE})
    _scan(service, vault)
    import shutil

    shutil.rmtree(vault)
    row = asyncio.run(db.fetch_one("SELECT item_uuid FROM obsidian_notes"))
    view = asyncio.run(service.get_note(str(row["item_uuid"])))
    assert view is not None
    assert view["contentHtml"]


def test_env_root_locks_configuration(db):
    service = ObsidianService(db, env_root="/vault")
    assert asyncio.run(service.get_vault_path()) == "/vault"
    with pytest.raises(VaultRootLocked):
        asyncio.run(service.set_vault_path("/somewhere/else"))


def test_scan_if_configured_is_noop_without_vault(db):
    service = _service(db)
    assert asyncio.run(service.scan_if_configured()) is None


def test_missing_note_is_404_not_503(client):
    resp = client.get(
        "/api/v1/obsidian/notes/00000000-0000-4000-8000-000000000009"
    )
    assert resp.status_code == 404
    assert resp.json()["error"]["type"] == "note_not_found"


def test_env_root_flows_from_settings(monkeypatch):
    monkeypatch.setenv("LUMIRSS_OBSIDIAN_VAULT_DIR", "/vault")
    from lumirss.config import LumiSettings

    settings = LumiSettings()
    assert settings.LUMIRSS_OBSIDIAN_VAULT_DIR == "/vault"
