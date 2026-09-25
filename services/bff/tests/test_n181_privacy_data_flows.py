"""N181 逐来源数据外发清单 — 来自真实配置；主机名 only；无密钥。"""

import secrets


def test_n181_unconfigured_capability_reports_not_sending(client):
    """未配置的能力如实返回 configured=false（UI 显示「不发送」）。"""
    response = client.get("/api/v1/privacy/data-flows")
    assert response.status_code == 200
    flows = {item["capability"]: item for item in response.json()["flows"]}
    assert flows["ai-summary"]["configured"] is False
    assert flows["ai-translation"]["configured"] is False
    assert flows["libretranslate"]["configured"] is False
    assert flows["webdav"]["configured"] is False
    assert flows["imap"]["configured"] is False
    # 未配置条目不携带主机名
    assert flows["ai-summary"].get("providerHost") in (None, "")


def test_n181_configured_ai_shows_host_only(client):
    """配置了 AI → configured=true 且 providerHost 只有主机名。"""
    put = client.put(
        "/api/v1/settings/ai",
        json={"baseUrl": "https://api.openai.com/v1", "model": "gpt-test"},
    )
    assert put.status_code == 200, put.text
    flows = {
        item["capability"]: item
        for item in client.get("/api/v1/privacy/data-flows").json()["flows"]
    }
    assert flows["ai-summary"]["configured"] is True
    assert flows["ai-summary"]["providerHost"] == "api.openai.com"
    assert flows["ai-chat"]["configured"] is True
    assert flows["ai-chat"]["providerHost"] == "api.openai.com"


def test_n181_libretranslate_engine_and_url(client):
    put = client.put(
        "/api/v1/settings/ai",
        json={
            "translationEngine": "libretranslate",
            "libretranslateUrl": "https://libre.example.com",
        },
    )
    assert put.status_code == 200, put.text
    flows = {
        item["capability"]: item
        for item in client.get("/api/v1/privacy/data-flows").json()["flows"]
    }
    assert flows["libretranslate"]["configured"] is True
    assert flows["libretranslate"]["providerHost"] == "libre.example.com"
    # 引擎切到 libretranslate 后，AI 翻译不再外发
    assert flows["ai-translation"]["configured"] is False


def test_n181_tts_is_local_and_never_sends(client):
    flows = {
        item["capability"]: item
        for item in client.get("/api/v1/privacy/data-flows").json()["flows"]
    }
    assert flows["tts"]["configured"] is True
    assert flows["tts"]["local"] is True
    assert not flows["tts"]["providerHost"]


def test_n181_no_secrets_in_response(client):
    """配置了含密码的 WebDAV + IMAP → 响应只有主机名，绝无密钥/用户名。"""
    password = secrets.token_urlsafe(16)
    imap_password = secrets.token_urlsafe(16)
    put = client.put(
        "/api/v1/backups/webdav",
        json={
            "serverUrl": "https://dav.example.com:5006/home/lumi",
            "username": "operator-user",
            "password": password,
        },
    )
    assert put.status_code == 200, put.text
    imap = client.put(
        "/api/v1/mail/imap/settings",
        json={
            "host": "imap.mail.example.com",
            "user": "news-user",
            "password": imap_password,
        },
    )
    assert imap.status_code == 200, imap.text
    body = client.get("/api/v1/privacy/data-flows").json()
    text = str(body)
    assert password not in text
    assert imap_password not in text
    assert "operator-user" not in text
    assert "news-user" not in text
    flows = {item["capability"]: item for item in body["flows"]}
    assert flows["webdav"]["providerHost"] == "dav.example.com"
    assert flows["imap"]["providerHost"] == "imap.mail.example.com"
