#!/usr/bin/env bash
# Release install-bundle tests (FIX-186/187):
#   - assembly produces a self-contained, checksum-verified, blank-env-
#     installable bundle (CLI + compose + env template + VERSION + manifest
#     with digest pins/migrations/min_compat + INSTALL + SHA256SUMS)
#   - manifest identity mismatches (version / digest pin / migrations) are
#     refused — no mixed builds ship (FIX-185)
#   - tampering with any bundle file breaks SHA256SUMS
# Requires docker (the blank-env compose render) but no registry, no push.
# Run from anywhere: tests/deploy/run-release-bundle-tests.sh
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PASS=0
FAIL=0

ok()  { printf '  ok   %s\n' "$1"; PASS=$((PASS + 1)); }
bad() { printf '  FAIL %s\n' "$1"; FAIL=$((FAIL + 1)); }
assert_eq() { if [[ "$2" == "$3" ]]; then ok "$1"; else bad "$1 — expected [$2] got [$3]"; fi; }

version="$(cat "$REPO_ROOT/VERSION")"
work="$(mktemp -d "${TMPDIR:-/tmp}/lumirss-bundle-tests.XXXXXX")"
trap 'rm -rf "$work"' EXIT

good_manifest() { # file
  cat > "$1" <<JSON
{
  "schema": "lumirss-release-manifest/v1",
  "name": "LumiRSS",
  "version": "$version",
  "git_sha": "0123456789abcdef0123456789abcdef01234567",
  "generated_at": "2026-10-01T00:00:00Z",
  "images": {
    "bff": "ghcr.io/paidethon/lumirss/lumirss-bff@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "web": "ghcr.io/paidethon/lumirss/lumirss-web@sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
  },
  "platform": "linux/amd64",
  "migrations": ["0001_baseline.sql", "0323_latest.sql"],
  "min_compat": "2.7.0",
  "note": "test manifest"
}
JSON
}

# ---------------------------------------------------------------------------
echo "== 1. assembly: self-contained, verified, installable =="
mkdir "$work/out1"
good_manifest "$work/manifest.json"
if out="$(bash "$REPO_ROOT/scripts/assemble-release-bundle.sh" --out "$work/out1" --manifest "$work/manifest.json" 2>&1)"; then
  ok "assembly exits 0"
else
  bad "assembly failed: $out"
fi
bundle="$work/out1/lumirss-release-bundle-$version"
assert_eq "bundle named after VERSION" "lumirss-release-bundle-$version" "$(basename "$bundle")"
for f in lumirss docker-compose.prod.yml docker-compose.external-caddy.yml \
         docker-compose.obsidian.yml \
         .env.prod.example VERSION release-manifest.json INSTALL.md SHA256SUMS; do
  [[ -s "$bundle/$f" ]] && ok "bundle carries $f" || bad "bundle missing $f"
done
[[ -x "$bundle/lumirss" ]] && ok "CLI keeps its exec bit in the bundle" || bad "CLI not executable"
( cd "$bundle" && sha256sum -c SHA256SUMS > /dev/null 2>&1 ) \
  && ok "SHA256SUMS verifies over the whole bundle" || bad "SHA256SUMS broken"
[[ "$(find "$bundle" -type l | wc -l)" -eq 0 ]] \
  && ok "no symlinks — bundle is self-contained" || bad "bundle contains symlinks"
[[ ! -e "$bundle/.env.prod" ]] \
  && ok "blank-env render left no stray .env.prod behind" || bad ".env.prod leaked into the bundle"

# ---------------------------------------------------------------------------
echo "== 2. blank-environment install check (FIX-187) =="
# The assembler's compose render already ran inside the bundle; here we
# prove the bundle is operable in isolation: fresh shell, cwd = bundle,
# CLI usage prints without docker and compose config renders from template.
if ( cd "$bundle" && ./lumirss help > /dev/null 2>&1 ); then
  ok "bundle CLI starts from its own directory"
else
  bad "bundle CLI cannot start (cwd-isolated run failed)"
fi
if ( cd "$bundle" && cp .env.prod.example .env.prod \
      && docker compose -f docker-compose.prod.yml config > /dev/null 2>&1; rc=$?; rm -f .env.prod; exit $rc ); then
  ok "compose config renders from the bundle alone (no repo files)"
else
  bad "compose render failed inside the bundle"
fi
( cd "$bundle" && grep -q "LUMIRSS_IMAGE_TAG:-$version" docker-compose.prod.yml ) \
  && ok "bundle compose pins the release tag (FIX-184 semantics)" || bad "bundle compose default is not the release tag"

# ---------------------------------------------------------------------------
echo "== 3. manifest identity mismatches are refused (FIX-185) =="
assemble_with() { # manifest-file outdir-name -> exit code
  bash "$REPO_ROOT/scripts/assemble-release-bundle.sh" --out "$work/$2" --manifest "$1" > /dev/null 2>&1
  echo $?
}
make_bad_manifest() { # name python-mutation
  cp "$work/manifest.json" "$work/bad_$1.json"
  python3 -c "
import json
p = '$work/bad_$1.json'
m = json.load(open(p))
$2
json.dump(m, open(p, 'w'))
"
}
make_bad_manifest version "m['version'] = '9.9.9'"
make_bad_manifest digests "m['images']['web'] = 'ghcr.io/paidethon/lumirss/lumirss-web:latest'"
make_bad_manifest migrations "m['migrations'] = []"
for case_name in version digests migrations; do
  mkdir -p "$work/out_bad_$case_name"
  rc="$(assemble_with "$work/bad_$case_name.json" "out_bad_$case_name")"
  assert_eq "assembler refuses a $case_name-mismatched manifest" "1" "$rc"
done

# ---------------------------------------------------------------------------
echo "== 4. tamper detection: SHA256SUMS catches any modification =="
printf 'tampered\n' >> "$bundle/docker-compose.obsidian.yml"
( cd "$bundle" && sha256sum -c SHA256SUMS > /dev/null 2>&1 )
rc=$?
assert_eq "modified bundle file fails checksum verification" "1" "$rc"

echo
echo "release-bundle tests: $PASS passed, $FAIL failed"
if [[ "$FAIL" -gt 0 ]]; then exit 1; fi
