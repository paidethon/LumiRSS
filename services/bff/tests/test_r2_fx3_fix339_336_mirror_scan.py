"""FIX-339 + FIX-336 — 镜像索引/增量扫描语义。

FIX-339（真修）：增量扫描的指纹是 ``st_mtime_ns:st_size``。同长度修改
落在同一 mtime 粒度内（粗粒度文件系统/回拨 utime）时指纹打平，但扫描
本来就已为每个文件算出 content_hash——指纹打平而摘要变化必须判为真实
修改，否则索引内容静默过期。修复零额外 I/O（摘要已在手）。

FIX-336（BASELINE_OK）：源文件删除后按既有同步策略处理——
- 删除后未重扫的窗口内 get_note 渲染已索引快照（P0-09f 文档化契约：
  读路径不触碰 Vault，Vault 暂时不可达不吞掉已索引内容）；
- sync_preview 如实报告 removed（NEW-323 审批预览 = 同步策略入口）；
- rescan 应用后投影行 + 搜索投影一并删除，get_note 404（不伪造原库
  还存在）。只读红线由 test_r2_fix158_obsidian_readonly 固有覆盖。
"""

import asyncio
import os

from lumirss.new325_root_profiles import RootProfileStore
from lumirss.obsidian import ObsidianService
from lumirss.search_library import LibrarySearchWriter
from lumirss.storage import Database


def run(coroutine):
    return asyncio.run(coroutine)


def _tie_mtime(path, mtime_ns: int) -> None:
    """把文件 mtime_ns 精确回拨到原值（构造「同长度 + 同粒度」指纹打平）。"""
    stat = os.stat(path)
    os.utime(path, ns=(stat.st_atime_ns, mtime_ns))


# ---------------------------------------------------------------------------
# FIX-339 — 指纹打平但内容摘要变化 → 真实修改。


def test_mirror_scan_same_length_same_mtime_edit_is_detected(tmp_path):
    service = ObsidianService(Database(tmp_path / "lumi.sqlite"))
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "a.md"
    note.write_text("版本甲：内容长度一致", encoding="utf-8")
    run(service.set_vault_path(str(vault)))
    run(service.rescan())

    mtime_ns = os.stat(note).st_mtime_ns
    uuid = run(service.list_notes())[0]["ref"].removeprefix("library:")
    before = run(service.get_note(uuid))
    assert "版本甲" in before["bodyText"]

    note.write_text("版本乙：内容长度一致", encoding="utf-8")
    _tie_mtime(note, mtime_ns)
    report = run(service.rescan())
    assert report["changed"] == 1, "指纹打平但 content_hash 变化必须判为修改"
    assert report["unchanged"] == 0

    after = run(service.get_note(uuid))
    assert "版本乙" in after["bodyText"]
    hits = run(LibrarySearchWriter(service._db).search("版本乙"))
    assert hits, "搜索投影同步更新"


def test_root_profile_scan_same_length_same_mtime_edit_is_detected(tmp_path):
    async def scenario():
        db = Database(tmp_path / "root.sqlite")
        await db.migrate()
        store = RootProfileStore(db)
        vault = tmp_path / "root"
        vault.mkdir()
        note = vault / "n.md"
        note.write_text("根档案版本甲内容", encoding="utf-8")
        profile = await store.create(label="fx339", root_path=str(vault))
        await store.scan(profile["id"])

        mtime_ns = os.stat(note).st_mtime_ns
        note.write_text("根档案版本乙内容", encoding="utf-8")
        _tie_mtime(note, mtime_ns)
        report = await store.scan(profile["id"])
        assert report["changed"] == 1, "根档案扫描同样不得漏掉同长度修改"
        assert report["unchanged"] == 0
        rows = await store.notes(profile["id"])
        assert len(rows) == 1

    asyncio.run(scenario())


def test_fingerprint_untouched_still_short_circuits(tmp_path):
    """增量短路照常工作：内容与指纹都没变 → unchanged（修复不把每次
    扫描都变成全量重写）。"""
    service = ObsidianService(Database(tmp_path / "short.sqlite"))
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "a.md"
    note.write_text("稳定内容", encoding="utf-8")
    run(service.set_vault_path(str(vault)))
    run(service.rescan())
    report = run(service.rescan())
    assert report["unchanged"] == 1 and report["changed"] == 0


def test_mtime_only_bump_same_content_refreshes_fingerprint(tmp_path):
    """只有 mtime 变化（touch，内容字节相同）→ changed 但行身份不变
    （既有 hash_only 语义，修复不得改变它）。"""
    service = ObsidianService(Database(tmp_path / "touch.sqlite"))
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "a.md"
    note.write_text("稳定内容", encoding="utf-8")
    run(service.set_vault_path(str(vault)))
    run(service.rescan())
    uuid = run(service.list_notes())[0]["ref"].removeprefix("library:")
    os.utime(note, ns=(1_000_000_000, 1_000_000_000))
    report = run(service.rescan())
    assert report["changed"] == 1
    again = run(service.get_note(uuid))
    assert again is not None and again["ref"] == f"library:{uuid}"


# ---------------------------------------------------------------------------
# FIX-336 — BASELINE_OK：删除走既有同步策略；投影不伪造源仍存在。


def test_fix336_deleted_source_removed_by_rescan_not_faked(tmp_path):
    service = ObsidianService(Database(tmp_path / "fx336.sqlite"))
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "gone.md"
    note.write_text("即将删除的笔记", encoding="utf-8")
    run(service.set_vault_path(str(vault)))
    run(service.rescan())
    uuid = run(service.list_notes())[0]["ref"].removeprefix("library:")

    # 删除后、重扫前：文档化窗口——快照渲染（P0-09f，Vault 暂时不可达
    # 不吞内容）；同步预览如实报告 removed（审批策略入口，零写入）。
    note.unlink()
    still = run(service.get_note(uuid))
    assert still is not None and "即将删除" in still["bodyText"]
    preview = run(service.sync_preview())
    assert preview["removed"] == 1

    # 应用同步策略（rescan）→ 投影行与搜索投影一并删除，404 口径。
    report = run(service.rescan())
    assert report["removed"] == 1
    assert run(service.get_note(uuid)) is None
    assert run(service.note_count()) == 0
    hits = run(LibrarySearchWriter(service._db).search("即将删除"))
    assert hits == []
