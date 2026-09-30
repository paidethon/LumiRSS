"""FIX-158 — Obsidian 集成只读边界：vault 不可被 BFF 写入/后台修改。

裁决：BASELINE_OK（现有实现已满足边界——本批次为边界加廉价守卫）。

两层守卫：
1. 静态：obsidian* 模块源代码不得出现任何 vault 变更调用
   （write/rename/mkdir/unlink/rmtree/shutil/os.remove…）——模块契约
   （"read-only: no write/rename/mkdir/unlink call exists"）从此有测试
   钉住，后续改动引入写路径会直接红。
2. 行为：对真实临时 vault 连续 rescan（含 rename 采纳路径）后，vault
   文件字节与目录结构逐字节不变——扫描只更新投影库，绝不动原库。
"""

import asyncio
import re
from pathlib import Path

import pytest

from lumirss.obsidian import ObsidianService
from lumirss.storage import Database

# 覆盖全部 Obsidian 集成模块（含 routers 的 obsidian 路由与 web 导出面
# 的服务端部分）；模板/URI/handoff 只生成 obsidian:// 链接，不落盘。
_OBSIDIAN_MODULES = [
    path
    for path in (Path(__file__).resolve().parent.parent / "src" / "lumirss").glob(
        "obsidian*.py"
    )
]

# vault 变更调用形态（调用点级匹配，不是子串误报）。
_WRITE_PATTERNS = re.compile(
    r"\.write_text\(|\.write_bytes\(|\.mkdir\(|\.unlink\(|\.rmdir\("
    r"|\.rename\(|\.replace\(.*Path|shutil\.(move|rmtree|copy)"
    r"|os\.(remove|removedirs|rmdir|truncate)\(|\baiofiles\.open\("
    r"|os\.mknod\(",
)


def test_obsidian_modules_contain_no_vault_mutation_calls():
    assert len(_OBSIDIAN_MODULES) >= 6, "obsidian 模块清单不应缩水"
    offenders = []
    for path in sorted(_OBSIDIAN_MODULES):
        source = path.read_text(encoding="utf-8")
        for match in _WRITE_PATTERNS.finditer(source):
            line = source.count("\n", 0, match.start()) + 1
            offenders.append(f"{path.name}:{line}: {match.group(0)}")
    assert offenders == [], (
        "Obsidian 集成模块出现 vault 变更调用（只读边界被削弱）：\n"
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
