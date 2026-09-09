"""0021 hardening: lightweight fixed-window rate limits.

Expensive control-plane routes (AI generation, restore, backups, outbound
discovery, RSSHub mutations) get generous single-user buckets; reading
endpoints stay unlimited. Tests shrink the windows via the rules table.
"""

import asyncio

from fastapi.testclient import TestClient

from lumirss.main import app
from lumirss.middleware import _rate_windows


def run(coroutine):
    return asyncio.run(coroutine)


def _shrink_rules(monkeypatch):
    """Two requests per 60s window for every rule (middleware reads the
    module-level table per request, so patching it changes live behavior)."""
    import lumirss.middleware as middleware

    shrunk = tuple(
        (method, prefix, bucket, 2, 60)
        for method, prefix, bucket, _max, _window in middleware._RATE_RULES
    )
    monkeypatch.setattr(middleware, "_RATE_RULES", shrunk)


def test_rate_limited_returns_stable_429_with_retry_after(monkeypatch, tmp_path):
    monkeypatch.setenv("LUMIRSS_DATA_DIR", str(tmp_path / "data"))
    _shrink_rules(monkeypatch)
    _rate_windows.clear()
    with TestClient(app) as client:
        statuses = [
            client.post(
                "/api/v1/feed-preview",
                json={"feedUrl": "https://example.com/feed.xml"},
            ).status_code
            for _ in range(4)
        ]
    _rate_windows.clear()
    # First two pass the limiter (feed may 400/502 afterwards — outbound),
    # the rest are refused by the limiter with the stable envelope.
    assert statuses[2] == 429 and statuses[3] == 429
    assert statuses[0] != 429 and statuses[1] != 429


def test_rate_limit_429_body_shape(monkeypatch, tmp_path):
    monkeypatch.setenv("LUMIRSS_DATA_DIR", str(tmp_path / "data"))
    _shrink_rules(monkeypatch)
    _rate_windows.clear()
    with TestClient(app) as client:
        for _ in range(3):
            last = client.post(
                "/api/v1/feed-preview",
                json={"feedUrl": "https://example.com/feed.xml"},
            )
    _rate_windows.clear()
    assert last.status_code == 429
    assert last.json()["error"]["type"] == "rate_limited"
    assert "retry-after" in {k.lower() for k in last.headers}


def test_reading_endpoints_stay_unlimited(monkeypatch, tmp_path):
    monkeypatch.setenv("LUMIRSS_DATA_DIR", str(tmp_path / "data"))
    _shrink_rules(monkeypatch)
    _rate_windows.clear()
    with TestClient(app) as client:
        statuses = [client.get("/health/live").status_code for _ in range(40)]
    _rate_windows.clear()
    assert set(statuses) == {200}
