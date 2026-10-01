#!/usr/bin/env python3
"""FIX-188 min_compat 解析 — 发布清单的最低可升级版本。

发布流水线（publish-images.yml）在每个 manifest 里声明 ``min_compat``：
低于它的旧版本不在升级支持范围内（upgrade-preview 原样透传给
GET /admin/upgrade-preview，运营者升级前可判定兼容性）。口径：最近一个
**早于当前版本**的发布 tag —— 声明"从上一个发布升上来"是受支持的路径；
没有任何更早的发布（首次发布）→ 输出 null，绝不编造。

输入（全部显式参数，确定性、仅标准库、可离线测试）：
  --current 2.8.0
  --tag v2.7.0 --tag v2.8.0 --tag v2.0.0 ...   （仓库全部 tag，可重复）

输出：min_compat 的裸 SemVer（无 v 前缀）或字符串 ``null``（供 workflow
原样嵌入 JSON）。非法输入 → 非零退出，绝不静默给值。
"""

from __future__ import annotations

import argparse
import re
import sys

_SEMVER = re.compile(r"^v?(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def parse_version(raw: str) -> tuple[int, int, int] | None:
    if not _SEMVER.match(raw.strip()):
        return None
    parts = raw.strip().lstrip("v").split(".")
    return tuple(int(p) for p in parts)  # type: ignore[return-value]


def resolve_min_compat(current: str, tags: list[str]) -> str | None:
    """最近一个 < current 的 SemVer tag；没有 → None。非 SemVer tag 忽略。"""
    current_v = parse_version(current)
    if current_v is None:
        raise ValueError(f"current version {current!r} is not SemVer")
    candidates: list[tuple[tuple[int, int, int], str]] = []
    for tag in tags:
        parsed = parse_version(tag)
        if parsed is None or parsed >= current_v:
            continue
        candidates.append((parsed, tag))
    if not candidates:
        return None
    best = max(candidates)[1]
    return best.lstrip("v")


def main() -> int:
    parser = argparse.ArgumentParser(description="Resolve manifest min_compat (FIX-188)")
    parser.add_argument("--current", required=True, help="the release being built (VERSION)")
    parser.add_argument(
        "--tag", action="append", default=[],
        help="a repository tag; repeat for every tag (v-prefix optional)",
    )
    args = parser.parse_args()
    try:
        value = resolve_min_compat(args.current, args.tag)
    except ValueError as exc:
        # 诊断走 stderr：workflow 把 stdout 原样嵌入 manifest JSON，
        # 诊断混入 stdout 会产生非法 JSON（2026-10-01 main 路径实测）。
        print(f"FAIL {exc}", file=sys.stderr)
        return 1
    # JSON-literal output: the workflow embeds it verbatim.
    print("null" if value is None else f'"{value}"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
