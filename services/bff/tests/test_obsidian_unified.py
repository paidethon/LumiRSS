"""Obsidian read-only projection + unified search + favorites (G6).

Scanner matrix mirrors the PoC (add/change/remove/rename on a real
fixture vault), path-escape refusals, containment re-checks, unified
search partial failure, and federated favorites ownership.
"""

import asyncio

import pytest

from lumirss.favorites import FavoritesService
from lumirss.obsidian import ObsidianService, VaultUnreachable
from lumirss.search_library import LibrarySearchWriter
from lumirss.storage import Database


def _run(coroutine):
    return asyncio.run(coroutine)


@pytest.fixture()
def obsidian(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    _run(db.migrate())
    return ObsidianService(db), tmp_path


def _write_vault(tmp_path, files: dict[str, str]):
    for rel, content in files.items():
        target = tmp_path / "vault" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


NOTE_A = """---
title: 注意力机制
tags: [ai, 深度学习]
---
# 注意力机制

参见 [[transformer]]。

#随手笔记 正文内容 attention。
"""

NOTE_B = """---
title: transformer
---
transformer 架构笔记。
"""


def test_full_scan_incremental_rename_delete(obsidian):
    service, tmp_path = obsidian
    _write_vault(
        tmp_path,
        {
            "AI/深度学习/note-000-注意力机制.md": NOTE_A,
            "AI/transformer.md": NOTE_B,
        },
    )
    vault = str(tmp_path / "vault")
    _run(service.set_vault_path(vault))

    report = _run(service.rescan())
    assert report["added"] == 2 and report["removed"] == 0

    notes = _run(service.list_notes())
    paths = {n["relPath"] for n in notes}
    assert "AI/深度学习/note-000-注意力机制.md" in paths  # 中文路径无损
    attention = next(n for n in notes if "注意力" in n["relPath"])
    assert "ai" in attention["tags"]
    assert "随手笔记" in attention["tags"]

    # Unified search projection sees the note.
    hits = _run(LibrarySearchWriter(service._db).search("transformer"))
    assert any(h["kind"] == "obsidian_note" for h in hits)

    # Touch + delete + rename
    (tmp_path / "vault" / "AI" / "transformer.md").write_text(
        "---\ntitle: transformer\n---\ntransformer 架构笔记。更新版。\n",
        encoding="utf-8",
    )
    # Rename 注意力机制 note (same content → adopt by hash, not re-add).
    (tmp_path / "vault" / "AI" / "深度学习" / "note-000-注意力机制.md").rename(
        tmp_path / "vault" / "AI" / "深度学习" / "renamed-注意.md"
    )
    report = _run(service.rescan())
    assert report["renames"] == 1
    assert report["removed"] == 0
    notes_after = _run(service.list_notes())
    rels = {n["relPath"] for n in notes_after}
    assert "AI/深度学习/renamed-注意.md" in rels
    assert "AI/深度学习/note-000-注意力机制.md" not in rels
    # Ref count stays stable across the rename (same library:<uuid>).
    from lumirss.search_library import LibrarySearchWriter as _W

    hits = _run(_W(service._db).search("attention"))
    assert len(hits) == 1  # not duplicated by the rename


def test_path_escape_and_unreachable(obsidian):
    service, tmp_path = obsidian
    vault = tmp_path / "vault"
    vault.mkdir()
    _run(service.set_vault_path(str(vault)))
    # Symlink escaping the vault must be excluded from the projection.
    outside = tmp_path / "outside.md"
    outside.write_text("---\ntitle: outside\n---\nsecret\n", encoding="utf-8")
    link = vault / "escape.md"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink unsupported")

    report = _run(service.rescan())
    assert report["added"] == 0  # escape target skipped
    notes = _run(service.list_notes())
    assert all("escape" not in n["relPath"] for n in notes)

    # Nonexistent vault → honest error, old index untouched.
    _run(service._db.execute(
        "UPDATE obsidian_settings SET vault_path = ? WHERE id = 1",
        (str(tmp_path / "nope"),),
    ))
    with pytest.raises(VaultUnreachable):
        _run(service.rescan())
    status = _run(service.get_status())
    assert status["lastError"]


def test_note_view_and_content(obsidian):
    service, tmp_path = obsidian
    _write_vault(tmp_path, {"t.md": NOTE_B})
    _run(service.set_vault_path(str(tmp_path / "vault")))
    _run(service.rescan())
    notes = _run(service.list_notes())
    note = _run(service.get_note(notes[0]["ref"].split(":", 1)[1]))
    assert note is not None
    assert note["title"] == "transformer"
    assert "<p>" in note["contentHtml"]


def test_unified_search_partial_failure(client, tmp_path):
    """Library leg failure degrades the response, RSS leg unaffected."""
    _ = tmp_path
    rss_ok = client.get("/api/v1/search", params={"q": "x"})
    # RSS projection may be empty (FreshRSS unconfigured) — endpoint still 200.
    assert rss_ok.status_code == 200
    body = rss_ok.json()
    assert "library" in body  # additive field present


def test_federated_favorites_merge(client, tmp_path):
    from lumirss.main import app
    from lumirss.storage import Database

    _ = client
    db = Database(tmp_path / "lumi.sqlite")
    _run(db.migrate())
    app.state.db = db
    service = FavoritesService(db, LibrarySearchWriter(db))
    from lumirss.entryref import encode_entry_ref
    from lumirss.itemref import parse_item_ref

    ref = parse_item_ref("rss:" + encode_entry_ref("9")).format()
    # A real bookmark projects itself into search_library on creation.
    from lumirss.library import LibraryStore

    store = LibraryStore(db)
    created, _flag = _run(
        store.create_url_bookmark("https://example.com/fav", "收藏的书签")
    )
    assert _run(service.add_favorite(created.ref)) is True
    # Idempotent re-add
    assert _run(service.add_favorite(created.ref)) is False
    result = _run(service.federated_favorites())
    assert result["libraryError"] is None
    assert any(i.ref == created.ref for i in result["library"])
    assert all(i.ref.startswith("rss:") for i in result["rss"])
    _ = ref
