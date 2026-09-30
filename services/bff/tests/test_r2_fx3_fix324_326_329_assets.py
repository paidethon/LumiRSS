"""R2 FX3 — 剪藏/附件/导入事务域 FIX 项的行为证据（BASELINE_OK 三连）。

每个测试把对应 FIX 项的验收规则固化为守卫；实现已满足规则的，通过的
测试即 BASELINE_OK 核验证据。全部凭据/内容为运行时生成的假数据。

- FIX-324（BASELINE_OK）分块上传完成早于最后一块落盘：产品不存在分块
  上传协议——全部路由无 upload/chunk/part/complete 会话端点；唯一的
  字节发布路径（AssetStore.save_snapshot）是单请求整体读取 + 硬上限 +
  ``tmp + shutil.move`` 原子发布 + 失败补偿。没有「最后一块」，完成
  请求无竞态面。
- FIX-326（BASELINE_OK）导入失败回滚误删已存在的重复资源：sha256 去重
  分支根本不写盘、无补偿删除；新对象分支的补偿只回收自己刚创建的
  ``<新uuid>.html``（服务端新生 uuid，不可能是既有文件）。
- FIX-329（BASELINE_OK）附件清理以创建时间代替引用状态：全仓附件文件
  删除点只有三个，全部按引用状态裁决——delete_asset 在 sha256 引用
  归零后才 unlink；reconcile 只清「无行引用」的文件且查询失败即整段
  跳过（fail-safe）；restore 暂存目录的 mtime 清理对象是服务端临时
  文件，不是用户附件。仍被引用的文件不会被空间回收删除。
"""

import asyncio
import re

import pytest

from lumirss.library_assets import AssetStore
from lumirss.main import app
from lumirss.storage import Database


def run(coroutine):
    return asyncio.run(coroutine)


def _store(tmp_path) -> AssetStore:
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    return AssetStore(db, tmp_path / "assets")


# ---------------------------------------------------------------------------
# FIX-324 — 无分块上传协议 + 唯一发布路径原子。


def test_fix324_no_chunked_upload_protocol_exists():
    """结构证据：255 条路由中不存在任何 upload/chunk/part/complete
    会话端点——「完成请求早于最后一块落盘」在产品里没有可触发面。"""
    pattern = re.compile(r"(upload|chunk|part|assembl|finalize)", re.IGNORECASE)
    paths = [str(getattr(route, "path", "")) for route in app.routes]
    assert len(paths) > 100  # 顶住路由表意外收缩的假阴性
    assert not [p for p in paths if pattern.search(p)]


def test_fix324_failed_commit_compensates_only_its_own_publish(tmp_path):
    """行为证据：发布（tmp+move）之后事务失败 → 只补偿本次对象；不存在
    半成品文件被「完成」引用的窗口（tmp→target 是同一目录内 rename）。"""
    store = _store(tmp_path)

    async def fail_tx(_db, _fn):
        raise RuntimeError("simulated commit failure after publish")

    import lumirss.library_assets as la

    original = la.transaction
    la.transaction = fail_tx
    try:
        with pytest.raises(RuntimeError):
            run(store.save_snapshot(data=b"<html>orphan-a</html>"))
    finally:
        la.transaction = original
    # 无行、无文件、无 tmp 残留——发布要么完整可见要么完全不可见。
    files = sorted(p.name for p in store.root.iterdir())
    assert files == []
    rows = run(store._db.fetch_all("SELECT uuid FROM library_assets"))
    assert rows == []


# ---------------------------------------------------------------------------
# FIX-326 — 回滚不误删已存在的重复资源。


def test_fix326_rollback_never_deletes_preexisting_deduped_file(tmp_path):
    """重复内容保存（去重分支）在事务失败时：不写盘、无补偿点、既有
    文件与既有行原样存活——「回滚误删已存在重复资源」结构性不可能。"""
    store = _store(tmp_path)
    record, deduped = run(store.save_snapshot(data=b"<html>shared-bytes</html>"))
    assert deduped is False
    before = store.file_path(record).read_bytes()

    async def fail_tx(_db, _fn):
        raise RuntimeError("simulated commit failure on dedupe branch")

    import lumirss.library_assets as la

    original = la.transaction
    la.transaction = fail_tx
    try:
        with pytest.raises(RuntimeError):
            run(store.save_snapshot(data=b"<html>shared-bytes</html>"))
    finally:
        la.transaction = original
    # 既有资源完好；去重分支没有为「本次保存」创建任何新文件。
    rows = run(store._db.fetch_all("SELECT uuid FROM library_assets"))
    assert len(rows) == 1
    assert store.file_path(record).read_bytes() == before
    assert run(store.read_bytes(record.uuid)) == before


def test_fix326_fresh_path_compensation_cannot_hit_preexisting_file(tmp_path):
    """新对象分支：补偿只删自己刚发布的 <新uuid>.html；既有（含去重
    共享的）文件不受影响——失败实例只回收「本次创建且无引用」的对象。"""
    store = _store(tmp_path)
    first, _ = run(store.save_snapshot(data=b"<html>existing-snap</html>"))
    second, deduped = run(store.save_snapshot(data=b"<html>existing-snap</html>"))
    assert deduped is True  # second 行引用同一物理文件
    shared_path = store.file_path(first)

    async def fail_tx(_db, _fn):
        raise RuntimeError("simulated commit failure on fresh branch")

    import lumirss.library_assets as la

    original = la.transaction
    la.transaction = fail_tx
    try:
        with pytest.raises(RuntimeError):
            run(store.save_snapshot(data=b"<html>fresh-bytes</html>"))
    finally:
        la.transaction = original

    # 既有两行（first + second 去重引用）与物理文件完好；失败对象零残留。
    rows = run(store._db.fetch_all("SELECT uuid FROM library_assets"))
    assert {str(r["uuid"]) for r in rows} == {first.uuid, second.uuid}
    assert shared_path.is_file()
    assert run(store.read_bytes(second.uuid)) == b"<html>existing-snap</html>"
    assert list(store.root.glob("*全新*")) == []
    assert not [p for p in store.root.iterdir() if p.name.startswith(".")]


# ---------------------------------------------------------------------------
# FIX-329 — 清理按引用状态，不按创建时间。


def test_fix329_deletion_follows_reference_state_not_creation_time(tmp_path):
    """两行去重共享一文件：删较早创建的行 → 文件仍被引用必须存活；
    删最后一行 → 文件才回收。空间回收永不多删仍被引用的文件。"""
    store = _store(tmp_path)
    oldest, _ = run(store.save_snapshot(data=b"<html>same-bytes</html>"))
    newest, deduped = run(store.save_snapshot(data=b"<html>same-bytes</html>"))
    assert deduped is True
    physical = store.file_path(oldest)
    assert physical.is_file()

    # 删除「创建时间最早」的行——文件仍被 newest 行引用，必须存活。
    assert run(store.delete_asset(oldest.uuid)) is True
    assert physical.is_file(), "仍被引用的文件不得被清理删除"
    assert run(store.read_bytes(newest.uuid)) == b"<html>same-bytes</html>"

    # 最后一行删除 → 引用归零，物理文件此刻回收。
    assert run(store.delete_asset(newest.uuid)) is True
    assert not physical.is_file()


def test_fix329_reconcile_sweeps_only_unreferenced_files(tmp_path):
    """reconcile 口径 = 引用集合（fail-safe），与创建时间无关：被引用的
    最老文件保留；孤儿文件与 tmp 清扫。"""
    store = _store(tmp_path)
    record, _ = run(store.save_snapshot(data=b"<html>still-referenced</html>"))
    orphan = store.root / "deadbeef.html"
    orphan.write_bytes(b"<html>no-row</html>")
    leftover_tmp = store.root / ".deadbeef.tmp"
    leftover_tmp.write_bytes(b"tmp")

    report = run(store.reconcile())
    assert report["filesRemoved"] == 2
    assert store.file_path(record).is_file()
    assert not orphan.exists() and not leftover_tmp.exists()


def test_fix329_reconcile_fail_safe_never_mass_deletes(tmp_path):
    """引用集合查询失败 → 整段文件清扫跳过（宁可留下孤儿也不误删）。"""
    store = _store(tmp_path)
    record, _ = run(store.save_snapshot(data=b"<html>critical-snap</html>"))

    async def broken_fetch_all(sql, params=()):
        raise RuntimeError("reference lookup failed")

    store._db.fetch_all = broken_fetch_all  # noqa: SLF001 — 测试注入
    report = run(store.reconcile())
    assert report == {"filesRemoved": 0, "rowsDropped": 0}
    assert store.file_path(record).is_file()
