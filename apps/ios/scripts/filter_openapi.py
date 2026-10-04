#!/usr/bin/env python3
"""Derive the iOS client's OpenAPI subset from the authoritative export.

The full LumiRSS contract (~1100 paths / 2 MB) is far beyond what
swift-openapi-generator can compile in an app target. This script
filters the ONE authoritative document (apps/web/src/api/generated/
openapi.json, itself produced by services/bff/scripts/export_openapi.py
and drift-checked by CI) down to the paths the iOS reader consumes,
walking the $ref graph so every reachable schema is kept.

The output (apps/ios/LumiRSS/API/openapi.json) is a generated artifact:
never hand-edited, always reproducible via

    python3 apps/ios/scripts/filter_openapi.py --check   # CI drift gate

which regenerates and diffs. Web and iOS therefore consume the same
server-exported contract; the filter list below is the only iOS-side
addition (it names WHAT the app uses, not how it is shaped).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SOURCE = REPO_ROOT / "apps" / "web" / "src" / "api" / "generated" / "openapi.json"
OUTPUT = REPO_ROOT / "apps" / "ios" / "LumiRSS" / "API" / "openapi.json"

# Paths the iOS reader consumes. Every path must exist upstream — a
# rename on the server side fails this script (and thus CI) loudly.
IOS_PATHS: tuple[str, ...] = (
    "/api/v1/auth/login",
    "/api/v1/auth/session",
    "/api/v1/auth/logout",
    "/api/v1/auth/totp/verify",
    "/api/v1/version",
    "/api/v1/entries",
    "/api/v1/entries/{entry_ref}",
    "/api/v1/entries/{entry_ref}/state",
    "/api/v1/subscriptions",
    "/api/v1/categories",
    "/api/v1/search",
    "/health/live",
)


def _refs_of(node: object, found: set[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                found.add(value)
            else:
                _refs_of(value, found)
    elif isinstance(node, list):
        for item in node:
            _refs_of(item, found)


def build_subset(source: dict) -> dict:
    missing = [p for p in IOS_PATHS if p not in source.get("paths", {})]
    if missing:
        raise SystemExit(f"iOS contract references unknown paths (server rename?): {missing}")

    subset: dict = {
        "openapi": source.get("openapi", "3.0.3"),
        "info": source["info"],
        "servers": source.get("servers", []),
        "paths": {p: source["paths"][p] for p in IOS_PATHS},
        "components": {"schemas": {}},
    }

    # Transitive closure over components sections that can be $ref'd.
    keep: set[str] = set()
    pending: list[dict] = list(subset["paths"].values())
    while pending:
        node = pending.pop()
        found: set[str] = set()
        _refs_of(node, found)
        for ref in found:
            if ref in keep:
                continue
            keep.add(ref)
            section, _, name = ref.removeprefix("#/components/").partition("/")
            bucket = source.get("components", {}).get(section, {})
            if name in bucket:
                pending.append(bucket[name])

    for ref in sorted(keep):
        section, _, name = ref.removeprefix("#/components/").partition("/")
        bucket = source.get("components", {}).get(section, {})
        if name in bucket:
            components = subset["components"].setdefault(section, {})
            components[name] = bucket[name]

    return subset


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 when the committed subset drifted")
    args = parser.parse_args()

    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    subset = build_subset(source)
    rendered = json.dumps(subset, ensure_ascii=False, indent=1, sort_keys=True) + "\n"

    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current != rendered:
            print(
                "apps/ios OpenAPI subset drifted from the authoritative export.\n"
                "Regenerate with: python3 apps/ios/scripts/filter_openapi.py",
                file=sys.stderr,
            )
            return 1
        print(f"iOS OpenAPI subset in sync ({len(subset['paths'])} paths, "
              f"{len(subset['components'].get('schemas', {}))} schemas)")
        return 0

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(rendered, encoding="utf-8")
    print(f"wrote {OUTPUT.relative_to(REPO_ROOT)} "
          f"({len(subset['paths'])} paths, {len(subset['components'].get('schemas', {}))} schemas)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
