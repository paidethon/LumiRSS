"""FIX-386 守卫 — BFF 测试禁止固定共享 /tmp 数据库/密钥路径。

多个 worktree（主仓 + 各 r2 worktree）并行开发、并行跑 pytest 时，
任何固定共享路径都会成为跨批次共享状态：一个 worktree 的运行能改变
另一个 worktree 的测试结果（红先行证据：向共享路径写入异物即可翻转
test_new341_list_events_pure_shape 的结果）。隔离纪律由 conftest 保证
（autouse _hermetic_db_path + client 夹具均为 per-test 临时目录），
需要自建库/密钥文件的测试必须使用 pytest 的 tmp_path。本守卫静态
扫描 tests/，防止固定共享路径回潮。
"""

import re
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
GUARD_SELF = Path(__file__).name
# 字符串字面量形如 引号 + /tmp/ + 至少一个非引号字符 + 引号 —— 即一个
# 以 /tmp/ 开头的具体路径。纯 "/tmp/" 前缀常量（如敏感串断言列表里的
# 子串匹配项）不含具体目录名，不在禁区。
FIXED_SHARED_PATH = re.compile(r"[\"']/tmp/[^\"']+[\"']")


def test_fix386_no_fixed_shared_tmp_paths_in_tests():
    offenders: list[str] = []
    for path in sorted(TESTS_DIR.glob("*.py")):
        if path.name == GUARD_SELF:
            continue
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if FIXED_SHARED_PATH.search(line):
                offenders.append(f"{path.name}:{lineno}: {line.strip()}")
    assert not offenders, (
        "tests/ 里出现固定共享 /tmp 路径字面量——多 worktree 并行跑"
        " pytest 时会互相读写同一文件（串数据 / schema 漂移 / SQLite 锁"
        " 冲突）。请改用 pytest 的 tmp_path（隔离纪律见 conftest."
        "_hermetic_db_path 与 client 夹具）:\n" + "\n".join(offenders)
    )
