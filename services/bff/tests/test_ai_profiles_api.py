"""Route-level tests for browser-managed AI profiles (purpose mapping).

Contract pinned here:

- profiles CRUD: create/list/patch/delete; keys NEVER appear anywhere;
- secrets are write-only: PUT/DELETE return 204 with an empty body;
- purpose mapping validates targets and resets when a profile dies;
- the default (legacy) key endpoint stores in the SecretsStore and the
  env AI_API_KEY remains the visible fallback;
- GET /api/v1/version exposes build provenance only (no env/paths).
"""

import asyncio

from fastapi.testclient import TestClient

from lumirss.main import app
from lumirss.secrets_store import SecretsStore
from lumirss.storage import Database

import secrets as _secrets

FAKE_KEY = "sk-" + _secrets.token_urlsafe(12)
FAKE_KEY_2 = "sk-" + _secrets.token_urlsafe(12)


def _use_temp_state(tmp_path):
    app.state.db = Database(tmp_path / "lumi.sqlite")
    app.state.secrets_store = SecretsStore(tmp_path / "secrets.json")
    app.state.ai_profile_store = None
    app.state.ai_settings_store = None


def run(coroutine):
    return asyncio.run(coroutine)


def _create_profile(client, label="GLM 摘要", **overrides):
    body = {"label": label, "baseUrl": "https://api.example.com/v1", "model": "glm-x"}
    body.update(overrides)
    response = client.post("/api/v1/settings/ai/profiles", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_version_endpoint_exposes_provenance_only(tmp_path):
    with TestClient(app) as client:
        _use_temp_state(tmp_path)
        response = client.get("/api/v1/version")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"version", "commit", "apiVersion"}
    assert body["apiVersion"] == 1
    assert isinstance(body["version"], str)
    assert isinstance(body["commit"], str)


def test_create_and_list_profiles_round_trip(tmp_path):
    with TestClient(app) as client:
        _use_temp_state(tmp_path)
        created = _create_profile(client)
        assert created["label"] == "GLM 摘要"
        assert created["provider"] == "openai_compatible"
        assert created["baseUrl"] == "https://api.example.com/v1"
        assert created["model"] == "glm-x"
        assert created["enabled"] is True
        assert created["keyConfigured"] is False

        listing = client.get("/api/v1/settings/ai/profiles")
        assert listing.status_code == 200
        assert [item["id"] for item in listing.json()] == [created["id"]]


def test_profile_validation_rejects_bad_values(tmp_path):
    with TestClient(app) as client:
        _use_temp_state(tmp_path)
        blank = client.post("/api/v1/settings/ai/profiles", json={"label": "  "})
        assert blank.status_code == 400
        assert blank.json()["error"]["type"] == "invalid_ai_settings"

        bad_url = client.post(
            "/api/v1/settings/ai/profiles",
            json={"label": "x", "baseUrl": "javascript:alert(1)"},
        )
        assert bad_url.status_code == 400


def test_profile_secret_is_write_only_and_never_echoed(tmp_path):
    with TestClient(app) as client:
        _use_temp_state(tmp_path)
        profile = _create_profile(client)

        put = client.put(
            f"/api/v1/settings/ai/profiles/{profile['id']}/secret",
            json={"value": FAKE_KEY},
        )
        assert put.status_code == 204
        assert put.text == ""

        status = client.get("/api/v1/settings/ai")
        assert status.status_code == 200
        assert FAKE_KEY not in status.text
        profiles = client.get("/api/v1/settings/ai/profiles").json()
        assert profiles[0]["keyConfigured"] is True
        assert FAKE_KEY not in client.get(
            "/api/v1/settings/ai/profiles"
        ).text

        cleared = client.delete(
            f"/api/v1/settings/ai/profiles/{profile['id']}/secret"
        )
        assert cleared.status_code == 204
        profiles = client.get("/api/v1/settings/ai/profiles").json()
        assert profiles[0]["keyConfigured"] is False


def test_profile_secret_on_unknown_profile_is_404(tmp_path):
    with TestClient(app) as client:
        _use_temp_state(tmp_path)
        put = client.put(
            "/api/v1/settings/ai/profiles/does-not-exist/secret",
            json={"value": FAKE_KEY},
        )
        assert put.status_code == 404
        assert put.json()["error"]["type"] == "ai_profile_not_found"


def test_purpose_mapping_round_trip_and_validation(tmp_path):
    with TestClient(app) as client:
        _use_temp_state(tmp_path)
        profile = _create_profile(client)

        empty = client.get("/api/v1/settings/ai/purposes")
        assert empty.status_code == 200
        assert empty.json() == {
            "summary": "default",
            "translation": "default",
            "chat": "default",
        }

        saved = client.put(
            "/api/v1/settings/ai/purposes",
            json={"translation": profile["id"], "chat": "default"},
        )
        assert saved.status_code == 200
        assert saved.json() == {
            "summary": "default",
            "translation": profile["id"],
            "chat": "default",
        }

        unknown = client.put(
            "/api/v1/settings/ai/purposes",
            json={"summary": "no-such-profile"},
        )
        assert unknown.status_code == 404

        # purposeStatus reflects the mapping (secret-free)
        status = client.get("/api/v1/settings/ai").json()
        assert status["purposes"]["translation"] == profile["id"]
        assert status["purposeStatus"]["translation"]["source"] == "profile"
        assert (
            status["purposeStatus"]["translation"]["profileLabel"] == "GLM 摘要"
        )
        # No key configured on the profile → honestly not configured.
        assert status["purposeStatus"]["translation"]["keyConfigured"] is False
        assert status["purposeStatus"]["translation"]["configured"] is False
        assert status["purposeStatus"]["summary"]["source"] == "default"


def test_delete_profile_resets_purpose_mapping_and_secret(tmp_path):
    with TestClient(app) as client:
        _use_temp_state(tmp_path)
        profile = _create_profile(client)
        client.put(
            f"/api/v1/settings/ai/profiles/{profile['id']}/secret",
            json={"value": FAKE_KEY},
        )
        client.put(
            "/api/v1/settings/ai/purposes",
            json={"summary": profile["id"], "chat": profile["id"]},
        )

        deleted = client.delete(f"/api/v1/settings/ai/profiles/{profile['id']}")
        assert deleted.status_code == 204

        listing = client.get("/api/v1/settings/ai/profiles")
        assert listing.json() == []
        purposes = client.get("/api/v1/settings/ai/purposes").json()
        assert purposes == {
            "summary": "default",
            "translation": "default",
            "chat": "default",
        }


def test_default_key_endpoint_write_only_env_fallback_visible(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("AI_API_KEY", raising=False)
    with TestClient(app) as client:
        _use_temp_state(tmp_path)
        before = client.get("/api/v1/settings/ai").json()
        assert before["envKeyConfigured"] is False
        assert before["defaultKeyConfigured"] is False

        put = client.put("/api/v1/settings/ai/key", json={"value": FAKE_KEY_2})
        assert put.status_code == 204
        assert put.text == ""

        after = client.get("/api/v1/settings/ai").json()
        assert after["defaultKeyConfigured"] is True
        assert after["envKeyConfigured"] is False
        assert after["purposeStatus"]["summary"]["keyConfigured"] is True
        assert after["purposeStatus"]["summary"]["keySource"] == "default_secret"
        assert FAKE_KEY_2 not in client.get("/api/v1/settings/ai").text

        cleared = client.delete("/api/v1/settings/ai/key")
        assert cleared.status_code == 204
        final = client.get("/api/v1/settings/ai").json()
        assert final["defaultKeyConfigured"] is False


def test_env_key_remains_fallback_for_default_resolution(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("AI_API_KEY", FAKE_KEY)
    with TestClient(app) as client:
        _use_temp_state(tmp_path)
        status = client.get("/api/v1/settings/ai").json()
        assert status["envKeyConfigured"] is True
        assert status["defaultKeyConfigured"] is True
        assert status["purposeStatus"]["summary"]["keySource"] == "env"
        assert FAKE_KEY not in client.get("/api/v1/settings/ai").text


def test_disabled_profile_falls_back_to_default(tmp_path):
    with TestClient(app) as client:
        _use_temp_state(tmp_path)
        profile = _create_profile(client, label="停用的")
        client.put(
            f"/api/v1/settings/ai/profiles/{profile['id']}/secret",
            json={"value": FAKE_KEY},
        )
        client.patch(
            f"/api/v1/settings/ai/profiles/{profile['id']}",
            json={"enabled": False},
        )
        client.put(
            "/api/v1/settings/ai/purposes",
            json={"translation": profile["id"]},
        )

        status = client.get("/api/v1/settings/ai").json()
        assert status["purposeStatus"]["translation"]["source"] == "default"


def test_manual_trigger_only_get_routes_never_build_a_provider(tmp_path):
    """Reading status/settings/profiles must never require or touch a key
    beyond boolean flags — GET /settings/ai works with zero config."""
    with TestClient(app) as client:
        _use_temp_state(tmp_path)
        assert client.get("/api/v1/settings/ai").status_code == 200
        assert client.get("/api/v1/settings/ai/profiles").status_code == 200
        assert client.get("/api/v1/settings/ai/purposes").status_code == 200
