#!/usr/bin/env python3
"""Validate checked-in .env*.example templates.

Guards against the post-merge regression where a config key ended up
glued onto the end of a comment line (invisible as config, silently
ignored by compose). Checks, per template:

- every non-blank, non-comment line is a well-formed KEY=value line;
- no duplicate keys;
- every expected key exists;
- no value looks like a real secret (values must be empty or a
  documented placeholder).

Stdlib only; run from anywhere:
    python3 scripts/check_env_example.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

EXPECTED_KEYS: dict[str, tuple[str, ...]] = {
    ".env.prod.example": (
        "LUMIRSS_AUTH_USER",
        "LUMIRSS_AUTH_HASH",
        "DOMAIN",
        "FRESHRSS_BASE_URL",
        "FRESHRSS_USERNAME",
        "FRESHRSS_API_PASSWORD",
        "FRESHRSS_PUBLIC_URL",
        "RSSHUB_BASE_URL",
        "RSSHUB_FRESHRSS_BASE_URL",
        "AI_API_KEY",
        "LUMIRSS_EXTERNAL_CADDY",
        "LUMIRSS_UPSTREAM_PORT",
        "LUMIRSS_INTERNAL_TOKEN",
    ),
}

KEY_LINE = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_]*)=(?P<value>.*)$")

# A filled-in template value is only acceptable when it is obviously a
# placeholder (empty, an internal Docker/localhost URL, or a short hint).
PLACEHOLDER_VALUE = re.compile(
    r"^$|^(https?://[A-Za-z0-9._-]+(:\d+)?|localhost|admin)$"
)


def check_template(path: Path, expected_keys: tuple[str, ...]) -> list[str]:
    problems: list[str] = []
    seen: dict[str, int] = {}
    for lineno, raw in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = KEY_LINE.match(line)
        if match is None:
            problems.append(
                f"{path}:{lineno}: malformed line (not KEY=value, "
                f"key glued to comment?): {raw!r}"
            )
            continue
        key = match.group("key")
        if key in seen:
            problems.append(
                f"{path}:{lineno}: duplicate key {key} "
                f"(first seen on line {seen[key]})"
            )
        else:
            seen[key] = lineno
        if not PLACEHOLDER_VALUE.match(match.group("value").strip()):
            problems.append(
                f"{path}:{lineno}: {key} has a non-placeholder value in a "
                f"committed template"
            )
    for key in expected_keys:
        if key not in seen:
            problems.append(f"{path}: missing expected key {key}")
    return problems


def main() -> int:
    all_problems: list[str] = []
    for name, expected in EXPECTED_KEYS.items():
        path = REPO_ROOT / name
        if not path.is_file():
            all_problems.append(f"missing template file: {name}")
            continue
        all_problems.extend(check_template(path, expected))
    if all_problems:
        for problem in all_problems:
            print(f"::error::{problem}")
        return 1
    print(f"env example templates OK ({len(EXPECTED_KEYS)} checked)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
