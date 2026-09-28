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
cp "$REPO_ROOT/.github/workflows/ci.yml" "$wt/.github/workflows/ci.yml"

# FIX-377/378/379: each release-publishing guard is pinned by the checker —
# removing the workflow wiring must be caught.
sed -i '/scripts\/release-sums\.sh/d' "$wt/.github/workflows/publish-images.yml"
if python3 "$wt/scripts/check-image-metadata.py" >/dev/null 2>&1; then
  bad "mutation: asset-set SHA256SUMS rebuild removed from attach NOT caught"
else
  ok "mutation: asset-set SHA256SUMS rebuild removed from attach caught"
fi
cp "$REPO_ROOT/.github/workflows/publish-images.yml" "$wt/.github/workflows/publish-images.yml"

sed -i '/scripts\/verify-release-promotion\.py/d' "$wt/.github/workflows/publish-images.yml"
if python3 "$wt/scripts/check-image-metadata.py" >/dev/null 2>&1; then
  bad "mutation: promotion identity verification removed NOT caught"
else
  ok "mutation: promotion identity verification removed caught"
fi
cp "$REPO_ROOT/.github/workflows/publish-images.yml" "$wt/.github/workflows/publish-images.yml"

sed -i '/scripts\/check-release-assets\.py/d' "$wt/.github/workflows/publish-images.yml"
if python3 "$wt/scripts/check-image-metadata.py" >/dev/null 2>&1; then
  bad "mutation: required-asset assertion removed NOT caught"
else
  ok "mutation: required-asset assertion removed caught"
fi
cp "$REPO_ROOT/.github/workflows/publish-images.yml" "$wt/.github/workflows/publish-images.yml"
# FIX-377 half-fix: keeping release-sums but dropping the download of the
# release's existing assets would silently under-cover again.
sed -i '/gh release download/d' "$wt/.github/workflows/publish-images.yml"
if python3 "$wt/scripts/check-image-metadata.py" >/dev/null 2>&1; then
  bad "mutation: existing-asset download removed from attach NOT caught"
else
  ok "mutation: existing-asset download removed from attach caught"
fi
cp "$REPO_ROOT/.github/workflows/publish-images.yml" "$wt/.github/workflows/publish-images.yml"
rm -rf "$wt"

# ---------------------------------------------------------------------------
echo "== 3. FIX-375 static: every build context is a subdirectory, never the repo root =="
# Root-level secrets (.env.prod, .lumi ledger, .git) are then structurally
# outside every build context, whatever the ignore files say.
context_paths="$(
  { grep -hoE '^\s*context: \S+' "$REPO_ROOT"/docker-compose*.yml "$REPO_ROOT"/e2e/stack/docker-compose.e2e.yml 2>/dev/null;
    grep -hoE '(docker build|context: )\S*services/bff\S*|(docker build|context: )\S*apps/web\S*' \
      "$REPO_ROOT"/.github/workflows/*.yml 2>/dev/null; } |
  sed -E 's/^\s*context: //; s/^docker build //' | sed 's/-t .*//' | sort -u
)"
echo "$context_paths" | sed 's/^/    context: /'
root_ctx="$(printf '%s\n' "$context_paths" | grep -E '^\.?/?$' || true)"
assert_eq "no build context is the repo root" "" "$root_ctx"
for ctx in $context_paths; do
  norm="${ctx#./}"
  case "$norm" in
    services/bff|apps/web|../../services/bff|../../apps/web) ;;
    *) bad "unexpected build context path: $ctx" ;;
  esac
done
ok "all build contexts resolve to apps/web or services/bff"

# ---------------------------------------------------------------------------
echo "== 4. FIX-375 behavioral: a poisoned context is really excluded =="
if docker info >/dev/null 2>&1; then
  probe_context() { # dir poison... -> build FROM scratch, list what entered
    local dir="$1"
    cat > "$dir/Dockerfile" <<'EOF'
FROM scratch
COPY . /probe
CMD ["/probe"]
EOF
    (cd "$dir" && docker build -q -t lumirss-ctx-probe . >/dev/null 2>&1)
    local cid; cid="$(docker create lumirss-ctx-probe)"
    docker export "$cid" | tar -tf - | sed 's#^probe/##' | grep -v '^$'
    docker rm "$cid" >/dev/null 2>&1
    docker rmi lumirss-ctx-probe >/dev/null 2>&1
  }

  poison_context() { # dir
    local dir="$1"; mkdir -p "$dir/sub/deep" "$dir/backups" "$dir/.work" "$dir/.git"
    printf 'LEAK=1\n'            > "$dir/.env"
    printf 'PROD-SECRET\n'       > "$dir/.env.prod"
    printf 'NESTED-SECRET\n'     > "$dir/sub/deep/.env.local"
    printf 'KEYFILE\n'           > "$dir/service-account.key"
    printf 'CERTFILE\n'          > "$dir/server.pem"
    printf 'db\n'                > "$dir/lumi.sqlite"
    printf 'wal\n'               > "$dir/lumi.sqlite-wal"
    printf 'ledger\n'            > "$dir/backups/20240101.tar.gz"
    printf 'tasks\n'             > "$dir/.work/task-bundle.tgz"
    printf 'ref: refs/heads/x\n' > "$dir/.git/HEAD"
  }

  for pair in "web:apps/web:package.json" "bff:services/bff:pyproject.toml"; do
    name="${pair%%:*}"; rest="${pair#*:}"; ctxdir="${rest%%:*}"; legit="${rest#*:}"
    sb="$(mktemp -d "${TMPDIR:-/tmp}/lumirss-ctx.XXXXXX")"
    cp "$REPO_ROOT/$ctxdir/.dockerignore" "$sb/"
    poison_context "$sb"
    printf 'legit\n' > "$sb/$legit"
    entered="$(probe_context "$sb")" || entered=""
    rm -rf "$sb"
    leaked=""
    for evil in .env .env.prod sub/deep/.env.local service-account.key server.pem \
                lumi.sqlite lumi.sqlite-wal backups/20240101.tar.gz .work/task-bundle.tgz .git/HEAD; do
      if printf '%s\n' "$entered" | grep -Fxq "$evil"; then leaked="$leaked $evil"; fi
    done
    assert_eq "$name context: none of the 10 poisoned files entered the build" "" "$leaked"
    assert_contains "$name context: legit file still builds in" "$legit" "$(printf '%s\n' "$entered")"
  done
else
  bad "docker daemon unavailable — FIX-375 behavioral context probe NOT executed"
fi

# ---------------------------------------------------------------------------
echo
echo "image-metadata tests: $PASS passed, $FAIL failed"
if [[ "$FAIL" -gt 0 ]]; then exit 1; fi
