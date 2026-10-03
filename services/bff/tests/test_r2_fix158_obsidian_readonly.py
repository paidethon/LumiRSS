"""FIX-158 — Obsidian 集成只读边界：vault 不可被 BFF 写入/后台修改。

裁决：BASELINE_OK（现有实现已满足边界——本批次为边界加廉价守卫）。
R07 更新：引入服务端受限写入导出（obsidian_export.py）后，边界从
「绝不写」细化为——

- 只读投影面（obsidian*.py 的其余全部模块）依旧一个写调用都不存在；
- 唯一被许可的写面是 obsidian_export.py：只写部署上独立挂载的导出
  根（LUMIRSS_OBSIDIAN_EXPORT_DIR，生产 /vault-export），原子且绝不
  覆盖已存在文件；破坏性全树变更形态（rmtree/rename/os.remove…）
  在该模块内同样被静态禁止。

两层守卫：
1. 静态：只读模块清单不得出现任何 vault 变更调用（write/rename/
   mkdir/unlink/rmtree/shutil/os.remove…）；obsidian_export.py 单独
   禁止破坏性形态——模块清单变化必须显式归类，不允许新模块静默
   绕过任一清单。
2. 行为：对真实临时 vault 连续 rescan（含 rename 采纳路径）后，vault
   文件字节与目录结构逐字节不变——扫描只更新投影库，绝不动原库。
"""

import asyncio
import re
from pathlib import Path

import pytest

from lumirss.obsidian import ObsidianService
from lumirss.storage import Database

_LUMIRSS_DIR = Path(__file__).resolve().parent.parent / "src" / "lumirss"

# R07：服务端受限写入导出——唯一被许可的写面（只写导出根）。
_EXPORT_MODULE = "obsidian_export.py"

# 其余 obsidian*.py 全部是只读投影面：模板/URI/handoff 只生成
# obsidian:// 链接，不落盘；backlinks/devices/handoff-log 只碰投影库。
_READONLY_MODULES = sorted(
    path.name
    for path in _LUMIRSS_DIR.glob("obsidian*.py")
    if path.name != _EXPORT_MODULE
)

# vault 变更调用形态（调用点级匹配，不是子串误报）。
_WRITE_PATTERNS = re.compile(
    r"\.write_text\(|\.write_bytes\(|\.mkdir\(|\.unlink\(|\.rmdir\("
    r"|\.rename\(|\.replace\(.*Path|shutil\.(move|rmtree|copy)"
    r"|os\.(remove|removedirs|rmdir|truncate)\(|\baiofiles\.open\("
    r"|os\.mknod\(",
)

# 写面模块仍被禁止的破坏性形态：导出只允许「新建文件」，绝不删除、
# 改名、移动任何既有文件（用户手写保护）。
_DESTRUCTIVE_PATTERNS = re.compile(
    r"shutil\.|os\.(remove|removedirs|rmdir|truncate)\("
    r"|\.rename\(|\.rmdir\(|\.replace\(.*Path|os\.mknod\(",
)


def test_obsidian_modules_contain_no_vault_mutation_calls():
    # 模块清单必须被显式归类：新 obsidian*.py 出现时，要么进只读清单
    # （默认），要么作为新写面显式加入本测试——不允许静默绕过。
    all_modules = sorted(p.name for p in _LUMIRSS_DIR.glob("obsidian*.py"))
    assert all_modules == sorted([*_READONLY_MODULES, _EXPORT_MODULE]), (
        "出现未归类的 obsidian 模块：请确认其读写边界后更新本测试清单。"
    )
    assert len(_READONLY_MODULES) >= 6, "只读模块清单不应缩水"
    offenders = []
    for name in _READONLY_MODULES:
        source = (_LUMIRSS_DIR / name).read_text(encoding="utf-8")
        for match in _WRITE_PATTERNS.finditer(source):
            line = source.count("\n", 0, match.start()) + 1
            offenders.append(f"{name}:{line}: {match.group(0)}")
    assert offenders == [], (
        "Obsidian 只读投影模块出现 vault 变更调用（只读边界被削弱）：\n"
        + "\n".join(offenders)
    )


def test_export_module_has_no_destructive_vault_forms():
    """R07 写面守卫：导出模块只能新建文件，禁止一切破坏性形态。"""
    source = (_LUMIRSS_DIR / _EXPORT_MODULE).read_text(encoding="utf-8")
    offenders = [
        f"{_EXPORT_MODULE}:{source.count(chr(10), 0, match.start()) + 1}: {match.group(0)}"
        for match in _DESTRUCTIVE_PATTERNS.finditer(source)
    ]
    assert offenders == [], (
        "导出写面出现破坏性调用（新建之外的动作必须不存在）：\n"
        + "\n".join(offenders)
    )


@pytest.fixture()
def db(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")

    async def _migrate():
        await db.migrate()

    asyncio.run(_migrate())
    return db


def _seed_vault(tmp_path, files: dict[str, str]) -> Path:
    vault = tmp_path / "vault"
    for rel, content in files.items():
        target = vault / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return vault


def _scan(service: ObsidianService, vault: Path) -> dict:
    async def _run_scan():
        await service.set_vault_path(str(vault))
        return await service.rescan()

    return asyncio.run(_run_scan())


def test_rescan_and_rename_adoption_leave_vault_bytes_untouched(db, tmp_path):
    vault = _seed_vault(
        tmp_path,
        {
            "a.md": "---\ntitle: 笔记A\n---\n正文A [[b]]。",
            "b.md": "---\ntitle: 笔记B\n---\n正文B。",
        },
    )
    service = ObsidianService(db)

    def snapshot() -> dict[str, bytes]:
        return {
            str(p.relative_to(vault)): p.read_bytes()
            for p in sorted(vault.rglob("*"))
            if p.is_file()
        }

    before = snapshot()
    first = _scan(service, vault)
    assert snapshot() == before, "首次扫描修改了 vault 文件"
    # rename 采纳路径：b.md → c.md（内容不变；这是测试自身的编辑）
    (vault / "b.md").rename(vault / "c.md")
    renamed = snapshot()
    second = _scan(service, vault)

    assert first["added"] == 2
    assert second["renames"] == 1
    # rename 采纳扫描后 vault 字节面与扫描前完全一致——唯一差异在投影库
    # （obsidian_notes），原库零写入。
    assert snapshot() == renamed, "rename 采纳扫描修改了 vault 文件"
