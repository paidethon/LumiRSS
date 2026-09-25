"""Shared test isolation for the BFF suite.

Tests must be hermetic against the developer's services/bff/.env: whether a
full backup can include FreshRSS data depends on FRESHRSS_DATA_DIR, and a
developer machine that has that variable configured (with a real directory
behind it) would otherwise flip individual-pass outcomes. Tests that exercise
the FreshRSS backup path set their own fixture directory via monkeypatch,
which overrides this default.
"""

import pytest


@pytest.fixture(autouse=True)
def _hermetic_db_path(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """每个测试默认拿到独立临时 LUMIRSS_DB_PATH——不使用 client 夹具的
    测试（如直接构造 service 的单测）也不会落到开发者真实 data/ 库。
    需要自定路径的测试随后 monkeypatch 覆盖即可（后设置者生效）。"""
    import os

    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path_factory.mktemp("lumi-db") / "lumi.sqlite"))
    assert os.environ["LUMIRSS_DB_PATH"]  # keep linters honest about the import


@pytest.fixture(autouse=True)
def _isolate_freshrss_data_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FRESHRSS_DATA_DIR", "")


@pytest.fixture(autouse=True)
def _disable_search_sync(monkeypatch: pytest.MonkeyPatch) -> None:
    """0022: the background search sync must not run under TestClient —
    on a developer machine it would pull the real FreshRSS reading list
    into the per-test database and make count assertions nondeterministic."""
    monkeypatch.setenv("LUMIRSS_SEARCH_SYNC_INTERVAL", "0")


@pytest.fixture(autouse=True)
def _reset_rate_limit_windows() -> None:
    """0021 rate limits are process-global fixed windows; tests must not
    inherit (or leak into) each other's counters. The login brute-force
    counters (session auth) are isolated the same way."""
    import lumirss.middleware as middleware

    middleware._rate_windows.clear()
    middleware._login_failures.clear()


@pytest.fixture(autouse=True)
def _reset_implicit_owner_cache() -> None:
    """0067 basic mode caches the owner id per process keyed by
    id(app.state) — a module-global that would otherwise pin the FIRST
    test's owner id onto every later test's user-database/secrets
    routing (each test gets a fresh control db + users root). Clearing
    it per test keeps basic-mode request routing consistent with
    ``app.state.owner_id`` for direct store access in tests."""
    import lumirss.middleware as middleware

    middleware._implicit_owner_cache.clear()


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch):
    """A TestClient with a fresh temp Lumi database (phase2 M1 suites).

    Q-P1-10: the temp DB path must be in place BEFORE TestClient starts —
    the lifespan binds app.state.db and eagerly builds the obsidian
    service on it. Swapping app.state.db afterwards left the obsidian
    service (and anything else captured at startup) reading the
    developer's real database, so obsidian-route tests were not
    hermetic (they passed only because the real DB happened to lack the
    fixture rows)."""
    import tempfile

    from fastapi.testclient import TestClient

    from lumirss.main import app
    from lumirss.storage import Database

    tmp = tempfile.TemporaryDirectory()
    monkeypatch.setenv("LUMIRSS_DB_PATH", f"{tmp.name}/lumi.sqlite")
    try:
        with TestClient(app) as test_client:
            # Same DB the lifespan built — now provably the temp one.
            app.state.db = Database(f"{tmp.name}/lumi.sqlite")
            yield test_client
    finally:
        tmp.cleanup()
