"""Tests for the persistent Lumi AI settings (0015 Gate 2).

All tests use a temp database injected onto app.state.db — no real Lumi
SQLite file is ever touched, and no secret is ever asserted beyond its
absence. The browser-managed profile layer lives in
test_ai_profiles_api.py; these tests pin the GLOBAL settings contract.
"""

import secrets as _secrets

from fastapi.testclient import TestClient

from lumirss.main import app
from lumirss.secrets_store import SecretsStore
from lumirss.storage import Database

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
        "translationEngine": "ai",
        "libretranslateUrl": "",
        "libretranslateKeyConfigured": False,
        # FIX-142：实际能力状态（最近一次有界探测）；untested = 从未探测。
        "libretranslateStatus": "untested",
        "libretranslateCheckedAt": None,
        "libretranslateDiagnostic": None,
        "configured": False,
        "envKeyConfigured": False,
        "defaultKeyConfigured": False,
        "purposes": {
            "summary": "default",
            "translation": "default",
            "chat": "default",
            "tts": "default",  # N098：TTS 作为第四用途，默认同 default profile
        },
        "purposeStatus": {
            "summary": dict(_PURPOSE_DEFAULTS),
            "translation": dict(_PURPOSE_DEFAULTS),
            "chat": dict(_PURPOSE_DEFAULTS),
            "tts": dict(_PURPOSE_DEFAULTS),
        },
        "quotaWindow": "",
        "quotaMaxCalls": 0,
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


def test_put_rejects_plain_http_base_url_without_allowlist(tmp_path, monkeypatch):
    """SSRF baseline (quality closure): the BFF dials the AI base URL
    server-side and sends the API key as a bearer token, so an arbitrary
    http:// host must not be storable unless the operator allow-listed it."""
    monkeypatch.delenv("LUMIRSS_FETCH_ALLOW_PRIVATE_HOSTS", raising=False)
    with TestClient(app) as client:
        _use_temp_state(tmp_path)
        rejected = client.put(
            "/api/v1/settings/ai",
            json={"baseUrl": "http://10.0.0.5:8000/v1"},
        )
        assert rejected.status_code == 400

        monkeypatch.setenv(
            "LUMIRSS_FETCH_ALLOW_PRIVATE_HOSTS", "10.0.0.5"
        )
        allowed = client.put(
            "/api/v1/settings/ai",
            json={"baseUrl": "http://10.0.0.5:8000/v1"},
        )
        assert allowed.status_code == 200


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


# ---- FIX-142: 本地翻译能力状态 = 实际探测结果（非“配置存在”即“可用”）----


def test_libretranslate_view_defaults_to_untested_capability(tmp_path):
    """FIX-142: 配置了 URL 只代表“已配置”；能力状态必须独立呈现——
    从未探测时诚实显示 untested，绝不暗示可用。"""
    import httpx

    with TestClient(app) as client:
        _use_temp_state(tmp_path)
        app.state.http_client = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(500, text="down")
            )
        )
        client.put(
            "/api/v1/settings/ai",
            json={
                "translationEngine": "libretranslate",
                "libretranslateUrl": "https://libre.example.com",
            },
        )
        before = client.get("/api/v1/settings/ai").json()
        assert before["translationEngine"] == "libretranslate"
        assert before["libretranslateStatus"] == "untested"
        assert before["libretranslateCheckedAt"] is None


def test_libretranslate_test_persists_capability_state(tmp_path):
    """FIX-142: POST libretranslate-test 是有界能力探测（GET /languages，
    上游超时上限）；其结果必须被持久化，GET /settings/ai 如实上报
    ok/failed + 最近检查时间 + 诊断——引擎“已启用”不再与“实际可用”脱节，
    且 stale 状态由 checkedAt 如实暴露。"""
    import httpx

    def ok_handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/languages"
        return httpx.Response(
            200, json=[{"code": "en"}, {"code": "zh"}]
        )

    with TestClient(app) as client:
        _use_temp_state(tmp_path)
        app.state.http_client = httpx.AsyncClient(
            transport=httpx.MockTransport(ok_handler)
        )
        client.put(
            "/api/v1/settings/ai",
            json={"libretranslateUrl": "https://libre.example.com"},
        )
        probe = client.post("/api/v1/settings/translation/libretranslate-test")
        assert probe.status_code == 200, probe.text
        probe_body = probe.json()
        assert probe_body["status"] == "ok"
        assert probe_body["checkedAt"]

        view = client.get("/api/v1/settings/ai").json()
        assert view["libretranslateStatus"] == "ok"
        assert view["libretranslateCheckedAt"] == probe_body["checkedAt"]
        assert view["libretranslateDiagnostic"]

    # 服务不可达 → 探测 failed 且视图如实降级（不再是上一次的 ok）。
    def down_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with TestClient(app) as client:
        _use_temp_state(tmp_path)
        app.state.http_client = httpx.AsyncClient(
            transport=httpx.MockTransport(down_handler)
        )
        client.put(
            "/api/v1/settings/ai",
            json={"libretranslateUrl": "https://libre.example.com"},
        )
        probe = client.post("/api/v1/settings/translation/libretranslate-test")
        assert probe.status_code == 200
        assert probe.json()["status"] == "failed"

        view = client.get("/api/v1/settings/ai").json()
        assert view["libretranslateStatus"] == "failed"
        assert view["libretranslateCheckedAt"]
        assert view["libretranslateDiagnostic"]
