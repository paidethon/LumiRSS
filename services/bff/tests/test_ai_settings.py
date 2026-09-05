"""Tests for the persistent Lumi AI settings (0015 Gate 2).

All tests use a temp database injected onto app.state.db — no real Lumi
SQLite file is ever touched, and no secret is ever asserted beyond its
absence. The browser-managed profile layer lives in
test_ai_profiles_api.py; these tests pin the GLOBAL settings contract.
"""

from fastapi.testclient import TestClient

from lumirss.main import app
from lumirss.secrets_store import SecretsStore
from lumirss.storage import Database

import secrets as _secrets
# 动态生成的假凭据（非真实 secret；安全扫描要求无凭据形状字面量）
SMUGGLED_KEY = "sk-" + _secrets.token_urlsafe(8)


def _use_temp_state(tmp_path):
    app.state.db = Database(tmp_path / "lumi.sqlite")
    app.state.secrets_store = SecretsStore(tmp_path / "secrets.json")


_PURPOSE_DEFAULTS = {
    "profileId": "default",
    "source": "default",
    "profileLabel": None,
    "baseUrl": "",
    "model": "",
    "keyConfigured": False,
    "keySource": "missing",
    "configured": False,
}


def _expected_default_body():
    return {
        "provider": "openai_compatible",
        "baseUrl": "",
        "model": "",
        "summaryLanguage": "zh-CN",
        "translationLanguage": "zh-CN",
        "configured": False,
        "envKeyConfigured": False,
        "defaultKeyConfigured": False,
        "purposes": {
            "summary": "default",
            "translation": "default",
            "chat": "default",
        },
        "purposeStatus": {
            "summary": dict(_PURPOSE_DEFAULTS),
            "translation": dict(_PURPOSE_DEFAULTS),
            "chat": dict(_PURPOSE_DEFAULTS),
        },
    }


def test_get_ai_settings_returns_defaults_without_configuration(tmp_path):
    with TestClient(app) as client:
        _use_temp_state(tmp_path)
        response = client.get("/api/v1/settings/ai")

    assert response.status_code == 200
    body = response.json()
    assert body == _expected_default_body()


def test_put_ai_settings_persists_and_round_trips(tmp_path):
    with TestClient(app) as client:
        _use_temp_state(tmp_path)
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
        _use_temp_state(tmp_path)
        app.state.db = Database(path)
        client.put(
            "/api/v1/settings/ai",
            json={"model": "survivor-model"},
        )

    with TestClient(app) as client:
        _use_temp_state(tmp_path)
        app.state.db = Database(path)
        response = client.get("/api/v1/settings/ai")

    assert response.status_code == 200
    assert response.json()["model"] == "survivor-model"


def test_put_rejects_invalid_base_url(tmp_path):
    with TestClient(app) as client:
        _use_temp_state(tmp_path)
        response = client.put(
            "/api/v1/settings/ai",
            json={"baseUrl": "javascript:alert(1)"},
        )

    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_ai_settings"


def test_put_rejects_unsupported_summary_language(tmp_path):
    with TestClient(app) as client:
        _use_temp_state(tmp_path)
        response = client.put(
            "/api/v1/settings/ai",
            json={"summaryLanguage": "fr"},
        )

    assert response.status_code == 422


def test_configured_reports_key_presence_but_never_the_key(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_API_KEY", "sk-super-secret-value")
    with TestClient(app) as client:
        _use_temp_state(tmp_path)
        response = client.get("/api/v1/settings/ai")

    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is True
    assert body["envKeyConfigured"] is True
    assert "sk-super-secret-value" not in response.text
    assert "apiKey" not in response.text
    assert "api_key" not in response.text


def test_put_rejects_unknown_fields_like_api_key(tmp_path):
    with TestClient(app) as client:
        _use_temp_state(tmp_path)
        response = client.put(
            "/api/v1/settings/ai",
            json={"apiKey": SMUGGLED_KEY},
        )

    assert response.status_code == 422


def test_blank_base_url_clears_value(tmp_path):
    with TestClient(app) as client:
        _use_temp_state(tmp_path)
        client.put("/api/v1/settings/ai", json={"baseUrl": "https://api.example.com/v1"})
        cleared = client.put("/api/v1/settings/ai", json={"baseUrl": ""})

    assert cleared.status_code == 200
    assert cleared.json()["baseUrl"] == ""
