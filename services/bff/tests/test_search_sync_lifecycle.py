"""P0-13 regression: the search sync task must not exist when disabled.

``LUMIRSS_SEARCH_SYNC_INTERVAL=0`` means "no background sync" (config
comment + tests/conftest). Before the fix the loop task was created
unconditionally and ``asyncio.sleep(0)`` turned it into a hot spin.
"""

import pytest
from fastapi.testclient import TestClient

from lumirss.main import app


@pytest.fixture()
def _sync_interval(monkeypatch: pytest.MonkeyPatch):
    def _set(value: str) -> None:
        monkeypatch.setenv("LUMIRSS_SEARCH_SYNC_INTERVAL", value)

    return _set


def test_interval_zero_creates_no_sync_task(_sync_interval):
    _sync_interval("0")
    with TestClient(app):
        assert app.state.search_sync_task is None


def test_negative_interval_rejected_at_config(_sync_interval):
    _sync_interval("-1")
    from lumirss.config import LumiSettings

    with pytest.raises(Exception):  # noqa: B017 — pydantic ValidationError
        LumiSettings()


def test_positive_interval_creates_sync_task(_sync_interval):
    _sync_interval("3600")
    with TestClient(app):
        task = app.state.search_sync_task
        assert task is not None
        assert not task.done()
