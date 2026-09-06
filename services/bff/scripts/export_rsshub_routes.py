#!/usr/bin/env python3
"""Vendor the RSSHub route metadata snapshot from the PINNED image.

RSSHub already owns its route metadata (path, parameters, examples). The
pinned image ships it generated at ``/app/assets/build/routes.json``. This
script extracts the namespaces Lumi curates into
``src/lumirss/rsshub_routes.generated.json`` so a test can verify the
Lumi catalog against the exact upstream version we deploy — without
production ever fetching remote metadata.

The running container's image digest must match the ``diygod/rsshub@`` pin
in docker-compose.yml (and docker-compose.prod.yml). When you bump the
pin: pull the new image, recreate the container, re-run this script, and
commit the refreshed snapshot together with the pin bump.

Usage (RSSHub dev stack running):

    uv run python scripts/export_rsshub_routes.py [--container rsshub]
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

BFF_ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = BFF_ROOT / "src" / "lumirss" / "rsshub_routes.generated.json"
COMPOSE_PATH = BFF_ROOT.parents[1] / "docker-compose.yml"

# Namespaces the Lumi catalog curates (keep in sync with rsshub.py CATALOG).
NAMESPACES = [
    "ithome",
    "github",
    "zhihu",
    "sspai",
    "hackernews",
    "youtube",
    "v2ex",
    "cnbeta",
    "huxiu",
    "36kr",
    "coolapk",
    "readhub",
    "douban",
]

SCHEMA_VERSION = 1


def compose_rsshub_pin() -> str:
    """The diygod/rsshub@sha256:... image pin from docker-compose.yml."""
    text = COMPOSE_PATH.read_text(encoding="utf-8")
    match = re.search(r"image:\s*(diygod/rsshub@sha256:[0-9a-f]{64})", text)
    if match is None:
        sys.exit("docker-compose.yml has no digest-pinned diygod/rsshub image.")
    return match.group(1)


def local_image_digest() -> str | None:
    """The manifest digest of the locally pulled diygod/rsshub image."""
    result = subprocess.run(
        ["docker", "images", "diygod/rsshub", "--format", "{{.Digest}}"],
        capture_output=True,
        text=True,
        check=True,
    )
    digest = result.stdout.strip().splitlines()
    if not digest or not digest[0]:
        return None
    raw = digest[0]
    return raw if raw.startswith("sha256:") else f"sha256:{raw}"


def read_routes_json(container: str) -> dict:
    result = subprocess.run(
        ["docker", "exec", container, "cat", "/app/assets/build/routes.json"],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def slim_route(route: dict) -> dict:
    """Keep the fields the catalog check needs (drop bulky docs blobs)."""
    return {
        "path": route.get("path"),
        "name": route.get("name"),
        "example": route.get("example"),
        "parameters": route.get("parameters") or {},
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--container", default="rsshub")
    args = parser.parse_args()

    pin = compose_rsshub_pin()
    digest = local_image_digest()
    if digest is None:
        sys.exit("No diygod/rsshub image found locally — docker pull the pinned image first.")
    if digest != pin.split("@", 1)[1]:
        sys.exit(
            f"Local image digest {digest} does not match the compose pin {pin}.\n"
            "Pull the pinned image and recreate the container, then re-run."
        )

    all_routes = read_routes_json(args.container)
    missing = [ns for ns in NAMESPACES if ns not in all_routes]
    if missing:
        sys.exit(f"Namespaces missing from upstream metadata: {', '.join(missing)}")

    snapshot = {
        "_meta": {
            "schemaVersion": SCHEMA_VERSION,
            "rsshubImage": pin,
            "source": "/app/assets/build/routes.json (generated inside the pinned image)",
        },
        "namespaces": {
            ns: {
                path: slim_route(route)
                for path, route in sorted(all_routes[ns].get("routes", {}).items())
            }
            for ns in NAMESPACES
        },
    }
    OUT_PATH.write_text(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=1) + "\n",
        encoding="utf-8",
    )
    routes_total = sum(len(ns) for ns in snapshot["namespaces"].values())
    print(f"wrote {OUT_PATH.relative_to(BFF_ROOT.parents[1])} ({routes_total} routes, image {pin.split('@')[1][:12]})")


if __name__ == "__main__":
    main()
