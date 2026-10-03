#!/usr/bin/env python3
"""O190 版本单一源漂移检查。

仓库根的 ``VERSION`` 文件是产品版本唯一权威源（SemVer 2.0.0）。
本脚本确定性校验各组件派生值一致：

- services/bff/pyproject.toml ``version``
- services/bff/src/lumirss/config.py ``LUMIRSS_VERSION``
- apps/web/package.json ``version``
- docker-compose.prod.yml 镜像默认 tag（FIX-184：正式安装钉发布版本，
  绝不默认可变 latest）
- docker-compose.allinone.yml 单容器栈镜像默认 tag（同规则）

任何不一致 → 非零退出。CI 与 ``pnpm api:check`` 同类门禁；升级版本时
只改 VERSION 与各处（脚本保证不漂移）。
"""

from __future__ import annotations

import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_CONFIG = ROOT / "services/bff/src/lumirss/config.py"


def read_version_file() -> str:
    raw = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if not _SEMVER.match(raw):
        print(f"FAIL VERSION '{raw}' is not strict SemVer (MAJOR.MINOR.PATCH)")
        raise SystemExit(1)
    return raw


def main() -> int:
    expected = read_version_file()
    failures: list[str] = []

    pyproject = tomllib.loads((ROOT / "services/bff/pyproject.toml").read_text("utf-8"))
    bff_pkg = pyproject.get("project", {}).get("version")
    if bff_pkg != expected:
        failures.append(f"services/bff/pyproject.toml version={bff_pkg!r} != {expected!r}")

    config = _CONFIG.read_text(encoding="utf-8")
    match = re.search(r'LUMIRSS_VERSION: str = "([^"]+)"', config)
    if match is None:
        failures.append("config.py LUMIRSS_VERSION not found")
    elif match.group(1) != expected:
        failures.append(f"config.py LUMIRSS_VERSION={match.group(1)!r} != {expected!r}")

    web = json.loads((ROOT / "apps/web/package.json").read_text("utf-8"))
    if web.get("version") != expected:
        failures.append(f"apps/web/package.json version={web.get('version')!r} != {expected!r}")

    # FIX-184: the production compose image default must equal VERSION —
    # a plain install pins the released immutable tag, never mutable
    # `latest` (image tag consistency is part of the O190 single source).
    compose = (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    defaults = re.findall(
        r"lumirss-(?:web|bff):\$\{LUMIRSS_IMAGE_TAG:-([^}]+)\}", compose
    )
    if sorted(defaults) != [expected, expected]:
        failures.append(
            "docker-compose.prod.yml image defaults "
            f"{defaults!r} != ['{expected}', '{expected}'] "
            "(both services must default to the VERSION release tag, never 'latest')"
        )

    # All-in-one single-container stack follows the same rule: its only
    # service must default to the VERSION release tag.
    aio_compose = (ROOT / "docker-compose.allinone.yml").read_text(encoding="utf-8")
    aio_defaults = re.findall(
        r"lumirss-allinone:\$\{LUMIRSS_IMAGE_TAG:-([^}]+)\}", aio_compose
    )
    if aio_defaults != [expected]:
        failures.append(
            "docker-compose.allinone.yml image default "
            f"{aio_defaults!r} != ['{expected}'] "
            "(the single-container stack must default to the VERSION release "
            "tag, never 'latest')"
        )

    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        return 1
    print(
        f"version ok: {expected} (VERSION, bff pyproject, bff config, "
        "web package.json, prod + allinone compose image defaults)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
