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
def _reset_rate_limit_windows() -> None:
    """0021 rate limits are process-global fixed windows; tests must not
    inherit (or leak into) each other's counters."""
    import lumirss.middleware as middleware

    middleware._rate_windows.clear()
