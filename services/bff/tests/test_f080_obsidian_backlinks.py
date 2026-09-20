"""F080 Obsidian 反链/断链 — 反链正确、重命名后 rescan 更新、断链列出、
别名解析、标题锚点、路径穿越负向、**vault 只读负向（哈希清单不变）**。"""

import asyncio
import hashlib
from pathlib import Path

import pytest

from lumirss.obsidian import ObsidianService
from lumirss.obsidian_backlinks import (
    backlinks_for,
    broken_links_for,
    parse_wikilink,
    rebuild_backlinks,
)
from lumirss.storage import Database


def run(coroutine):
    return asyncio.run(coroutine)


@pytest.fixture()
def obsidian(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    return ObsidianService(db), tmp_path


def _write_vault(tmp_path, files):
    vault = tmp_path / "vault"
    for rel, content in files.items():
        target = vault / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return vault


def _hash_vault(vault: Path) -> list[str]:
    """vault 文件哈希清单（相对路径 + 内容 sha256，排序后拼接）。"""
    manifest = []
    for file in sorted(vault.rglob("*")):
        if file.is_file():
            digest = hashlib.sha256(file.read_bytes()).hexdigest()
            manifest.append(f"{file.relative_to(vault)}:{digest}")
    return manifest


def test_f080_parse_alias_heading_and_traversal_rejected():
    # 别名解析
    parsed = parse_wikilink("notes/深度学习#训练|深度学习笔记")
    assert parsed.target == "notes/深度学习"
    assert parsed.alias == "深度学习笔记"
    assert parsed.heading == "训练"
    # 标题锚点
    heading_only = parse_wikilink("某笔记#第三章")
    assert heading_only.target == "某笔记"
    assert heading_only.heading == "第三章"
    # 路径穿越/绝对路径逃逸 vault → 拒绝解析（负向）
    assert parse_wikilink("../secrets/keys").escaped_vault is True
    assert parse_wikilink("/etc/passwd").escaped_vault is True
    assert parse_wikilink("C:/Windows/system").escaped_vault is True
    assert parse_wikilink("正常笔记").escaped_vault is False


def test_f080_backlinks_broken_rename_rescan_and_vault_readonly(obsidian, tmp_path):
    service, tmp = obsidian
    vault = _write_vault(
        tmp,
        {
            "notes/alpha.md": "---\ntitle: Alpha\n---\n正文，链接到 [[beta|Beta 笔记#结论]]。",
            "notes/beta.md": "---\ntitle: Beta\n---\n被链接的笔记。",
            "notes/escape.md": "穿越尝试 [[../secrets]] 和 [[/abs]]，外加 [[不存在]]。",
        },
    )
    run(service.set_vault_path(str(vault)))
    # **vault 只读负向：rescan 前后哈希清单不变**
    before = _hash_vault(vault)
    run(service.rescan())
    after = _hash_vault(vault)
    assert before == after

    # 重建反链（rescan 内部亦触发）
    notes = run(service.list_notes())
    _ = notes
    count = run(rebuild_backlinks(app_db(service)))
    assert count > 0

    beta_uuid = _uuid_of(service, "notes/beta.md")
    # 反链正确：alpha → beta，别名透出
    links = run(backlinks_for(app_db(service), beta_uuid))
    assert len(links) == 1
    assert links[0]["alias"] == "Beta 笔记#结论"
    assert links[0]["title"] == "Alpha"

    # 断链列出：穿越（path_escaped_vault）与未解析（unresolved）
    escape_uuid = _uuid_of(service, "notes/escape.md")
    broken = run(broken_links_for(app_db(service), escape_uuid))
    reasons = {b["reason"] for b in broken}
    assert "path_escaped_vault" in reasons
    assert "unresolved" in reasons

    # 重命名后 rescan 更新反链（beta.md → gamma.md；alpha 链接改为断链）
    (vault / "notes").mkdir(exist_ok=True)
    (vault / "notes/beta.md").rename(vault / "notes/gamma.md")
    (vault / "notes/gamma.md").write_text(
        "---\ntitle: Gamma\n---\n改名后的笔记。", encoding="utf-8"
    )
    run(service.rescan())
    run(rebuild_backlinks(app_db(service)))
    beta_links = run(backlinks_for(app_db(service), beta_uuid))
    assert beta_links == []  # 旧目标已不在
    # alpha 的链接 [[beta|...]] 现在指向不存在的 rel_path → 断链
    alpha_uuid = _uuid_of(service, "notes/alpha.md")
    alpha_broken = run(broken_links_for(app_db(service), alpha_uuid))
    assert any(b["raw"].startswith("beta") for b in alpha_broken)


def app_db(service):
    return service._db


def _uuid_of(service, rel_path: str) -> str:
    db = service._db

    async def _get():
        row = await db.fetch_one(
            "SELECT item_uuid FROM obsidian_notes WHERE rel_path = ?", (rel_path,)
        )
        return str(row["item_uuid"]) if row is not None else None

    return run(_get())
