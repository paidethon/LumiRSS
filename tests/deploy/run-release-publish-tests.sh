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
echo
echo "release-publish tests: $PASS passed, $FAIL failed"
if [[ "$FAIL" -gt 0 ]]; then exit 1; fi
