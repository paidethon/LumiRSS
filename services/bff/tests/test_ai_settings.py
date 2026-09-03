"""Tests for the persistent Lumi AI settings (0015 Gate 2).

All tests use a temp database injected onto app.state.db — no real Lumi
SQLite file is ever touched, and no secret is ever asserted beyond its
absence.
"""

from fastapi.testclient import TestClient

from lumirss.main import app
from lumirss.storage import Database


def test_get_ai_settings_returns_defaults_without_configuration(tmp_path):
    with TestClient(app) as client:
        app.state.db = Database(tmp_path / "lumi.sqlite")
        response = client.get("/api/v1/settings/ai")

    assert response.status_code == 200
    body = response.json()
    assert body == {
        "provider": "openai_compatible",
        "baseUrl": "",
        "model": "",
        "summaryLanguage": "zh-CN",
        "configured": False,
    }


def test_put_ai_settings_persists_and_round_trips(tmp_path):
    with TestClient(app) as client:
        app.state.db = Database(tmp_path / "lumi.sqlite")
        response = client.put(
            "/api/v1/settings/ai",
            json={
                "baseUrl": "https://api.deepseek.com/v1",
                "model": "deepseek-chat",
                "summaryLanguage": "en",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["baseUrl"] == "https://api.deepseek.com/v1"
        assert body["model"] == "deepseek-chat"
        assert body["summaryLanguage"] == "en"
        assert body["configured"] is False

        reread = client.get("/api/v1/settings/ai")
        assert reread.json()["baseUrl"] == "https://api.deepseek.com/v1"


def test_settings_survive_app_restart(tmp_path):
    path = tmp_path / "lumi.sqlite"
    with TestClient(app) as client:
        app.state.db = Database(path)
        client.put(
            "/api/v1/settings/ai",
            json={"model": "survivor-model"},
        )

    with TestClient(app) as client:
        app.state.db = Database(path)
        response = client.get("/api/v1/settings/ai")

    assert response.status_code == 200
    assert response.json()["model"] == "survivor-model"


def test_put_rejects_invalid_base_url(tmp_path):
    with TestClient(app) as client:
        app.state.db = Database(tmp_path / "lumi.sqlite")
        response = client.put(
            "/api/v1/settings/ai",
            json={"baseUrl": "javascript:alert(1)"},
        )

    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_ai_settings"


def test_put_rejects_unsupported_summary_language(tmp_path):
    with TestClient(app) as client:
        app.state.db = Database(tmp_path / "lumi.sqlite")
        response = client.put(
            "/api/v1/settings/ai",
            json={"summaryLanguage": "fr"},
        )

    assert response.status_code == 422


def test_configured_reports_key_presence_but_never_the_key(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_API_KEY", "sk-super-secret-value")
    with TestClient(app) as client:
        app.state.db = Database(tmp_path / "lumi.sqlite")
        response = client.get("/api/v1/settings/ai")

    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is True
    assert "sk-super-secret-value" not in response.text
    assert "apiKey" not in response.text
    assert "api_key" not in response.text


def test_put_rejects_unknown_fields_like_api_key(tmp_path):
    with TestClient(app) as client:
        app.state.db = Database(tmp_path / "lumi.sqlite")
        response = client.put(
            "/api/v1/settings/ai",
            json={"apiKey": "sk-smuggled"},
        )

    assert response.status_code == 422


def test_blank_base_url_clears_value(tmp_path):
    with TestClient(app) as client:
        app.state.db = Database(tmp_path / "lumi.sqlite")
        client.put("/api/v1/settings/ai", json={"baseUrl": "https://api.example.com/v1"})
        cleared = client.put("/api/v1/settings/ai", json={"baseUrl": ""})

    assert cleared.status_code == 200
    assert cleared.json()["baseUrl"] == ""
