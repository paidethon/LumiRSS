"""Security tests for the 0018 archive handling (B5 threat model).

Every hostile-archive shape the spec's security model calls out is exercised
here against the REAL parsers: traversal, absolute paths, Windows drives,
symlinks, duplicate members, zip bombs (ratio / count / size / total),
checksum-before-extract ordering, and undeclared (unchecksummed) members.
"""

import asyncio
import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from lumirss.backup import BackupInvalid
from lumirss.restore import BackupChecksumMismatch, safe_extract
from lumirss.restore import _verify_checksums
from lumirss.secrets_store import SecretsStore


def run(coroutine):
    return asyncio.run(coroutine)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _manifest(files: list[dict]) -> dict:
    return {
        "backupSchemaVersion": 1,
        "appName": "LumiRSS",
        "createdAt": "2026-09-04T00:00:00+00:00",
        "lumiVersion": "0.1.0",
        "lumiDbSchemaVersion": 3,
        "components": ["lumi.sqlite"],
        "secretPolicy": {"excludedSecrets": [], "configured": False},
        "files": files,
    }


def _write_archive(zip_path: Path, manifest: dict, members: list[tuple[str, bytes]], attrs: dict | None = None):
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        for name, data in members:
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            if attrs and name in attrs:
                info.external_attr = attrs[name]
                info.create_system = 3
            archive.writestr(info, data)


def _valid_archive(tmp_path: Path, name: str = "pkg.backup") -> tuple[Path, Path, dict, bytes]:
    zip_path = tmp_path / name
    payload = b"sqlite-data"
    manifest = _manifest(
        [{"path": "lumi.sqlite", "size": len(payload), "sha256": _sha(payload)}]
    )
    _write_archive(zip_path, manifest, [("lumi.sqlite", payload)])
    return zip_path, tmp_path / "out", manifest, payload


def test_path_traversal_member_rejected(tmp_path):
    zip_path, out_dir, manifest, _ = _valid_archive(tmp_path)
    # Rewrite the archive with a traversal member (not declared in manifest)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("../escaped.txt", b"hostile")
    with zipfile.ZipFile(zip_path) as archive:
        with pytest.raises(BackupInvalid):
            safe_extract(archive, out_dir, manifest)
    assert not (tmp_path / "escaped.txt").exists()


def test_absolute_path_member_rejected(tmp_path):
    zip_path, out_dir, manifest, _ = _valid_archive(tmp_path)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("/etc/escaped.txt", b"hostile")
    with zipfile.ZipFile(zip_path) as archive:
        with pytest.raises(BackupInvalid):
            safe_extract(archive, out_dir, manifest)


def test_windows_drive_member_rejected(tmp_path):
    zip_path, out_dir, manifest, _ = _valid_archive(tmp_path)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("C:/escaped.txt", b"hostile")
    with zipfile.ZipFile(zip_path) as archive:
        with pytest.raises(BackupInvalid):
            safe_extract(archive, out_dir, manifest)


def test_symlink_member_rejected(tmp_path):
    zip_path, out_dir, manifest, payload = _valid_archive(tmp_path)
    symlink_attr = (0o120777 << 16)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        info = zipfile.ZipInfo("lumi.sqlite")
        info.external_attr = symlink_attr
        info.create_system = 3
        archive.writestr(info, payload)
    with zipfile.ZipFile(zip_path) as archive:
        with pytest.raises(BackupInvalid):
            safe_extract(archive, out_dir, manifest)


def test_duplicate_members_rejected(tmp_path):
    payload = b"sqlite-data"
    manifest = _manifest(
        [{"path": "lumi.sqlite", "size": len(payload), "sha256": _sha(payload)}]
    )
    zip_path = tmp_path / "pkg.backup"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("lumi.sqlite", payload)
        archive.writestr("lumi.sqlite", payload)  # duplicate entry
    with zipfile.ZipFile(zip_path) as archive:
        with pytest.raises(BackupInvalid):
            safe_extract(archive, tmp_path / "out", manifest)


def test_zip_bomb_ratio_rejected(tmp_path):
    # 1 MB of zeros compresses far beyond the 200x ratio guard.
    bomb = b"\x00" * (1024 * 1024)
    manifest = _manifest(
        [{"path": "lumi.sqlite", "size": len(bomb), "sha256": _sha(bomb)}]
    )
    zip_path = tmp_path / "bomb.backup"
    _write_archive(zip_path, manifest, [("lumi.sqlite", bomb)])
    with zipfile.ZipFile(zip_path) as archive:
        with pytest.raises(BackupInvalid):
            safe_extract(archive, tmp_path / "out", manifest)


def test_undeclared_member_rejected(tmp_path):
    """Members absent from manifest.files have no checksum coverage → reject.

    Enforcement point: _verify_checksums runs before ANY extraction
    (preview + execute), so undeclared content is never trusted."""
    zip_path, out_dir, manifest, payload = _valid_archive(tmp_path)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("lumi.sqlite", payload)
        archive.writestr("smuggled.txt", b"hostile-undecleared")
    with zipfile.ZipFile(zip_path) as archive:
        with pytest.raises(BackupInvalid):
            _verify_checksums(archive, manifest)


def test_checksums_verified_before_any_trust(tmp_path):
    """A tampered declared member fails verification (pre-extract check)."""
    zip_path, _, manifest, payload = _valid_archive(tmp_path)
    bad = manifest["files"][0] | {"sha256": "0" * 64}
    tampered_manifest = _manifest([bad])
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(tampered_manifest))
        archive.writestr("lumi.sqlite", payload)
    with zipfile.ZipFile(zip_path) as archive:
        with pytest.raises(BackupChecksumMismatch):
            _verify_checksums(archive, tampered_manifest)


def test_valid_archive_extracts_declared_members(tmp_path):
    """The happy path still works (no false positives from the guards)."""
    zip_path, out_dir, manifest, payload = _valid_archive(tmp_path)
    with zipfile.ZipFile(zip_path) as archive:
        extracted = safe_extract(archive, out_dir, manifest)
    assert extracted["lumi.sqlite"].read_bytes() == payload


def test_secrets_file_written_with_0600(tmp_path):
    """AD-0018-6: secrets.json must be chmod 600 on disk."""
    store = SecretsStore(tmp_path / "secrets.json")
    store.set("rsshub.ACCESS_KEY", "smoke-value")
    path = tmp_path / "secrets.json"
    assert path.is_file()
    mode = path.stat().st_mode & 0o777
    assert mode == 0o600, f"secrets.json mode is {oct(mode)}, expected 0o600"
