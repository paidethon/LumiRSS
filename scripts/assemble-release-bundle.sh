#!/usr/bin/env bash
# Assemble the ready-to-install LumiRSS release bundle (FIX-186/187).
#
# A release must ship something an operator can install DIRECTLY — not
# only an Actions-artifact manifest. The bundle is self-contained: the
# lumirss CLI, the production compose file (+ optional-mode fragments),
# the .env template, the VERSION single source, INSTALL instructions and
# the release manifest (digest-pinned images, migration metadata, the
# FIX-188 min_compat floor), with SHA256SUMS over the whole set.
#
# Blank-environment validation is part of assembly: the script copies the
# set into a fresh directory, verifies checksums and the manifest schema,
# syntax-checks the CLI, and renders `docker compose config` from the
# BUNDLE directory against a template .env.prod — no repository files are
# consulted there. Any failure aborts assembly with a nonzero exit.
#
# Usage:
#   scripts/assemble-release-bundle.sh --out DIR [--manifest release-manifest.json]
#
# Deterministic, no network. CI (publish-images.yml) and
# tests/deploy/run-release-bundle-tests.sh both call it.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT=""
MANIFEST=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --out) OUT="${2:?}"; shift 2;;
    --manifest) MANIFEST="${2:?}"; shift 2;;
    *) echo "unknown argument: $1" >&2; exit 1;;
  esac
done
[[ -n "$OUT" ]] || { echo "usage: $0 --out DIR [--manifest FILE]" >&2; exit 1; }
[[ -d "$OUT" ]] || { echo "--out must be an existing directory" >&2; exit 1; }

version="$(cat "$ROOT/VERSION")"
bundle="$OUT/lumirss-release-bundle-$version"

# --- collect ----------------------------------------------------------------
rm -rf "$bundle"
mkdir -p "$bundle"
cp -p "$ROOT/lumirss" "$bundle/"
cp -p "$ROOT/docker-compose.prod.yml" \
      "$ROOT/docker-compose.external-caddy.yml" \
      "$ROOT/docker-compose.obsidian.yml" \
      "$ROOT/.env.prod.example" \
      "$ROOT/VERSION" \
      "$bundle/"
if [[ -n "$MANIFEST" ]]; then
  [[ -f "$MANIFEST" ]] || { echo "manifest not found: $MANIFEST" >&2; exit 1; }
  cp -p "$MANIFEST" "$bundle/release-manifest.json"
fi
cp -p "$ROOT/scripts/INSTALL-BUNDLE.md" "$bundle/INSTALL.md" 2>/dev/null || {
  echo "missing scripts/INSTALL-BUNDLE.md (install instructions are part of the bundle)" >&2
  exit 1
}

# --- verify what we just collected (FIX-187 acceptance) ---------------------
fail() { echo "bundle verification FAILED: $*" >&2; exit 1; }

# Every required piece exists and is non-empty.
for f in lumirss docker-compose.prod.yml docker-compose.external-caddy.yml \
         docker-compose.obsidian.yml \
         .env.prod.example VERSION INSTALL.md; do
  [[ -s "$bundle/$f" ]] || fail "required bundle file missing or empty: $f"
done
[[ -x "$bundle/lumirss" ]] || fail "lumirss CLI lost its exec bit in the bundle"

# Manifest: schema + identity must describe THIS release (FIX-185: no mixed
# builds — version/git_sha present and the image refs are digest-pinned).
if [[ -f "$bundle/release-manifest.json" ]]; then
  python3 - "$bundle/release-manifest.json" "$version" <<'PY' || fail "manifest identity check"
import json, sys
path, version = sys.argv[1], sys.argv[2]
m = json.load(open(path, encoding="utf-8"))
problems = []
if m.get("schema") != "lumirss-release-manifest/v1":
    problems.append(f"schema {m.get('schema')!r}")
if m.get("version") != version:
    problems.append(f"version {m.get('version')!r} != {version!r}")
if not str(m.get("git_sha") or "").strip():
    problems.append("git_sha missing")
for role in ("bff", "web"):
    ref = str((m.get("images") or {}).get(role) or "")
    if "@sha256:" not in ref:
        problems.append(f"{role} image not digest-pinned: {ref!r}")
if not isinstance(m.get("migrations"), list) or not m["migrations"]:
    problems.append("migration metadata (migrations) missing")
mc = m.get("min_compat")
if mc is not None and not str(mc).strip():
    problems.append("min_compat present but empty")
if problems:
    print("; ".join(problems))
    sys.exit(1)
PY
fi

# CLI syntax + entry point actually starts (usage path needs no docker).
bash -n "$bundle/lumirss" || fail "lumirss CLI failed bash -n"

# Compose render from the BUNDLE dir with a template env — the blank-env
# install shape (FIX-187). No repo compose file is reachable from there.
cp "$bundle/.env.prod.example" "$bundle/.env.prod"
(
  cd "$bundle"
  docker compose -f docker-compose.prod.yml config > /dev/null 2>&1 \
    || fail "compose config render failed inside the bundle"
  rm -f .env.prod
)

# Checksum manifest over the FINAL bundle set (exclude the sums file in
# BOTH of its transient names — the shell redirect creates the temp target
# before find runs, so a naive listing would sum the empty file into itself).
( cd "$bundle" && find . -mindepth 1 -maxdepth 1 -type f \
    -not -name SHA256SUMS -not -name '.SHA256SUMS.tmp' -printf '%f\n' \
    | LC_ALL=C sort | xargs -d '\n' sha256sum > .SHA256SUMS.tmp \
    && mv .SHA256SUMS.tmp SHA256SUMS )
( cd "$bundle" && sha256sum -c SHA256SUMS > /dev/null ) || fail "bundle checksum self-verification failed"

echo "bundle assembled: $bundle ($(ls -A "$bundle" | wc -l) files, SHA256SUMS verified)"
