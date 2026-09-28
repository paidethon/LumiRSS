#!/usr/bin/env bash
# FIX-377: rebuild a release SHA256SUMS that covers EVERY file in a staging
# directory — the actual upload set — instead of a hardcoded subset.
#
# The GitHub Release for a tag can carry more than this workflow's manifest:
# the maintainer attaches the offline image archive produced by
# './lumirss export-images' (lumirss-images-<tag>.tar). A sums file that
# enumerates only release-manifest.json silently leaves that multi-GB
# attachment unverifiable (and the old --clobber even DESTROYED the archive's
# own checksum entry). Rule: whatever is on the release, SHA256SUMS names it.
#
# Usage: release-sums.sh <staging-dir>
#   Writes <staging-dir>/SHA256SUMS covering every regular file directly in
#   <staging-dir> (SHA256SUMS itself excluded). Deterministic: C-locale
#   sorted names, so identical inputs produce byte-identical output.
#   Verify on the target host with: sha256sum -c SHA256SUMS
set -euo pipefail

dir="${1:?usage: release-sums.sh <staging-dir>}"
if [[ ! -d "$dir" ]]; then
  echo "release-sums: not a directory: $dir" >&2
  exit 1
fi

mapfile -t files < <(find "$dir" -maxdepth 1 -type f ! -name SHA256SUMS \
  -printf '%f\n' | LC_ALL=C sort)
if [[ "${#files[@]}" -eq 0 ]]; then
  echo "release-sums: no assets to checksum in $dir" >&2
  exit 1
fi

# cd so sha256sum prints plain relative names (the release-asset names);
# xargs -d '\n' keeps names with spaces intact, order = the sorted list.
(
  cd "$dir"
  printf '%s\n' "${files[@]}" | xargs -d '\n' sha256sum
) > "$dir/SHA256SUMS"

# Self-check: the sums file must have exactly one line per asset — a
# truncated write here would ship a silently incomplete checksum file.
lines="$(wc -l < "$dir/SHA256SUMS")"
if [[ "$lines" -ne "${#files[@]}" ]]; then
  echo "release-sums: expected ${#files[@]} entries, wrote $lines" >&2
  exit 1
fi
echo "release-sums: $lines asset(s) covered in $dir/SHA256SUMS"
