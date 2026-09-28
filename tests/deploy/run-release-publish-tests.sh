#!/usr/bin/env bash
# Release-publishing tests (no registry, no docker required):
#   - FIX-374: the deploy entry point stays executable in a freshly unpacked
#     release tree — the packaging path (git archive = what GitHub serves for
#     tag source tarballs) must preserve exec bits without relying on any
#     developer machine's chmod history
#   - FIX-377: the release SHA256SUMS enumerates the ACTUAL upload set
#     (scripts/release-sums.sh), never a hardcoded subset
#   - FIX-378: promotion identity — tag commit == built SHA == pushed digests
#     (scripts/verify-release-promotion.py)
#   - FIX-379: a half-finished release cannot end green — required assets are
#     asserted against server truth (scripts/check-release-assets.py)
#   - FIX-390: pipes into tail/head never swallow a failure
#     (scripts/check-pipefail.py)
# Run from anywhere: tests/deploy/run-release-publish-tests.sh
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PASS=0
FAIL=0

ok()  { printf '  ok   %s\n' "$1"; PASS=$((PASS + 1)); }
bad() { printf '  FAIL %s\n' "$1"; FAIL=$((FAIL + 1)); }

assert_eq() { # desc expected actual
  if [[ "$2" == "$3" ]]; then ok "$1"; else bad "$1 — expected [$2] got [$3]"; fi
}

# ---------------------------------------------------------------------------
echo "== 1. FIX-374: exec bits survive the release packaging path =="
# Operators get the deploy entry from source: git clone, or the tag source
# tarball (git archive semantics). Git tracks the exec bit, but a staging
# step that round-trips through a mode-less format (zip semantics) drops it
# and `sudo ./lumirss deploy` dies with "Permission denied" on a fresh
# machine. Pin both halves: (a) every git-100755 file is executable in a
# fresh `git archive` extraction, (b) the deploy-critical set is 100755 IN
# GIT so the mode cannot silently regress.
unpack_release_tree() { # -> dir   (same pipeline as a tag source tarball)
  local dst; dst="$(mktemp -d "${TMPDIR:-/tmp}/lumirss-reltree.XXXXXX")"
  git -C "$REPO_ROOT" archive --format=tar HEAD | tar -xf - -C "$dst"
  printf '%s\n' "$dst"
}

check_exec_tree() { # dir -> 0 if every git-100755 file is executable there
  local dir="$1" entry rc=0
  while IFS= read -r entry; do
    if [[ ! -x "$dir/$entry" ]]; then
      printf '    not executable in packaged tree: %s\n' "$entry" >&2
      rc=1
    fi
  done < <(git -C "$REPO_ROOT" ls-files -s | awk '$1=="100755" {print $4}')
  return "$rc"
}

# (a) behavior: fresh tarball extraction → every tracked-exec file executes
tree="$(unpack_release_tree)"
if out="$(check_exec_tree "$tree" 2>&1)"; then
  ok "git archive extraction keeps exec bits on all tracked-exec files"
else
  bad "packaged tree lost exec bits: $out"
fi
if (cd "$tree" && ./lumirss --help >/dev/null 2>&1); then
  ok "fresh unpack: ./lumirss --help runs (deploy entry executable)"
else
  bad "fresh unpack: ./lumirss is not runnable (exec bit / shebang lost)"
fi
synrx=0
while IFS= read -r sh; do
  if ! bash -n "$tree/$sh" 2>/dev/null; then
    bad "syntax error in packaged script: $sh"
    synrx=1
  fi
done < <(cd "$tree" && find . -name '*.sh' -type f | sed 's#^\./##'; printf 'lumirss\n')
[[ "$synrx" -eq 0 ]] && ok "all packaged shell scripts parse (bash -n)"
rm -rf "$tree"

# (a') self-test of the assertion: a staging path that strips modes (zip
# semantics) MUST be caught by check_exec_tree.
tree="$(unpack_release_tree)"
find "$tree" -type f -exec chmod a-x {} +
if check_exec_tree "$tree" >/dev/null 2>&1; then
  bad "self-test: mode-stripped staging (zip semantics) NOT caught"
else
  ok "self-test: mode-stripped staging (zip semantics) is caught"
fi
rm -rf "$tree"

# (b) static pin: the deploy-critical entry points must be 100755 in git,
# independently of what the current worktree looks like.
critical_755="$(git -C "$REPO_ROOT" ls-files -s lumirss scripts/freshrss_pool.sh \
  | awk '$1=="100755" {print $4}' | sort)"
expected_755="$(printf 'lumirss\nscripts/freshrss_pool.sh\n' | sort)"
assert_eq "deploy-critical files are 100755 in git (mode cannot regress)" \
  "$expected_755" "$critical_755"

# ---------------------------------------------------------------------------
echo "== 2. FIX-377: SHA256SUMS enumerates the actual upload set =="
# A release carries more than the workflow's manifest: the maintainer may
# attach the offline image archive (lumirss-images-<tag>.tar from
# './lumirss export-images'). The sums file must name EVERY attachment,
# whichever publish path landed last — never a hardcoded subset.
sums="$REPO_ROOT/scripts/release-sums.sh"
[[ -x "$sums" ]] && ok "scripts/release-sums.sh exists and is executable" \
  || bad "scripts/release-sums.sh missing or not executable"

stage="$(mktemp -d "${TMPDIR:-/tmp}/lumirss-sums.XXXXXX")"
printf 'fake-tar\n'      > "$stage/lumirss-images-v2.0.1.tar"
printf 'fake-manifest\n' > "$stage/release-manifest.json"
printf 'notepad\nname with spaces.txt\n' > "$stage/name with spaces.txt"
if out="$("$sums" "$stage")"; then
  ok "release-sums runs over a mixed asset set ($out)"
else
  bad "release-sums failed: $out"
fi
n_assets="$(find "$stage" -maxdepth 1 -type f ! -name SHA256SUMS | wc -l)"
n_lines="$(wc -l < "$stage/SHA256SUMS")"
assert_eq "SHA256SUMS has one entry per asset (tar+manifest+spacey name)" "3" "$n_lines"
[[ "$n_assets" -eq "$n_lines" ]]
if (cd "$stage" && sha256sum -c SHA256SUMS >/dev/null 2>&1); then
  ok "sha256sum -c passes over the regenerated sums"
else
  bad "regenerated SHA256SUMS does not verify"
fi
if grep -q "lumirss-images-v2.0.1.tar" "$stage/SHA256SUMS" \
  && grep -q "name with spaces.txt" "$stage/SHA256SUMS"; then
  ok "offline image archive + spacey names are covered (not a hardcoded subset)"
else
  bad "SHA256SUMS missed an asset in the staging dir"
fi
cp "$stage/SHA256SUMS" "$stage.sums1"
"$sums" "$stage" >/dev/null
if cmp -s "$stage/SHA256SUMS" "$stage.sums1"; then
  ok "regeneration is deterministic (byte-identical)"
else
  bad "SHA256SUMS regeneration is not deterministic"
fi
if grep -qE '(^| )SHA256SUMS$' "$stage/SHA256SUMS"; then
  bad "SHA256SUMS includes itself"
else
  ok "SHA256SUMS excludes itself"
fi
mkdir -p "$stage-empty"
if "$sums" "$stage-empty" >/dev/null 2>&1; then
  bad "release-sums accepted an empty staging dir (would ship empty sums)"
else
  ok "release-sums refuses an empty staging dir"
fi
# Simulate the OLD clobber bug as a regression guard: a manifest-only sums
# over a set that also carries the offline archive still "verifies" clean —
# the incompleteness is invisible to sha256sum -c and only shows up when
# enumerating the actual dir (which is exactly what release-sums.sh does).
printf 'fake-manifest\n' > "$stage/release-manifest.json"
( cd "$stage" && sha256sum release-manifest.json > SHA256SUMS )
manifest_only_verifies=0
( cd "$stage" && sha256sum -c SHA256SUMS >/dev/null 2>&1 ) && manifest_only_verifies=1
n_assets="$(find "$stage" -maxdepth 1 -type f ! -name SHA256SUMS | wc -l)"
n_lines="$(wc -l < "$stage/SHA256SUMS")"
if [[ "$manifest_only_verifies" -eq 1 && "$n_lines" -lt "$n_assets" ]]; then
  ok "regression simulation: manifest-only sums verifies clean yet under-covers (the FIX-377 bug)"
else
  bad "regression simulation did not reproduce the incomplete-sums state"
fi
"$sums" "$stage" >/dev/null   # restore the complete sums
rm -rf "$stage" "$stage.sums1" "$stage-empty"

# Workflow wiring: the attach step must consume the release's existing
# assets (statically pinned in scripts/check-image-metadata.py, mutation-
# tested in tests/deploy/run-image-metadata-tests.sh).
grep -q "gh release download" "$REPO_ROOT/.github/workflows/publish-images.yml" \
  && ok "publish-images.yml downloads existing release assets before regenerating sums" \
  || bad "publish-images.yml attach step does not pull existing assets into the checksum set"

# ---------------------------------------------------------------------------
echo "== 3. FIX-378: promotion identity (tag commit == built SHA == digests) =="
# A prebuilt candidate may only be promoted under its own identity: the tag
# must point at the commit CI tested, the manifest must describe THAT build,
# and both image references must be digest-pinned to the digests the publish
# run actually pushed. A rebuild is never silently "the same package".
promo="$REPO_ROOT/scripts/verify-release-promotion.py"
[[ -x "$promo" ]] && ok "scripts/verify-release-promotion.py exists and is executable" \
  || bad "scripts/verify-release-promotion.py missing or not executable"

SHA="0123456789abcdef0123456789abcdef01234567"
BD="sha256:$(printf '1%.0s' $(seq 64))"
WD="sha256:$(printf '2%.0s' $(seq 64))"
pstage="$(mktemp -d "${TMPDIR:-/tmp}/lumirss-promo.XXXXXX")"
cat > "$pstage/manifest.json" <<JSON
{
  "schema": "lumirss-release-manifest/v1",
  "name": "LumiRSS",
  "version": "2.0.1",
  "git_sha": "$SHA",
  "images": {
    "bff": "ghcr.io/paidethon/lumirss/lumirss-bff@$BD",
    "web": "ghcr.io/paidethon/lumirss/lumirss-web@$WD"
  }
}
JSON
promo_ok() { # args passthrough -> 0 expected
  "$promo" "$@" >/dev/null 2>&1
}
if promo_ok --manifest "$pstage/manifest.json" --tag-commit "$SHA" --expected-sha "$SHA" \
  --expected-version 2.0.1 --bff-digest "$BD" --web-digest "$WD"; then
  ok "matching tag/build/manifest/digests promotes"
else
  bad "promotion verifier rejected a consistent candidate"
fi
promo_bad() { # desc args...
  local desc="$1"; shift
  if promo_ok "$@"; then bad "promotion accepted: $desc"; else ok "promotion rejected: $desc"; fi
}
promo_bad "manifest rebuilt from a different commit" \
  --manifest <(sed "s/$SHA/ffffffffffffffffffffffffffffffffffffffff/" "$pstage/manifest.json") \
  --tag-commit "$SHA" --expected-sha "$SHA" --expected-version 2.0.1 \
  --bff-digest "$BD" --web-digest "$WD"
promo_bad "tag moved off the built commit" \
  --manifest "$pstage/manifest.json" --tag-commit "ffffffffffffffffffffffffffffffffffffffff" \
  --expected-sha "$SHA" --expected-version 2.0.1 --bff-digest "$BD" --web-digest "$WD"
promo_bad "version drift" \
  --manifest "$pstage/manifest.json" --tag-commit "$SHA" --expected-sha "$SHA" \
  --expected-version 9.9.9 --bff-digest "$BD" --web-digest "$WD"
promo_bad "bff digest mismatch (rebuilt image)" \
  --manifest "$pstage/manifest.json" --tag-commit "$SHA" --expected-sha "$SHA" \
  --expected-version 2.0.1 --bff-digest "sha256:$(printf '3%.0s' $(seq 64))" --web-digest "$WD"
promo_bad "mutable-tag reference instead of a digest pin" \
  --manifest <(sed "s/@$BD/@v2.0.1/" "$pstage/manifest.json") \
  --tag-commit "$SHA" --expected-sha "$SHA" --expected-version 2.0.1 \
  --bff-digest "$BD" --web-digest "$WD"
rm -rf "$pstage"

# ---------------------------------------------------------------------------
echo "== 4. FIX-379: required release assets asserted before green =="
chk="$REPO_ROOT/scripts/check-release-assets.py"
[[ -x "$chk" ]] && ok "scripts/check-release-assets.py exists and is executable" \
  || bad "scripts/check-release-assets.py missing or not executable"

astage="$(mktemp -d "${TMPDIR:-/tmp}/lumirss-assets.XXXXXX")"
assets_ok() { # manifest tar sums...
  local sums="$1"; shift
  "$chk" --assets-json "$astage/assets.json" --sums "$sums" \
    --required release-manifest.json SHA256SUMS >/dev/null 2>&1
}
mk_assets() { # manifest? sums?  (control what the "server" has; ".fake" suffix stripped for the asset name)
  rm -f "$astage"/*.fake
  [[ "${1:-}" == 1 ]] && printf 'manifest\n' > "$astage/release-manifest.json.fake"
  [[ "${2:-}" == 1 ]] && printf 'sums\n'    > "$astage/SHA256SUMS.fake"
  python3 - "$astage" <<'PY'
import json, sys, pathlib
stage = pathlib.Path(sys.argv[1])
assets = [{"name": p.name[:-len(".fake")], "size": p.stat().st_size}
          for p in sorted(stage.glob("*.fake"))]
(stage / "assets.json").write_text(json.dumps({"assets": assets}))
PY
}
printf 'manifest\n' > "$astage/release-manifest.json"
printf '%s  release-manifest.json\n%s  SHA256SUMS\n' \
  "$(printf 'a%.0s' $(seq 64))" "$(printf 'b%.0s' $(seq 64))" > "$astage/SHA256SUMS"

mk_assets 1 1
if assets_ok "$astage/SHA256SUMS"; then
  ok "complete release (manifest+sums, sized) passes"
else
  bad "asset checker rejected a complete release"
fi
mk_assets 1 0
if assets_ok "$astage/SHA256SUMS"; then
  bad "missing SHA256SUMS asset NOT caught (half-finished release would end green)"
else
  ok "missing SHA256SUMS asset caught"
fi
mk_assets 0 1
if assets_ok "$astage/SHA256SUMS"; then
  bad "missing release-manifest.json NOT caught"
else
  ok "missing release-manifest.json caught"
fi
# zero-size upload = failure, not an asset
mk_assets 1 1
python3 - "$astage" <<'PY'
import json, sys, pathlib
stage = pathlib.Path(sys.argv[1])
data = json.loads((stage / "assets.json").read_text())
for a in data["assets"]:
    if a["name"] == "SHA256SUMS":
        a["size"] = 0
(stage / "assets.json").write_text(json.dumps(data))
PY
if assets_ok "$astage/SHA256SUMS"; then
  bad "zero-size asset treated as present"
else
  ok "zero-size asset caught"
fi
# sums <-> assets must match both ways (FIX-377 contract at attach time)
mk_assets 1 1
printf '%s  release-manifest.json\n%s  GONE.tar\n' \
  "$(printf 'a%.0s' $(seq 64))" "$(printf 'c%.0s' $(seq 64))" > "$astage/SHA256SUMS"
if assets_ok "$astage/SHA256SUMS"; then
  bad "sums naming a non-asset NOT caught"
else
  ok "sums naming a phantom file caught"
fi
mk_assets 1 1
printf '%s  release-manifest.json\n' "$(printf 'a%.0s' $(seq 64))" > "$astage/SHA256SUMS"
if assets_ok "$astage/SHA256SUMS"; then
  bad "asset without a sums entry NOT caught"
else
  ok "asset without a checksum entry caught"
fi
rm -rf "$astage"

# ---------------------------------------------------------------------------
echo "== 5. FIX-390: pipes into tail/head never swallow a failure =="
# `cmd | tail -1` returns TAIL's exit status; a failed cmd is invisible.
# The repo invariant: every tail/head pipe sits in a pipefail-declared scope.
guard="$REPO_ROOT/scripts/check-pipefail.py"
[[ -f "$guard" ]] && ok "scripts/check-pipefail.py exists" \
  || bad "scripts/check-pipefail.py missing"
if out="$(python3 "$guard" 2>&1)"; then
  ok "real tree passes the pipe-hygiene guard ($out)"
else
  bad "pipe-hygiene guard failed on the real tree: $out"
fi

# Mutations on a scratch root: the guard must bite exactly on unguarded pipes.
mroot="$(mktemp -d "${TMPDIR:-/tmp}/lumirss-pipe.XXXXXX")"
mkdir -p "$mroot/.github/workflows" "$mroot/scripts"
run_mutation() { # desc expected_exit fixture-fn args...
  local desc="$1" want="$2"; shift 2
  "$@"
  python3 "$guard" --root "$mroot" >/dev/null 2>&1
  local got=$?
  assert_eq "$desc" "$want" "$got"
}
mk_wf()  { printf 'name: X\non: [push]\njobs:\n  j:\n    steps:\n      - name: s\n        run: |\n%s\n' "$1" > "$mroot/.github/workflows/w.yml"; }
mk_sh()  { printf '%s\n' "$1" > "$mroot/scripts/s.sh"; }

run_mutation "workflow: unguarded 'foo | tail -1' is caught" 1 \
  mk_wf $'          foo | tail -1'
run_mutation "workflow: pipefail-declared step passes" 0 \
  mk_wf $'          set -euo pipefail\n          foo | tail -1'
run_mutation "script: tail pipe without pipefail is caught" 1 \
  mk_sh $'#!/usr/bin/env bash\nfoo | tail -1'
run_mutation "script: pipefail-declared script passes" 0 \
  mk_sh $'#!/usr/bin/env bash\nset -uo pipefail\nfoo | tail -1'
run_mutation "workflow: 'logs --tail' flag is not a pipe" 0 \
  mk_wf '          docker compose logs --tail 40'
rm -rf "$mroot"

# ---------------------------------------------------------------------------
echo
echo "release-publish tests: $PASS passed, $FAIL failed"
if [[ "$FAIL" -gt 0 ]]; then exit 1; fi
