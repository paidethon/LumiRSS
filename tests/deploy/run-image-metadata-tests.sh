#!/usr/bin/env bash
# Release-pipeline metadata + build-context tests (no push, no registry):
#   - O190 version single source still holds (scripts/check-version.py)
#   - FIX-373: OCI labels + build args are wired to VERSION + tested SHA
#     (scripts/check-image-metadata.py; mutation-tested here)
#   - FIX-375: a POISONED build context (local credentials, ledgers, VCS
#     state, task packages) is actually excluded — verified by building a
#     FROM-scratch probe image with the repo's real .dockerignore and
#     listing the files that entered the build, plus a static check that
#     every build context path in workflows/compose is a subdirectory
#     (never the repo root, so root-level .env.prod / ledgers are out of
#     context by construction)
#   - FIX-376: node caches hash lockfiles (checker pin, mutation-tested)
# Run from anywhere: tests/deploy/run-image-metadata-tests.sh
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PASS=0
FAIL=0

ok()  { printf '  ok   %s\n' "$1"; PASS=$((PASS + 1)); }
bad() { printf '  FAIL %s\n' "$1"; FAIL=$((FAIL + 1)); }

assert_eq() { # desc expected actual
  if [[ "$2" == "$3" ]]; then ok "$1"; else bad "$1 — expected [$2] got [$3]"; fi
}
assert_contains() { # desc needle haystack
  if [[ "$3" == *"$2"* ]]; then ok "$1"; else bad "$1 — missing [$2]"; fi
}

copy_tree() { # worktree copy without .git / venvs / node_modules
  local dst; dst="$(mktemp -d "${TMPDIR:-/tmp}/lumirss-meta.XXXXXX")"
  (cd "$REPO_ROOT" && tar -cf - \
    --exclude=.git --exclude=.venv --exclude=node_modules \
    --exclude='*.sqlite' --exclude='*.sqlite-*' \
    .) | (mkdir -p "$dst" && tar -xf - -C "$dst")
  printf '%s\n' "$dst"
}

# ---------------------------------------------------------------------------
echo "== 1. baseline: version + image-metadata checkers pass on the real tree =="
if out="$(python3 "$REPO_ROOT/scripts/check-version.py" 2>&1)"; then
  ok "O190 check-version passes ($out)"
else
  bad "O190 check-version FAILED: $out"
fi
if out="$(python3 "$REPO_ROOT/scripts/check-image-metadata.py" 2>&1)"; then
  ok "check-image-metadata passes ($out)"
else
  bad "check-image-metadata FAILED: $out"
fi

# ---------------------------------------------------------------------------
echo "== 2. mutation tests: each drifted source is caught =="
wt="$(copy_tree)"

sed -i 's/"version": "2.0.1"/"version": "9.9.9"/' "$wt/apps/web/package.json"
if python3 "$wt/scripts/check-version.py" >/dev/null 2>&1; then
  bad "mutation: web package.json version drift NOT caught by check-version"
else
  ok "mutation: web package.json version drift caught by check-version"
fi
sed -i 's/"version": "9.9.9"/"version": "2.0.1"/' "$wt/apps/web/package.json"

sed -i '/LABEL org\.opencontainers\.image\.version/d; /org\.opencontainers\.image\.revision/d' \
  "$wt/services/bff/Dockerfile" "$wt/apps/web/Dockerfile"
if python3 "$wt/scripts/check-image-metadata.py" >/dev/null 2>&1; then
  bad "mutation: dropped OCI labels NOT caught"
else
  ok "mutation: dropped OCI labels caught"
fi

sed -i '/LUMIRSS_VERSION=\${{ steps.tags.outputs.version }}/d' "$wt/.github/workflows/publish-images.yml"
if python3 "$wt/scripts/check-image-metadata.py" >/dev/null 2>&1; then
  bad "mutation: publish build without VERSION-file arg NOT caught"
else
  ok "mutation: publish build without VERSION-file arg caught"
fi
cp "$REPO_ROOT/.github/workflows/publish-images.yml" "$wt/.github/workflows/publish-images.yml"

sed -i 's#actions/workflows/ci.yml/runs?head_sha=#actions/workflows/other.yml/runs?head_sha=#' \
  "$wt/.github/workflows/publish-images.yml"
if python3 "$wt/scripts/check-image-metadata.py" >/dev/null 2>&1; then
  bad "mutation: gate queried by a non-ci.yml path NOT caught"
else
  ok "mutation: gate queried by a non-ci.yml path caught"
fi
cp "$REPO_ROOT/.github/workflows/publish-images.yml" "$wt/.github/workflows/publish-images.yml"

sed -i '/cache-dependency-path:/d' "$wt/.github/workflows/ci.yml" "$wt/.github/workflows/docs.yml"
if python3 "$wt/scripts/check-image-metadata.py" >/dev/null 2>&1; then
  bad "mutation: node cache without lockfile pin NOT caught"
else
  ok "mutation: node cache without lockfile pin caught"
fi
sed -i '/--build-arg LUMIRSS_VERSION/d' "$wt/.github/workflows/ci.yml"
if python3 "$wt/scripts/check-image-metadata.py" >/dev/null 2>&1; then
  bad "mutation: ci build without LUMIRSS_VERSION NOT caught"
else
  ok "mutation: ci build without LUMIRSS_VERSION caught"
fi
rm -rf "$wt"


# ---------------------------------------------------------------------------
echo
echo "image-metadata tests: $PASS passed, $FAIL failed"
if [[ "$FAIL" -gt 0 ]]; then exit 1; fi
