"""FIX-360 — 备份锁与升级锁获取顺序相反产生死锁（BASELINE_OK）。

裁决：BASELINE_OK。全系统对「备份 × 升级」只有一把锁：
- lumirss CLI：唯一的 ``.update.lock``（flock(2)，FIX-195）。``cmd_update``
  先取锁再做 pre-update 备份（FIX-201 失败即中止）；``cmd_backup``/
  ``cmd_restore`` 不取任何第二把锁——单锁系统不存在可反转的获取顺序，
  AB-BA 死锁结构性不可能；并发第二个 update 被 ``flock -n`` 立刻清楚
  拒绝（有界，绝不挂等）。
- BFF：BackupEngine 用单个 ``_busy`` 进程内标志串行备份与恢复
  （AD-0018-7），同样没有锁对；并发提交被 BackupBusy 清楚拒绝
  （既有覆盖 tests/test_backup.py）。
- 同族既有处理：FIX-209 备份目录唯一（mkdir 原子撞名退 PID 后缀）+
  LATEST 成功后原子写（tmp + mv）；deploy 域并发写一致性由
  tests/deploy/run-deploy-tests.sh §17/§19 在真实 docker 上覆盖。

本文件把上述口径固化为守卫：脚本结构（单锁 + 顺序 + 201/209 守卫）、
flock -n 的有界拒绝行为、BFF 单标志双门。
"""

import fcntl
import os
from pathlib import Path

import pytest

from lumirss.backup import BackupBusy, BackupEngine

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = (_REPO_ROOT / "lumirss").read_text(encoding="utf-8")


def run(coroutine):
    return asyncio_run(coroutine)


def asyncio_run(coroutine):
    import asyncio

    return asyncio.run(coroutine)


def _function_source(name: str) -> str:
    """提取 ``name() { ... }`` 的函数体（bash 顶层函数，无嵌套同名）。"""
    start = _SCRIPT.index(f"{name}() {{")
    body_start = _SCRIPT.index("{", start)
    depth = 0
    for index in range(body_start, len(_SCRIPT)):
        if _SCRIPT[index] == "{":
            depth += 1
        elif _SCRIPT[index] == "}":
            depth -= 1
            if depth == 0:
                return _SCRIPT[start : index + 1]
    raise AssertionError(f"function {name} not closed")  # pragma: no cover


def test_single_lock_architecture_no_order_to_invert():
    """结构证据：全脚本只有一把锁（.update.lock / 一次 flock 调用）；
    cmd_backup 与 cmd_restore 都不取锁——不存在两把锁，也就不存在
    「获取顺序相反」。"""
    assert _SCRIPT.count("flock -n") == 1, "全系统只允许一把 flock 锁"
    assert _SCRIPT.count('UPDATE_LOCK_FILE="') == 1
    backup_body = _function_source("cmd_backup")
    restore_body = _function_source("cmd_restore")
    for name, body in (("cmd_backup", backup_body), ("cmd_restore", restore_body)):
        assert "acquire_update_lock" not in body, f"{name} 不得嵌套取升级锁"
        assert "flock" not in body, f"{name} 不得引入第二把锁"


def test_update_takes_the_only_lock_before_backup_stage():
    """顺序证据：cmd_update 先 acquire_update_lock（FIX-195），后调
    cmd_backup——唯一锁在全流程中顺序一致，无反向获取方。"""
    update_body = _function_source("cmd_update")
    assert update_body.index("acquire_update_lock") < update_body.index(
        "cmd_backup"
    )
    # FIX-201：备份失败绝不继续升级（先记状态再退出）。
    assert "pre-update backup failed" in update_body
    assert "exit 1" in update_body


def test_fix209_guards_present_in_backup_flow():
    """同族守卫在场：备份目录唯一（mkdir 撞名退 PID 后缀）+ LATEST 整包
    成功后原子写（tmp + mv）——并发备份有界完成、互不覆盖。"""
    backup_body = _function_source("cmd_backup")
    assert 'if ! mkdir "$dir" 2>/dev/null; then' in backup_body
    assert 'dir="$BACKUP_DIR/$stamp-$$"' in backup_body
    assert "$BACKUP_DIR/.LATEST.$$" in backup_body
    assert 'mv -f "$BACKUP_DIR/.LATEST.$$" "$BACKUP_DIR/LATEST"' in backup_body


def test_second_lock_holder_refused_immediately_bounded(tmp_path):
    """行为证据：``flock -n`` 语义 = 第二个持有者立刻被拒（BlockingIOError，
    对应 CLI 的 err + exit 1 清楚拒绝），绝不阻塞挂等；持锁者释放后
    后续运行有界完成。"""
    lock_file = tmp_path / ".update.lock"
    first = os.open(lock_file, os.O_RDWR | os.O_CREAT)
    second = os.open(lock_file, os.O_RDWR | os.O_CREAT)
    try:
        fcntl.flock(first, fcntl.LOCK_EX | fcntl.LOCK_NB)  # 第一个 update 成功
        import time

        started = time.monotonic()
        with pytest.raises(BlockingIOError):
            fcntl.flock(second, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert time.monotonic() - started < 1.0  # 拒绝是有界的，非挂死
        fcntl.flock(first, fcntl.LOCK_UN)  # 第一个运行结束释放
        fcntl.flock(second, fcntl.LOCK_EX | fcntl.LOCK_NB)  # 重试有界完成
        fcntl.flock(second, fcntl.LOCK_UN)
    finally:
        os.close(first)
        os.close(second)


def test_bff_backup_restore_share_one_serialization_gate():
    """BFF 侧：备份与恢复共用同一个 _busy 标志（单门）——并发第二请求
    被清楚拒绝（BackupBusy），不存在第二把可反转的锁。"""
    engine = BackupEngine.__new__(BackupEngine)  # 只测忙门，不需要完整装配
    engine._busy = True
    with pytest.raises(BackupBusy):
        run(engine.submit_full_backup("local"))
    with pytest.raises(BackupBusy):
        run(engine.run_restore(object(), "session", "confirmation"))
