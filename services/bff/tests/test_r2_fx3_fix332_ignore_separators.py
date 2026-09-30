"""FIX-332 — 忽略规则在不同 OS 分隔符下失效（真修）。

裁决：真修。``is_ignored`` 此前把模式原样交给 ``fnmatch``：Windows 书写
的忽略规则（``archive\\private``、``archive\\*``）在 Linux 服务端永不
命中——posix 的 fnmatch 把 ``\\`` 当转义符（``\\*`` = 字面星号），而
walk 产出的 rel_path 恒为 posix 正斜杠。修复 = 模式与路径都先归一到
posix 分隔符再匹配；posix 规则行为逐字不变。
"""

import asyncio

import pytest

from lumirss.new325_root_profiles import (
    RootProfileInvalid,
    is_ignored,
    validate_ignore_globs,
    walk_root,
)
from lumirss.obsidian import canonical_vault_root


def test_windows_separator_pattern_matches_posix_rel_path():
    """Windows 反斜杠目录规则命中 posix rel_path（修复前 False）。"""
    assert is_ignored("archive/private/note.md", ["archive\\private"]) is True
    assert is_ignored("archive/sub/n.md", ["archive\\sub"]) is True


def test_windows_separator_glob_matches_posix_rel_path():
    """Windows 反斜杠 glob（``archive\\*``）命中 posix 路径。"""
    assert is_ignored("archive/note.md", ["archive\\*"]) is True
    assert is_ignored("archive/deep/note.md", ["archive\\*"]) is True


def test_backslash_rel_path_defensively_normalized():
    """防御向：带反斜杠的 rel_path 也按 posix 语义与 posix 规则匹配。"""
    assert is_ignored("archive\\private\\note.md", ["archive/private"]) is True


def test_posix_rules_behavior_unchanged():
    """既有 posix 口径逐字保留：文件 glob / 目录前缀 / 精确名。"""
    assert is_ignored("archive/note.md", ["archive/*"]) is True
    assert is_ignored("archive/sub/n.md", ["archive/sub"]) is True
    assert is_ignored("draft.md", ["draft.md"]) is True
    assert is_ignored("notes/idea.md", ["archive/*"]) is False
    assert is_ignored("archive/note.md", ["templates/*"]) is False


def test_windows_dir_rule_prunes_during_walk(tmp_path):
    """walk 语义：反斜杠目录规则在进入目录前整枝剪掉。"""
    root = tmp_path / "root"
    (root / "archive" / "old").mkdir(parents=True)
    (root / "keep").mkdir()
    (root / "archive" / "old" / "x.md").write_text("x", encoding="utf-8")
    (root / "archive" / "y.md").write_text("y", encoding="utf-8")
    (root / "keep" / "ok.md").write_text("ok", encoding="utf-8")
    canonical_vault_root(str(root))
    files, skipped, total = walk_root(root, ["archive\\old"])
    assert {p.name for p in files} == {"ok.md", "y.md"}
    # 整枝剪除：被忽略的是目录本身（archive/old），x.md 从不入列。
    assert total >= 1 and "archive/old" in skipped


def test_validate_ignore_globs_still_rejects_absolute():
    """规则校验口径不变：仍拒绝绝对路径形态，反斜杠相对规则放行。"""
    assert validate_ignore_globs(["archive\\private"]) == ["archive\\private"]
    with pytest.raises(RootProfileInvalid):
        validate_ignore_globs(["/etc"])


def test_scan_applies_windows_rule_end_to_end(tmp_path):
    """端到端：RootProfileStore 扫描把 Windows 书写规则真实应用于 vault。"""

    async def scenario():
        from lumirss.new325_root_profiles import RootProfileStore
        from lumirss.storage import Database

        db = Database(tmp_path / "lumi.sqlite")
        await db.migrate()
        store = RootProfileStore(db)
        vault = tmp_path / "vault"
        (vault / "private").mkdir(parents=True)
        (vault / "private" / "secret.md").write_text(
            "秘密", encoding="utf-8"
        )
        (vault / "public.md").write_text("公开", encoding="utf-8")
        profile = await store.create(
            label="win-rules", root_path=str(vault), ignore_globs=["private\\*"]
        )
        report = await store.scan(profile["id"])
        assert report["added"] == 1  # 只有 public.md
        assert "private/secret.md" in report["skippedPaths"]

    asyncio.run(scenario())
