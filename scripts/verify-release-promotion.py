#!/usr/bin/env python3
"""FIX-378 promotion identity: a tagged release may only promote the
candidate that was actually built from the tag's commit.

'./lumirss export-images' can rebuild images anywhere; a rebuilt artifact is
NOT the same package unless every recorded identity matches. Before
publish-images.yml attaches a manifest to the tag's GitHub Release, this
script verifies, from the manifest FIX-373 generates (git_sha + digest-pinned
image references — the same identities the OCI labels carry at build time):

  1. manifest schema is lumirss-release-manifest/v1;
  2. tag commit == expected (tested) SHA — the checkout CI pinned and the
     image builds received as LUMIRSS_COMMIT / VITE_GIT_COMMIT;
  3. manifest.git_sha == that same SHA — the manifest promotes THIS build;
  4. manifest.version == the tag's version (VERSION file of the tested tree);
  5. both image references are digest-pinned (immutable @sha256:...) and the
     digests equal the ones THIS run's build steps actually pushed.

Any mismatch -> exit 1; the tag never gets a manifest describing a different
build. Deterministic, stdlib only; publish-images.yml + tests/deploy call it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SHA256 = "sha256:"
_DIGEST_LEN = 64  # sha256 hex digits after the prefix


def _fail(failures: list[str], what: str) -> None:
    failures.append(what)


def verify_promotion(
    manifest_path: Path,
    tag_commit: str,
    expected_sha: str,
    expected_version: str,
    bff_digest: str,
    web_digest: str,
) -> list[str]:
    failures: list[str] = []

    def _is_digest(value: str) -> bool:
        return (
            value.startswith(_SHA256)
            and len(value) == len(_SHA256) + _DIGEST_LEN
            and all(c in "0123456789abcdef" for c in value[len(_SHA256):])
        )

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"manifest unreadable: {exc}"]

    if manifest.get("schema") != "lumirss-release-manifest/v1":
        _fail(failures, f"unexpected manifest schema: {manifest.get('schema')!r}")

    # The commit the tag points at must be the commit CI tested and the
    # builds received — a rebuilt/moved tag can never pass here.
    if tag_commit != expected_sha:
        _fail(
            failures,
            f"tag commit {tag_commit} != tested SHA {expected_sha} "
            "(the tag does not point at the commit that was built)",
        )
    if manifest.get("git_sha") != expected_sha:
        _fail(
            failures,
            f"manifest git_sha {manifest.get('git_sha')!r} != tested SHA "
            f"{expected_sha} (manifest does not describe THIS build)",
        )
    if manifest.get("version") != expected_version:
        _fail(
            failures,
            f"manifest version {manifest.get('version')!r} != expected "
            f"{expected_version!r}",
        )

    images = manifest.get("images") or {}
    for role, digest in (("bff", bff_digest), ("web", web_digest)):
        ref = images.get(role, "")
        if not _is_digest(digest):
            _fail(failures, f"{role} digest from the build is not a sha256 digest: {digest!r}")
            continue
        expected_ref = f"@{digest}"
        if not ref.endswith(expected_ref):
            _fail(
                failures,
                f"manifest image {role}={ref!r} is not digest-pinned to the "
                f"pushed digest @{digest} — a mutable tag must never be promoted",
            )

    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify release promotion identity (FIX-378)")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--tag-commit", required=True, help="git rev-parse of the tag's commit")
    parser.add_argument("--expected-sha", required=True, help="tested SHA the builds received")
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--bff-digest", required=True)
    parser.add_argument("--web-digest", required=True)
    args = parser.parse_args()

    failures = verify_promotion(
        args.manifest,
        args.tag_commit,
        args.expected_sha,
        args.expected_version,
        args.bff_digest,
        args.web_digest,
    )
    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        return 1
    print(
        f"promotion identity ok: tag commit == tested SHA == manifest git_sha "
        f"({args.expected_sha[:12]}); v{args.expected_version}; "
        "bff+web digest-pinned to this run's pushes"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
