#!/usr/bin/env python3
"""Validate checked-in .env*.example templates + config docs against code.

Guards against two regression classes:

1. The post-merge regression where a config key ended up glued onto the
   end of a comment line (invisible as config, silently ignored by
   compose). Checks, per template:

   - every non-blank, non-comment line is a well-formed KEY=value line;
   - no duplicate keys;
   - every expected key exists;
   - no value looks like a real secret (values must be empty or a
     documented placeholder).

2. The FIX-397 class: prose claims a non-empty fallback for a key
   ("Empty = X" / "空 = X" / "Default when empty: X") that contradicts
   the actual code/compose default. NONEMPTY_FALLBACKS records every
   fallback that is a concrete value in the code (with its source);
   whenever a scanned file mentions such a key together with a
   default-claim marker, the recorded literal must appear in the same
   claim window (the key line plus its contiguous comment block above).
   A doc that says "空 = 返回相对路径" for LUMIRSS_ATOM_BASE_URL fails
   because the code actually falls back to http://bff:8000.

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
        "LUMIRSS_AUTH_MODE",
        "LUMIRSS_SESSION_MAX_AGE_DAYS",
        "LUMIRSS_SESSION_SECURE_COOKIES",
        "LUMIRSS_PUBLIC_ORIGIN",
        "LUMIRSS_WEB_MEM_LIMIT",
        "LUMIRSS_WEB_MEM_RESERVATION",
        "LUMIRSS_BFF_MEM_LIMIT",
        "LUMIRSS_BFF_MEM_RESERVATION",
        "LUMIRSS_FRESHRSS_MEM_LIMIT",
        "LUMIRSS_FRESHRSS_MEM_RESERVATION",
        "LUMIRSS_RSSHUB_MEM_LIMIT",
        "LUMIRSS_RSSHUB_MEM_RESERVATION",
        "LUMIRSS_RSSHUB_MEMORY_MAX",
        "LUMIRSS_RSSHUB_NODE_OPTIONS",
        "DOMAIN",
        "FRESHRSS_BASE_URL",
        "FRESHRSS_USERNAME",
        "FRESHRSS_API_PASSWORD",
        "FRESHRSS_PUBLIC_URL",
        "RSSHUB_BASE_URL",
        "RSSHUB_FRESHRSS_BASE_URL",
        "AI_API_KEY",
        "LUMIRSS_IMAGE_TAG",
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

# FIX-397: non-empty fallback defaults, each verified against the code
# (source noted per entry). If the code fallback ever changes, update the
# entry here AND the prose in .env.prod.example /
# docs/configuration.md — the checker fails until all three
# agree.
NONEMPTY_FALLBACKS: dict[str, tuple[str, str]] = {
    "LUMIRSS_ATOM_BASE_URL": (
        "http://bff:8000",
        "services/bff/src/lumirss/api_sources.py atom_base()",
    ),
    "LUMIRSS_UPSTREAM_PORT": (
        "18080",
        "docker-compose.external-caddy.yml + ./lumirss",
    ),
    "LUMIRSS_RAG_INDEX_INTERVAL": (
        "300",
        "services/bff/src/lumirss/config.py LumiSettings",
    ),
    "LUMIRSS_SESSION_MAX_AGE_DAYS": (
        "180",
        "services/bff/src/lumirss/config.py LumiSettings",
    ),
    "LUMIRSS_SESSION_SECURE_COOKIES": (
        "1",
        "services/bff/src/lumirss/config.py LumiSettings (bool True)",
    ),
    "LUMIRSS_FRESHRSS_CRON_MIN": (
        "13,43",
        "docker-compose.prod.yml",
    ),
    "DOMAIN": ("localhost", "docker-compose.prod.yml"),
    # FIX-184: the fallback is no longer a literal — the mutable `latest`
    # was replaced by the release VERSION tag. The prose must name VERSION
    # as the single source; the compose default == VERSION equality is
    # enforced by scripts/check-version.py.
    "LUMIRSS_IMAGE_TAG": (
        "VERSION",
        "VERSION file + docker-compose.prod.yml (FIX-184: pinned release tag, never latest)",
    ),
}

# Files scanned for fallback-claim prose (in addition to the templates'
# structural checks above).
CLAIM_SCAN_FILES: tuple[str, ...] = (
    ".env.prod.example",
    "services/bff/.env.example",
    "docs/configuration.md",
)

# Phrases that introduce an empty/default claim. When one appears in the
# claim window of a NONEMPTY_FALLBACKS key, the fallback literal must be
# present in the same window.
CLAIM_MARKERS: tuple[str, ...] = (
    "空",
    "留空",
    "默认",
    "缺省",
    "empty",
    "default",
    "fallback",
    "回退",
)


def _claim_window(lines: list[str], key_line_idx: int) -> str:
    """The key line plus the contiguous '#' comment block above it.

    In env templates the prose lives in that comment block; in markdown
    tables the whole claim sits on the row line itself (no comment
    lines), so the window degenerates to the row.
    """
    window = [lines[key_line_idx]]
    idx = key_line_idx - 1
    while idx >= 0 and lines[idx].lstrip().startswith("#"):
        window.insert(0, lines[idx])
        idx -= 1
    return " ".join(window)


_KEY_TOKEN = re.compile(r"\b[A-Z][A-Z0-9_]{2,}\b")


def _primary_keys(line: str) -> set[str]:
    """Which key a line is *about* (only those get claim-checked).

    - KEY=value line: the left-hand key. The comment block above belongs
      to it.
    - Markdown table row: the keys in the FIRST column. A registry key
      merely *mentioned* in a later column (e.g. the LUMIRSS_EXTERNAL_
      CADDY row citing 127.0.0.1:LUMIRSS_UPSTREAM_PORT) is not the row's
      subject and must not inherit its "（空）" default claim.
    - Any other line (prose): every key token on the line.
    """
    kv = KEY_LINE.match(line)
    if kv is not None:
        return {kv.group("key")}
    if line.lstrip().startswith("|"):
        first_column = line.split("|")[1] if "|" in line else ""
        return set(_KEY_TOKEN.findall(first_column))
    return set(_KEY_TOKEN.findall(line))


def check_fallback_claims(path: Path) -> list[str]:
    """Every default claim for a known key must contain the real fallback."""
    problems: list[str] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        primary = _primary_keys(line)
        for key, (fallback, source) in NONEMPTY_FALLBACKS.items():
            if key not in primary:
                continue
            window = _claim_window(lines, i)
            if not any(marker in window for marker in CLAIM_MARKERS):
                continue
            if fallback not in window:
                problems.append(
                    f"{path}:{i + 1}: {key} claims an empty/default value "
                    f"but the verified code fallback is {fallback!r} "
                    f"(source: {source}); update the prose or the checker "
                    f"registry together with the code"
                )
    return problems


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
    for name in CLAIM_SCAN_FILES:
        path = REPO_ROOT / name
        if not path.is_file():
            all_problems.append(f"missing scanned file: {name}")
            continue
        all_problems.extend(check_fallback_claims(path))
    if all_problems:
        for problem in all_problems:
            print(f"::error::{problem}")
        return 1
    print(
        f"env example templates OK "
        f"({len(EXPECTED_KEYS)} structural, {len(CLAIM_SCAN_FILES)} "
        f"fallback-claim files, {len(NONEMPTY_FALLBACKS)} registered defaults)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
