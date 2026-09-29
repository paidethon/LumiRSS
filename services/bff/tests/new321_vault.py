"""Shared NEW-321..330 test helpers — real temp vault fixtures over the
ab_env harness (session auth, owner + members A/B)."""

from pathlib import Path

NOTE_A = """---
title: 注意力机制
status: draft
rating: 4
tags: [ai, 深度学习]
---
# 注意力机制

参见 [[transformer]] 与 [[dup]]，坏链 [[missing-note]]，越界 [[../outside]]。

#随手笔记 正文 attention。
"""

NOTE_B = """---
title: transformer
status: published
---
transformer 架构笔记。
"""

DUP_ONE = "---\ntitle: dup\n---\n重复同名一。\n"
DUP_TWO = "---\ntitle: dup\n---\n重复同名二。\n"


def write_vault(tmp_path: Path, files: dict[str, str], *, root_name: str = "vault") -> Path:
    """Write a real fixture vault; returns the vault root path."""
    vault = tmp_path / root_name
    for rel, content in files.items():
        target = vault / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return vault


def connect_vault(client, headers, vault: Path) -> None:
    """Owner connects the main vault root (PUT settings) and rescans."""
    created = client.put(
        "/api/v1/obsidian/settings",
        json={"vaultPath": str(vault)},
        headers=headers,
    )
    assert created.status_code == 200, created.text
    rescan = client.post("/api/v1/obsidian/rescan", headers=headers)
    assert rescan.status_code == 200, rescan.text


def note_uuids(client, headers) -> dict[str, str]:
    """rel_path → item uuid from the projection listing."""
    listing = client.get("/api/v1/obsidian/notes?limit=200", headers=headers)
    assert listing.status_code == 200, listing.text
    return {
        note["relPath"]: str(note["ref"]).replace("library:", "")
        for note in listing.json()["items"]
    }
