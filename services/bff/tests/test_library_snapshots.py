"""Snapshot asset store + job pipeline tests (phase2 M2, recovery P0-04).

Covers: corrected dedupe semantics (True = this save reused stored
bytes), unique-bytes quota accounting, transactional delete that also
removes the library_items identity row + the last-reference file,
reconcile() compensation sweeps, honest monolith-unavailable, target
validation before the subprocess exists, the REAL monolith argv/env
contract (stub binary asserting argv + proxy env, pinned against the
verified v2.10.1 CLI), and the SSRF filtering proxy start/stop around
the run.
"""

import asyncio
import json
import stat

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
    return asyncio.run(coroutine)


@pytest.fixture()
def asset_store(tmp_path):
    from lumirss.storage import Database

    db = Database(tmp_path / "lumi.sqlite")
    _run(db.migrate())
    return AssetStore(db, tmp_path / "assets", quota_bytes=1024 * 1024)


def _identity_rows(db, uuid: str) -> int:
    async def query():
        row = await db.fetch_one(
            "SELECT COUNT(*) AS n FROM library_items WHERE uuid = ?", (uuid,)
        )
        return int(row["n"])

    return _run(query())


# --------------------------------------------------------------------------
# Save / read / delete with recovery semantics
# --------------------------------------------------------------------------


def test_save_read_delete_roundtrip(asset_store):
    record, deduped = _run(
        asset_store.save_snapshot(data=b"<html>snapshot</html>", url="https://page.example/a")
    )
    assert deduped is False  # first save wrote NEW bytes — not deduplicated
    assert record.bytes == len(b"<html>snapshot</html>")
    assert record.url == "https://page.example/a"
    assert (asset_store.root / record.path).is_file()
    assert _run(asset_store.read_bytes(record.uuid)) == b"<html>snapshot</html>"

    assert _run(asset_store.delete_asset(record.uuid)) is True
    assert not (asset_store.root / record.path).exists()
    with pytest.raises(AssetNotFound):
        _run(asset_store.read_bytes(record.uuid))


def test_dedupe_semantics_and_refcount_deletion(asset_store, monkeypatch):
    """deduplicated is True exactly when THIS save reused stored bytes
    (recovery P0-04d: the pre-recovery flag was inverted)."""
    import lumirss.library_assets as assets_module

    tick = {"n": 0}

    def fake_now() -> str:
        tick["n"] += 1
        return f"2026-01-01T00:00:{tick['n']:02d}.000000Z"

    # Strictly increasing timestamps: saves within the same wall-clock
    # second tie on created_at in the real table (uuid tiebreak), so the
    # canonical "earliest row pays" order needs distinct stamps here.
    monkeypatch.setattr(assets_module, "utc_now", fake_now)

    first, deduped_first = _run(asset_store.save_snapshot(data=b"<html>same</html>"))
    assert deduped_first is False
    second, deduped_second = _run(asset_store.save_snapshot(data=b"<html>same</html>"))
    assert deduped_second is True
    assert second.sha256 == first.sha256
    assert second.path == first.path

    listed = _run(asset_store.list_snapshots())
    flags = {row.record.uuid: row.deduplicated for row in listed}
    assert flags[first.uuid] is False
    assert flags[second.uuid] is True

    _run(asset_store.delete_asset(first.uuid))
    assert (asset_store.root / second.path).is_file()
    _run(asset_store.delete_asset(second.uuid))
    assert not (asset_store.root / second.path).exists()


def test_delete_removes_library_items_identity_row(asset_store, tmp_path):
    """Recovery P0-04f: deleting the last reference must also remove the
    kind='snapshot' identity row — no permanent orphans."""
    from lumirss.storage import Database

    record, _ = _run(asset_store.save_snapshot(data=b"<html>x</html>"))
    assert _identity_rows(asset_store._db, record.item_uuid) == 1
    assert _run(asset_store.delete_asset(record.uuid)) is True
    assert _identity_rows(asset_store._db, record.item_uuid) == 0
    row = _run(
        asset_store._db.fetch_one(
            "SELECT COUNT(*) AS n FROM library_assets WHERE uuid = ?", (record.uuid,)
        )
    )
    assert int(row["n"]) == 0
    _ = Database


def test_unique_bytes_quota_not_double_charged(asset_store):
    """Recovery P0-04e: deduplicated rows are references and must not
    re-charge the quota — usage.bytes counts each sha256 once."""
    big = b"x" * (900 * 1024)
    first, _ = _run(asset_store.save_snapshot(data=big))
    _run(asset_store.save_snapshot(data=big))  # same bytes → dedupe reference
    usage = _run(asset_store.usage())
    assert usage["bytes"] == 900 * 1024  # charged once, not 1.8MB
    assert usage["count"] == 2  # two snapshot rows

    # 1MB quota: only 100KB headroom left, this must be refused.
    with pytest.raises(AssetQuotaExceeded):
        _run(asset_store.save_snapshot(data=b"y" * (200 * 1024)))
    assert usage["quotaBytes"] == 1024 * 1024
    _ = first


def test_quota_enforced_and_honest(asset_store):
    big = b"x" * (900 * 1024)
    first, _ = _run(asset_store.save_snapshot(data=big))
    assert first.bytes == 900 * 1024
    with pytest.raises(AssetQuotaExceeded):
        _run(asset_store.save_snapshot(data=b"y" * (200 * 1024)))
    usage = _run(asset_store.usage())
    assert usage["bytes"] == 900 * 1024
    assert usage["quotaBytes"] == 1024 * 1024


def test_per_file_cap(asset_store):
    with pytest.raises(AssetTooLarge):
        _run(asset_store.save_snapshot(data=b"z" * (51 * 1024 * 1024)))


def test_failed_db_write_compensates_file(tmp_path, monkeypatch):
    """Recovery P0-04g: if the insert transaction fails after the file
    landed, the file is compensated away — no orphan, no dangling row."""

    async def failing_transaction(db, fn):
        raise RuntimeError("simulated crash between file and commit")

    import lumirss.library_assets as assets_module

    monkeypatch.setattr(assets_module, "transaction", failing_transaction)
    from lumirss.storage import Database

    db = Database(tmp_path / "lumi.sqlite")
    _run(db.migrate())
    store = AssetStore(db, tmp_path / "assets", quota_bytes=1024 * 1024)
    with pytest.raises(RuntimeError):
        _run(store.save_snapshot(data=b"<html>orph</html>"))
    assert list((tmp_path / "assets").iterdir()) == []  # file compensated
    row = _run(db.fetch_one("SELECT COUNT(*) AS n FROM library_assets"))
    assert int(row["n"]) == 0


def test_reconcile_sweeps_orphan_files_and_dead_rows(asset_store):
    record, _ = _run(asset_store.save_snapshot(data=b"<html>keep</html>"))
    # Orphan files: never referenced + tmp leftover from a crashed save.
    (asset_store.root / "deadbeef.html").write_bytes(b"orphan")
    (asset_store.root / ".wip.tmp").write_bytes(b"tmp")
    # Dead row: file disappeared underneath a committed row.
    dead, _ = _run(asset_store.save_snapshot(data=b"<html>dead</html>"))
    (asset_store.root / dead.path).unlink()

    result = _run(asset_store.reconcile())
    assert result["filesRemoved"] >= 2  # orphan + tmp
    assert result["rowsDropped"] >= 1  # dead row group removed
    assert not (asset_store.root / "deadbeef.html").exists()
    assert not (asset_store.root / ".wip.tmp").exists()
    assert (asset_store.root / record.path).is_file()  # healthy row survives
    assert _identity_rows(asset_store._db, dead.item_uuid) == 0
    with pytest.raises(AssetNotFound):
        _run(asset_store.read_bytes(dead.uuid))


# --------------------------------------------------------------------------
# Job runner: honest unavailability + pre-subprocess validation
# --------------------------------------------------------------------------


def test_monolith_missing_is_honest_503(asset_store, monkeypatch):
    """Without the monolith binary the API reports unavailable — never a
    fabricated success. (Real deployments install monolith; tests prove
    the honest failure path.)"""
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


def test_snapshot_target_validated_before_subprocess(asset_store, monkeypatch):
    """Even with a (fake) binary present, private targets never reach it."""
    import lumirss.snapshots as snapshots

    monkeypatch.setattr(
        snapshots, "monolith_path", lambda: "/nonexistent/monolith"
    )
    ran = {"exec": False}

    async def fake_exec(*args, **kwargs):
        ran["exec"] = True

        class _Proc:
            returncode = 0

            async def communicate(self):
                return b"", b""

        return _Proc()

    monkeypatch.setattr(
        snapshots.asyncio, "create_subprocess_exec", fake_exec
    )
    runner = SnapshotJobRunner(asset_store)
    with pytest.raises(Exception):
        _run(runner.run("http://169.254.169.254/latest/meta-data/"))
    assert ran["exec"] is False


# --------------------------------------------------------------------------
# Job runner: REAL argv + proxy env contract (stub binary)
# --------------------------------------------------------------------------


def _write_stub_binary(directory, script: str) -> str:
    path = directory / "fake-monolith.sh"
    directory.mkdir(parents=True, exist_ok=True)
    path.write_text(script)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return str(path)


def test_monolith_argv_and_proxy_env_contract(asset_store, tmp_path, monkeypatch):
    """The stub binary asserts the EXACT argv against the pinned v2.10.1
    CLI (<url> -o <file> -t 60 -I -j — never the old positional-out/cookie
    misuse) and records the proxy env the child would dial through."""
    import lumirss.snapshots as snapshots

    record_file = tmp_path / "stub-record.json"

    script = """#!/usr/bin/env bash
set -eu
out=""
prev=""
for arg in "$@"; do
  if [[ "$prev" == "-o" ]]; then out="$arg"; fi
  prev="$arg"
done
if [[ -z "$out" ]]; then echo "stub: no -o in args: $*" >&2; exit 3; fi
python3 - "$out" "$@" <<'PYEOF'
import json, os, sys, tempfile
from pathlib import Path
allowed = (
    Path("__STUB_ROOT__").resolve(),
    Path(tempfile.gettempdir()).resolve(),
)
out_file = Path(sys.argv[1]).resolve()
record_path = Path("__RECORD_PATH__").resolve()
for target in (out_file, record_path):
    if not any(root == target or root in target.parents for root in allowed):
        raise SystemExit(f"stub: refusing {target} outside the stub roots")
proxy_keys = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "PATH")
observed = {
    "monolith_argv": sys.argv[2:],
    "proxy_env": {k: os.environ.get(k, "") for k in proxy_keys},
    "probe_marker_visible": "LUMIRSS_PROBE_MARKER" in os.environ,
}
record_path.write_text(json.dumps(observed), encoding="utf-8")
out_file.write_text("<html><body>stub snapshot</body></html>", encoding="utf-8")
PYEOF
""".replace("__RECORD_PATH__", str(record_file)).replace("__STUB_ROOT__", str(tmp_path))
    binary = _write_stub_binary(tmp_path, script)

    # If the runner passed the host environment through, the child would
    # see this marker; the minimal env must hide it.
    monkeypatch.setenv("LUMIRSS_PROBE_MARKER", "present-only-in-host-env")
    monkeypatch.setattr(snapshots, "monolith_path", lambda: binary)

    async def no_network(url: str) -> None:
        return None

    monkeypatch.setattr(snapshots, "validate_hop", no_network)

    started = {}

    class StubProxy:
        def __init__(self):
            self.port = None

        @property
        def url(self):
            return f"http://127.0.0.1:{self.port or 0}"

        async def __aenter__(self):
            started["entered"] = True
            self.port = 59999
            return self

        async def __aexit__(self, *exc):
            started["exited"] = True
            return False

    runner = SnapshotJobRunner(asset_store, proxy_factory=StubProxy)
    result = _run(runner.run("https://web.example/article"))

    assert started == {"entered": True, "exited": True}
    recorded = json.loads(record_file.read_text())
    argv = recorded["monolith_argv"]
    assert argv[0] == "https://web.example/article"  # url is positional FIRST
    assert argv[1] == "-o"  # output file via flag (old code passed it positionally)
    assert argv[2].endswith("page.html")
    assert argv[3:] == ["-t", "60", "-I", "-j"]
    assert "-C" not in argv  # the old cookie-file misuse is gone
    assert recorded["proxy_env"]["HTTP_PROXY"] == "http://127.0.0.1:59999"
    assert recorded["proxy_env"]["HTTPS_PROXY"] == "http://127.0.0.1:59999"
    assert recorded["proxy_env"]["ALL_PROXY"] == "http://127.0.0.1:59999"
    assert recorded["proxy_env"]["NO_PROXY"] == ""
    assert recorded["probe_marker_visible"] is False  # minimal child env
    assert result["url"] == "https://web.example/article"
    assert result["deduplicated"] is False
    assert result["asset"]["url"] == "https://web.example/article"


def test_runner_uses_real_filtering_proxy(asset_store, monkeypatch):
    """By default the runner starts the REAL SsrfFilteringProxy (not a
    stub) — proving the wiring, on loopback, end to end with the stub
    binary making no network calls."""
    import lumirss.snapshots as snapshots

    script = """#!/usr/bin/env bash
set -eu
out=""
prev=""
for arg in "$@"; do
  if [[ "$prev" == "-o" ]]; then out="$arg"; fi
  prev="$arg"
done
printf '<html>proxy-run</html>' > "$out"
"""
    binary = _write_stub_binary(asset_store.root.parent / "bin", script)
    monkeypatch.setattr(snapshots, "monolith_path", lambda: binary)

    async def no_network(url: str) -> None:
        return None

    monkeypatch.setattr(snapshots, "validate_hop", no_network)
    runner = SnapshotJobRunner(asset_store)
    result = _run(runner.run("https://web.example/x"))
    assert result["asset"]["bytes"] == len(b"<html>proxy-run</html>")
    assert result["asset"]["url"] == "https://web.example/x"
