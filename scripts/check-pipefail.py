#!/usr/bin/env python3
"""FIX-390 guard: a command piped into tail/head must never return success
after the real command failed.

Audited scope (release/deploy paths):
  - .github/workflows/*.yml  -> per STEP: a run block that pipes into
    tail/head must declare `pipefail` in that same block;
  - shell scripts (root `lumirss`, scripts/*.sh, tests/deploy/*.sh,
    e2e/stack/*.sh, apps/web/*.sh) -> a file that pipes into tail/head must
    declare `pipefail` file-wide (`set -o pipefail` / `set -euo pipefail`).

Notes:
  - `docker logs --tail 40` and friends are FLAGS, not pipes — never matched;
  - `$(cmd | tail -1)` inside `set -uo pipefail` scripts propagates the
    producer's failure; sites that swallow deliberately must do so with an
    explicit `|| true`/fallback that a human wrote on purpose (the pipefail
    requirement makes the escape hatch visible in review);
  - deterministic, stdlib only; repository-checks + tests/deploy call it.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# `|` + optional spaces + tail/head as a word — a real pipe into the tool.
_PIPE_INTO = re.compile(r"\|\s*(?:tail|head)\b")
_PIPEFAIL_DECL = re.compile(r"^\s*set\s+[^#\n]*pipefail", re.MULTILINE)
_STEP_SPLIT = re.compile(r"\n(?=- (?:name|uses):)")

_SHELL_TARGETS = [
    Path("lumirss"),
    Path("scripts/freshrss_pool.sh"),
    Path("e2e/stack/run-smoke.sh"),
]
_SHELL_GLOBS = ["scripts/*.sh", "tests/deploy/*.sh", "e2e/stack/*.sh", "apps/web/*.sh"]


def _workflow_failures(wf: Path, text: str) -> list[str]:
    failures: list[str] = []
    for block in _STEP_SPLIT.split(text):
        # Only judge actual run scripts; `| tail` inside a comment or a
        # non-run context (e.g. a YAML string) would be a false positive.
        run_matches = re.findall(
            r"^[ \t]*run:\s*[>|]?\n?((?:(?:^[ \t]+).*\n?)*)", block, re.MULTILINE
        )
        for run_body in run_matches:
            if _PIPE_INTO.search(run_body) and not re.search(r"pipefail", block):
                line = next(
                    ln.strip() for ln in run_body.splitlines() if _PIPE_INTO.search(ln)
                )
                failures.append(
                    f"{wf.name}: run step pipes into tail/head without `set ... pipefail`: {line!r}"
                )
    return failures


def _shell_failures(path: Path, text: str, root: Path) -> list[str]:
    if not _PIPE_INTO.search(text):
        return []
    if _PIPEFAIL_DECL.search(text):
        return []
    lines = [f"  {i + 1}: {ln.strip()}" for i, ln in enumerate(text.splitlines()) if _PIPE_INTO.search(ln)]
    return [
        f"{path.relative_to(root)}: pipes into tail/head but never declares "
        f"`set -o pipefail` (producer failures are silently dropped):\n"
        + "\n".join(lines)
    ]


def check_pipefail(root: Path = ROOT) -> list[str]:
    failures: list[str] = []

    wf_dir = root / ".github/workflows"
    if wf_dir.is_dir():
        for wf in sorted(wf_dir.glob("*.yml")):
            failures.extend(_workflow_failures(wf, wf.read_text(encoding="utf-8")))

    targets = [root / t for t in _SHELL_TARGETS]
    for pattern in _SHELL_GLOBS:
        targets.extend(sorted(root.glob(pattern)))
    seen: set[Path] = set()
    for path in targets:
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        failures.extend(_shell_failures(path, path.read_text(encoding="utf-8"), root))

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="FIX-390 pipe error-propagation guard")
    parser.add_argument(
        "--root", type=Path, default=ROOT,
        help="repo root to scan (default: the checkout this script lives in)",
    )
    args = parser.parse_args()
    failures = check_pipefail(args.root)
    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        return 1
    print(
        "pipe hygiene ok: every tail/head pipe in workflows/scripts declares "
        "pipefail — no command hides a failure behind a truncated pipe (FIX-390)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
