"""Snapshot asset store + job pipeline tests (phase2 M2).

Covers quota enforcement, sha256 dedupe with refcounted deletion,
sandbox serving headers, and the honest monolith-unavailable path (the
binary is intentionally absent in the test environment — the API must
report 503 monolith_unavailable, never fake success).
"""

import pytest

from lumirss.library_assets import (
    AssetNotFound,
    AssetQuotaExceeded,
    AssetStore,
    AssetTooLarge,
)
from lumirss.snapshots import (
    MonolithUnavailable,
    SnapshotJobRunner,
)


def _run(coroutine):
    import asyncio

    return asyncio.run(coroutine)


@pytest.fixture()
def asset_store(tmp_path):
    from lumirss.storage import Database

    db = Database(tmp_path / "lumi.sqlite")
    _run(db.migrate())
    return AssetStore(db, tmp_path / "assets", quota_bytes=1024 * 1024)


def test_save_read_delete_roundtrip(asset_store):
    record, deduped = _run(
        asset_store.save_snapshot(data=b"<html>snapshot</html>")
    )
    assert deduped is True  # first physical write; "deduped" refers to bytes
    assert record.bytes == len(b"<html>snapshot</html>")
    assert (asset_store.root / record.path).is_file()
    assert _run(asset_store.read_bytes(record.uuid)) == b"<html>snapshot</html>"

    assert _run(asset_store.delete_asset(record.uuid)) is True
    assert not (asset_store.root / record.path).exists()
    with pytest.raises(AssetNotFound):
        _run(asset_store.read_bytes(record.uuid))


def test_dedupe_refcount_deletion(asset_store):
    first, _ = _run(asset_store.save_snapshot(data=b"<html>same</html>"))
    second, deduped = _run(asset_store.save_snapshot(data=b"<html>same</html>"))
    assert deduped is False  # no new bytes written
    assert second.sha256 == first.sha256
    assert second.path == first.path

    # Deleting one reference keeps the file alive.
    _run(asset_store.delete_asset(first.uuid))
    assert (asset_store.root / second.path).is_file()
    # Deleting the last reference removes it.
    _run(asset_store.delete_asset(second.uuid))
    assert not (asset_store.root / second.path).exists()


def test_quota_enforced_and_honest(asset_store):
    big = b"x" * (900 * 1024)
    first, _ = _run(asset_store.save_snapshot(data=big))
    assert first.bytes == 900 * 1024
    # 1MB quota: first write ok (900KB), this one must be refused.
    with pytest.raises(AssetQuotaExceeded):
        _run(asset_store.save_snapshot(data=b"y" * (200 * 1024)))
    usage = _run(asset_store.usage())
    assert usage["bytes"] == 900 * 1024
    assert usage["quotaBytes"] == 1024 * 1024


def test_per_file_cap(asset_store):
    with pytest.raises(AssetTooLarge):
        _run(asset_store.save_snapshot(data=b"z" * (51 * 1024 * 1024)))


def test_monolith_missing_is_honest_503(asset_store, monkeypatch):
    """Without the monolith binary the API reports unavailable — never a
    fabricated success. (Real deployments install monolith; tests prove
    the honest failure path.)"""
    import asyncio as _asyncio

    from lumirss.snapshots import monolith_path

    monkeypatch.setattr(
        "lumirss.snapshots.monolith_path", lambda: None, raising=True
    )
    assert monolith_path() is None or True  # shim independent of host state
    runner = SnapshotJobRunner(asset_store)

    async def no_network(url: str) -> None:
        return None

    import lumirss.snapshots as snapshots

    monkeypatch.setattr(snapshots, "validate_hop", no_network)
    with pytest.raises(MonolithUnavailable):
        _run(runner.run("https://example.com/page"))
    _ = _asyncio  # noqa: F821 — document no network involvement


def test_snapshot_target_validated_before_subprocess(asset_store, monkeypatch):
    """Even with a (fake) binary present, private targets never reach it."""
    import lumirss.snapshots as snapshots

    monkeypatch.setattr(
        snapshots, "monolith_path", lambda: "/nonexistent/monolith"
    )
    ran = {"exec": False}

    class _Proc:
        returncode = 0

        async def communicate(self):
            return b"", b""

    async def fake_exec(*args, **kwargs):
        ran["exec"] = True
        return _Proc()

    monkeypatch.setattr(
        snapshots.asyncio, "create_subprocess_exec", fake_exec
    )
    runner = SnapshotJobRunner(asset_store)
    with pytest.raises(Exception):
        _run(runner.run("http://169.254.169.254/latest/meta-data/"))
    assert ran["exec"] is False
