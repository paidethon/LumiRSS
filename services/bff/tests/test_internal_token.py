"""0021 hardening: single-user internal token (opt-in).

With LUMIRSS_INTERNAL_TOKEN configured, /api/* requires a matching
X-Lumi-Token header (Caddy injects it in production); /health/* stays
open for container healthchecks. Unset = previous behavior.
"""

from fastapi.testclient import TestClient

from lumirss.main import app

TOKEN = "itest-internal-token-9f2c"


def _client():
    return TestClient(app)


def test_token_unset_keeps_previous_behavior(monkeypatch):
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", "")
    with _client() as client:
        # An /api route that exists and answers without any token header.
        response = client.get("/api/v1/settings")
        assert response.status_code == 200


def test_token_required_on_api_routes(monkeypatch):
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", TOKEN)
    with _client() as client:
        missing = client.get("/api/v1/settings")
        assert missing.status_code == 401
        assert missing.json()["error"]["type"] == "unauthorized"

        wrong = client.get(
            "/api/v1/settings", headers={"X-Lumi-Token": "wrong-token"}
        )
        assert wrong.status_code == 401

        ok = client.get("/api/v1/settings", headers={"X-Lumi-Token": TOKEN})
        assert ok.status_code == 200


def test_health_stays_open_with_token_configured(monkeypatch):
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", TOKEN)
    with _client() as client:
        live = client.get("/health/live")
        assert live.status_code == 200
        assert "X-Lumi-Token" not in live.text


def test_non_api_paths_stay_open_with_token_configured(monkeypatch):
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", TOKEN)
    with _client() as client:
        # /docs / openapi are not part of the protected control plane.
        response = client.get("/openapi.json")
        assert response.status_code == 200
