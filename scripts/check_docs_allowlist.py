#!/usr/bin/env python3
"""Docs v2 防腐化门禁：docs/ 下的长期 Markdown 必须在 SSOT 白名单内。

Docs v2 治理把活跃文档收敛为一组单一事实来源（SSOT）；本脚本阻止
Agent/贡献者无意识地把 `FINAL_REPORT.md`、`IMPLEMENTATION_PLAN.md`、
`RECOVERY_NOTES.md` 这类过程文件再种回 main：

- `docs/**/*.md` 中任何不在白名单的文件 → 失败，并提示优先合并进现有
  SSOT；确有必要的新长期文档，显式扩充下方 ALLOWLIST（一行一文件）。
- `docs/upstream/**` 是 LEGAL 存档（许可审计/来源归档），整目录豁免
  白名单逐条登记，但同样不允许新增叙事文档混入。
- 非文档文件（.json 机读件、.vitepress/、public/ 资产）不在本门禁范围。

用法: python3 scripts/check_docs_allowlist.py [repo 根目录]
"""
import sys
from pathlib import Path

# 活跃 SSOT 全集（docs/ 相对路径）。每个文件有唯一职责，见 docs/development.md。
ALLOWLIST: frozenset[str] = frozenset(
    {
        "index.md",
        "getting-started.md",
        "usage.md",
        "operations.md",
        "configuration.md",
        "architecture.md",
        "design-system.md",
        "development.md",
        "roadmap.md",
        "upstreams.md",
    }
)

# LEGAL 目录（许可/归因存档）：不进站点导航，但文件本身不逐条登记。
LEGAL_DIRS: tuple[str, ...] = ("upstream",)


def main() -> int:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
    docs = root / "docs"
    if not docs.is_dir():
        print(f"FAIL: 找不到 {docs}")
        return 1

    offenders: list[str] = []
    checked = 0
    for md in sorted(docs.rglob("*.md")):
        rel = md.relative_to(docs).as_posix()
        if rel.startswith(".vitepress/"):
            continue  # 站点主题/配置（非内容文档）
        if rel.split("/")[0] in LEGAL_DIRS:
            continue  # LEGAL 存档目录
        checked += 1
        if rel not in ALLOWLIST:
            offenders.append(rel)

    if offenders:
        print("DOCS ALLOWLIST FAIL — 白名单外的 Markdown 文档：")
        for f in offenders:
            print(f" - docs/{f}")
        print(
            "\nCan this information be added to an existing SSOT document?\n"
            "优先把内容合并进现有 SSOT（清单见 docs/development.md「文档治理规则」）；\n"
            "确有必要的新长期文档：把路径加进 scripts/check_docs_allowlist.py 的 ALLOWLIST。"
        )
        return 1

    print(f"docs allowlist OK: {checked} 个活跃文档全部在 SSOT 白名单内")
    return 0


if __name__ == "__main__":
    sys.exit(main())
