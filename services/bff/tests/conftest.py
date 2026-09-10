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
