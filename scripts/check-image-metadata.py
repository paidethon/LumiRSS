#!/usr/bin/env python3
"""FIX-373 / FIX-372 发布管线元数据一致性检查。

VERSION 文件是产品版本唯一权威源（O190，scripts/check-version.py 校验
组件派生值）。本脚本钉住版本如何进入镜像与发布门禁，使「构建标签」与
「镜像内版本」不可能各说各话：

- 两个生产 Dockerfile 必须从构建参数注入 OCI labels：
  org.opencontainers.image.version  <- LUMIRSS_VERSION（VERSION 文件）
  org.opencontainers.image.revision <- 测试过的 git SHA（BFF: LUMIRSS_COMMIT,
  Web: VITE_GIT_COMMIT——与运行时 env/前端 bundle 同源）。
- publish-images.yml 与 ci.yml 的构建命令必须显式传入这些参数，
  LUMIRSS_VERSION 一律来自 VERSION 文件，SHA 一律来自同一输出。
- FIX-372：发布门禁必须按 workflow PATH（actions/workflows/ci.yml）查询
  CI 结论——同名不同文件的工作流不可能冒充所需检查；被校验的必须是
  run 的整体 conclusion。workflow_run 触发按名字匹配（GitHub 语义），
  但门禁查询按路径，本脚本钉死这两个属性。
- FIX-376：所有启用了 setup-node 缓存的步骤必须显式 hash 锁文件
  （cache-dependency-path）；setup-uv 默认按 **/uv.lock 计算 key。

任何不一致 → 非零退出。确定性、仅标准库；CI（repository-checks）与
tests/deploy/run-image-metadata-tests.sh 调用。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")

_BFF_DOCKERFILE = ROOT / "services/bff/Dockerfile"
_WEB_DOCKERFILE = ROOT / "apps/web/Dockerfile"
_PUBLISH_WF = ROOT / ".github/workflows/publish-images.yml"
_CI_WF = ROOT / ".github/workflows/ci.yml"
_CI_WF_PATH = ".github/workflows/ci.yml"


def _last_dockerfile_stage(text: str) -> str:
    """The final (shipped) stage — where labels must live."""
    return text.split("\nFROM ")[-1]


def _require(text: str, pattern: str, failures: list[str], what: str) -> None:
    if re.search(pattern, text, flags=re.MULTILINE) is None:
        failures.append(what)


def check_image_metadata() -> list[str]:
    failures: list[str] = []

    version_raw = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    if not _SEMVER.match(version_raw):
        failures.append(f"VERSION '{version_raw}' is not strict SemVer")

    # ---- BFF image: labels from LUMIRSS_VERSION + LUMIRSS_COMMIT ----------
    bff = _BFF_DOCKERFILE.read_text(encoding="utf-8")
    bff_runtime = _last_dockerfile_stage(bff)
    _require(bff_runtime, r'^ARG LUMIRSS_COMMIT="?"?', failures, "bff Dockerfile final stage: ARG LUMIRSS_COMMIT missing")
    _require(bff_runtime, r'^ARG LUMIRSS_VERSION="?"?', failures, "bff Dockerfile final stage: ARG LUMIRSS_VERSION missing")
    _require(
        bff_runtime,
        r'LABEL org\.opencontainers\.image\.version="\$\{LUMIRSS_VERSION\}"',
        failures,
        "bff Dockerfile: LABEL org.opencontainers.image.version must come from ${LUMIRSS_VERSION}",
    )
    _require(
        bff_runtime,
        r'org\.opencontainers\.image\.revision="\$\{LUMIRSS_COMMIT\}"',
        failures,
        "bff Dockerfile: LABEL org.opencontainers.image.revision must come from ${LUMIRSS_COMMIT}",
    )

    # ---- Web image: labels from LUMIRSS_VERSION + VITE_GIT_COMMIT ---------
    web = _WEB_DOCKERFILE.read_text(encoding="utf-8")
    web_final = _last_dockerfile_stage(web)
    _require(web_final, r'^ARG LUMIRSS_VERSION="?"?', failures, "web Dockerfile final stage: ARG LUMIRSS_VERSION missing")
    _require(web_final, r'^ARG VITE_GIT_COMMIT="?"?', failures, "web Dockerfile final stage: ARG VITE_GIT_COMMIT missing")
    _require(
        web_final,
        r'LABEL org\.opencontainers\.image\.version="\$\{LUMIRSS_VERSION\}"',
        failures,
        "web Dockerfile: LABEL org.opencontainers.image.version must come from ${LUMIRSS_VERSION}",
    )
    _require(
        web_final,
        r'org\.opencontainers\.image\.revision="\$\{VITE_GIT_COMMIT\}"',
        failures,
        "web Dockerfile: LABEL org.opencontainers.image.revision must come from ${VITE_GIT_COMMIT}",
    )

    # ---- publish-images.yml: pass the args from the tested tree/SHA -------
    publish = _PUBLISH_WF.read_text(encoding="utf-8")
    _require(
        publish,
        r'echo "version_file=\$\(cat VERSION\)" >> "\$GITHUB_OUTPUT"',
        failures,
        'publish-images.yml: image version must be read from the VERSION file '
        'of the checked-out (tested) tree',
    )
    if publish.count("LUMIRSS_VERSION=${{ steps.tags.outputs.version_file }}") < 2:
        failures.append(
            "publish-images.yml: BOTH image builds must receive "
            "LUMIRSS_VERSION from steps.tags.outputs.version_file (the VERSION file)"
        )
    _require(
        publish,
        r"LUMIRSS_COMMIT=\$\{\{ steps\.tested\.outputs\.sha \}\}",
        failures,
        "publish-images.yml: bff LUMIRSS_COMMIT must be the tested SHA",
    )
    _require(
        publish,
        r"VITE_GIT_COMMIT=\$\{\{ steps\.tested\.outputs\.sha \}\}",
        failures,
        "publish-images.yml: web VITE_GIT_COMMIT must be the tested SHA",
    )

    # ---- ci.yml: the no-push production builds carry the same metadata ----
    ci = _CI_WF.read_text(encoding="utf-8")
    _require(
        ci,
        r"--build-arg LUMIRSS_COMMIT=\$\{\{ github\.sha \}\}",
        failures,
        "ci.yml: bff build must pass LUMIRSS_COMMIT=github.sha",
    )
    _require(
        ci,
        r"--build-arg VITE_GIT_COMMIT=\$\{\{ github\.sha \}\}",
        failures,
        "ci.yml: web build must pass VITE_GIT_COMMIT=github.sha",
    )
    if ci.count("--build-arg LUMIRSS_VERSION=\"$(cat VERSION)\"") < 2:
        failures.append(
            'ci.yml: BOTH docker build commands must pass '
            '--build-arg LUMIRSS_VERSION="$(cat VERSION)"'
        )

    # ---- FIX-372: stable workflow identity + whole-run conclusion ---------
    _require(
        publish,
        r"actions/workflows/ci\.yml/runs\?head_sha=",
        failures,
        "publish-images.yml: ci-gate must query CI runs by workflow PATH "
        "(actions/workflows/ci.yml), not by display name",
    )
    _require(
        publish,
        r'github\.event\.workflow_run\.head_sha',
        failures,
        "publish-images.yml: workflow_run path must use event's head_sha",
    )
    _require(
        publish,
        r'\[\[ "\$conclusion" == "success" \]\]',
        failures,
        "publish-images.yml: gate must require the run's overall conclusion == success",
    )
    if not _CI_WF.is_file():
        failures.append(f"{_CI_WF_PATH} does not exist at this path")
    elif re.search(r"^name: CI\s*$", ci, flags=re.MULTILINE) is None:
        failures.append(f"{_CI_WF_PATH} must declare `name: CI` (the workflow_run trigger matches by name)")

    # ---- FIX-376: any setup-node cache must hash its lockfile -------------
    for wf in sorted((ROOT / ".github/workflows").glob("*.yml")):
        text = wf.read_text(encoding="utf-8")
        # Pair every `cache: <pm>` with a cache-dependency-path in the same
        # `with:` block (setup-uv needs no explicit config: its default
        # cache-dependency-glob hashes **/uv.lock + **/pyproject.toml).
        for block in re.split(r"\n(?=- name:|- uses:)", text):
            if re.search(r"^\s*cache: (npm|yarn|pnpm)\s*$", block, flags=re.MULTILINE):
                if "cache-dependency-path:" not in block:
                    failures.append(
                        f"{wf.name}: setup-node `cache:` without an explicit "
                        "cache-dependency-path (key must hash the lockfile)"
                    )

    return failures


def main() -> int:
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    failures = check_image_metadata()
    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        return 1
    print(f"image metadata ok: OCI labels wired to VERSION ({version}) + tested SHA; "
          "ci-gate identity is path-based; node caches hash lockfiles")
    return 0


if __name__ == "__main__":
    sys.exit(main())
