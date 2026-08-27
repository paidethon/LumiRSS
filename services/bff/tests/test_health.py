"""Test A — liveness endpoint."""

from fastapi.testclient import TestClient

from lumirss.main import app


def test_health_live_returns_ok():
    with TestClient(app) as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_live_ok_when_freshrss_unreachable():
    """Health isolation: the shared HTTP client points at a dead port, but
    /health/live must not care — it never touches FreshRSS."""
    with TestClient(app) as client:
        response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
