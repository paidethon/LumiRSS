#!/usr/bin/env python3
"""FIX-379: a half-finished release must not end green.

Before publish-images.yml concludes, this script asserts — against SERVER
truth (gh release view --json assets), not local staging — that:

  1. every REQUIRED asset is present on the release;
  2. every asset has a non-zero size (an empty/truncated upload is a
     failure, not an asset);
  3. when --sums is given, SHA256SUMS names EXACTLY the asset set (every
     official attachment has a checksum entry and no entry names a phantom
     file) — the FIX-377 completeness contract, verified where it matters.

Deterministic, stdlib only; exit 1 with one FAIL line per problem.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def check_assets(assets_json: dict, sums_path: Path | None, required: list[str]) -> list[str]:
    failures: list[str] = []
    assets = assets_json.get("assets")
    if assets is None:
        return [f"assets JSON has no 'assets' key (gh release view --json assets): "
                f"got keys {sorted(assets_json)}"]

    by_name: dict[str, dict] = {}
    for asset in assets:
        name = asset.get("name", "")
        if name in by_name:
            failures.append(f"duplicate asset name on release: {name!r}")
        by_name[name] = asset

    for name in required:
        asset = by_name.get(name)
        if asset is None:
            failures.append(f"required asset missing from the release: {name}")
            continue
        size = asset.get("size")
        if not isinstance(size, int) or size <= 0:
            failures.append(f"required asset {name} has size {size!r} — treat as absent")

    if sums_path is not None:
        try:
            lines = [
                ln for ln in sums_path.read_text(encoding="utf-8").splitlines() if ln.strip()
            ]
        except OSError as exc:
            failures.append(f"SHA256SUMS unreadable: {exc}")
            lines = []
        names: list[str] = []
        for ln in lines:
            # sha256sum format: "<hex>  <name>" (two spaces); names with
            # spaces are legal — split on the first double-space run.
            parts = ln.split("  ", 1)
            if len(parts) != 2 or len(parts[0]) != 64:
                failures.append(f"malformed SHA256SUMS line: {ln!r}")
                continue
            names.append(parts[1])
        for name in sorted(set(names)):
            if name not in by_name:
                failures.append(f"SHA256SUMS names a file that is not a release asset: {name}")
        for name in sorted(set(by_name) - set(names)):
            failures.append(f"release asset has no SHA256SUMS entry: {name}")

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Assert required GitHub Release assets exist (FIX-379)"
    )
    parser.add_argument(
        "--assets-json", required=True, type=Path,
        help="output of: gh release view <tag> --json assets",
    )
    parser.add_argument(
        "--sums", type=Path, default=None,
        help="SHA256SUMS file; when given, its name set must equal the asset set",
    )
    parser.add_argument("--required", nargs="+", required=True)
    args = parser.parse_args()

    try:
        assets_json = json.loads(args.assets_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"FAIL assets JSON unreadable: {exc}")
        return 1

    failures = check_assets(assets_json, args.sums, args.required)
    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        return 1
    print(f"release assets ok: {', '.join(args.required)} present with content"
          + (f"; SHA256SUMS covers exactly the {len(assets_json.get('assets', []))} asset(s)"
             if args.sums else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
