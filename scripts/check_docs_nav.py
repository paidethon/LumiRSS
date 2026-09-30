#!/usr/bin/env python3
"""校验 docs 站点导航（VitePress nav/sidebar）的路由真实存在。

`vitepress build` 的死链门禁只查 Markdown 源内链接，不查 config.ts 里
themeConfig 的 nav/sidebar 路由（实测：坏导航链接照样 build 成功）。
本脚本补上这一缺口：解析 config.ts 的每个 `link: '/...'`，映射回源文件
（`/x/y` → `docs/x/y.md`；`/` 经 rewrite → `docs/README.md`），文件缺失
即失败。`docs/.vitepress/dist/` 存在时（先跑过 `npm run docs:build`）再
核验构建产物 `<path>.html`，覆盖"源在、构建路由变了"的情形。

用法: python3 scripts/check_docs_nav.py [repo 根目录，默认脚本上级]
锚点（/page#section）不在覆盖范围：当前 config 导航全是纯路由。
"""
import re
import sys
from pathlib import Path

_LINK_RE = re.compile(r"link:\s*'([^']+)'")
_REWRITE_TARGET = "README.md"


def main() -> int:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
    config = root / "docs" / ".vitepress" / "config.ts"
    if not config.is_file():
        print(f"FAIL: 找不到 {config}")
        return 1
    links = sorted(set(_LINK_RE.findall(config.read_text(encoding="utf-8"))))
    dist = root / "docs" / ".vitepress" / "dist"
    missing: list[str] = []
    checked = 0
    for link in links:
        if link.startswith(("http://", "https://", "mailto:")):
            continue
        rel = _REWRITE_TARGET if link == "/" else link.strip("/") + ".md"
        source = root / "docs" / rel
        checked += 1
        if not source.is_file():
            missing.append(f"{link} -> docs/{rel}（源文件不存在）")
            continue
        if dist.is_dir():
            built = dist / "index.html" if link == "/" else dist / f"{link.strip('/')}.html"
            if not built.is_file():
                missing.append(f"{link} -> {built.relative_to(root)}（构建产物缺失；先 npm run docs:build）")
    if missing:
        print("DOCS NAV FAIL")
        for m in missing:
            print(" -", m)
        return 1
    extra = f"，含 dist 构建产物核验" if dist.is_dir() else "（仅源文件核验；跑 npm run docs:build 后重跑可覆盖构建路由）"
    print(f"docs nav OK: {checked} 个导航路由全部可达{extra}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
