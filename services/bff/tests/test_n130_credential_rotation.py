"""N130 来源秘密轮换预演 — credentials test/rotate for API + inbox sources.

Proves: a bad new credential → stable 422 credential_test_failed with the
current credential UNTOUCHED (old secret still works); a good probe →
masked {ok, statusClass, latencyMs} (no secret, no header echo); rotate
swaps atomically and parks the old hash in SecretsStore as a fallback
key for the 10-minute window (reads prefer the new credential; a
fallback hit is flagged); the fallback is prunable (expired → old
credential dead). Inbox connectors mirror the contract.
"""

import asyncio
import json

import pytest


def _run(coroutine):
    return asyncio.run(coroutine)


NEW_CREDENTIAL = "rotated-credential-9f8e7d6c5b4a"
OLD_SECRET = None  # filled by fixtures


@pytest.fixture()
def api_source(client):
    created = client.post(
        "/api/v1/api-sources",
        json={
            "name": "轮换源",
            "endpoint": "https://api.example.com/x",
            "itemsExpr": "[*]",
            "fieldMap": {"id": "id", "title": "name"},
            "subscribe": False,
        },
    )
    assert created.status_code == 201
    return created.json()


def _stub_endpoint_ok(monkeypatch):
    import lumirss.routers.api_sources as routes

    async def _fetch(url, *args, **kwargs):
        return [{"id": 1, "name": "n"}]

    monkeypatch.setattr(routes, "fetch_json", _fetch)


def _stub_endpoint_broken(monkeypatch, message="API 端点返回 HTTP 503。"):
    import lumirss.routers.api_sources as routes

    async def _fetch(url, *args, **kwargs):
        raise routes.ApiSourceFetchFailed(message)

    monkeypatch.setattr(routes, "fetch_json", _fetch)


def _user_secret_store(app):
    return app.state.secrets_store.store_for(app.state.owner_id)


# -- API 来源：test（预演，不换） -------------------------------------------------


def test_api_test_rejects_weak_credential_and_keeps_old(client, api_source, monkeypatch):
    _stub_endpoint_ok(monkeypatch)
    response = client.post(
        f"/api/v1/api-sources/{api_source['uuid']}/credentials/test",
        json={"newCredential": "short"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["type"] == "credential_test_failed"
    # 旧凭据原样可用（Atom 地址照常 200）
    assert client.get(api_source["atomPath"]).status_code == 200


def test_api_test_reports_endpoint_failure_masked(client, api_source, monkeypatch):
    _stub_endpoint_broken(monkeypatch)
    response = client.post(
        f"/api/v1/api-sources/{api_source['uuid']}/credentials/test",
        json={"newCredential": NEW_CREDENTIAL},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert body["statusClass"] == "http_error"
    assert isinstance(body["latencyMs"], int)
    # 脱敏：凭据与请求/响应头绝不回显
    assert NEW_CREDENTIAL not in response.text
    for header_like in ("authorization", "x-api-key", "cookie"):
        assert header_like not in response.text.lower()
    assert set(body.keys()) == {"ok", "statusClass", "latencyMs", "note"}


def test_api_rotate_fails_probe_leaves_current_untouched(client, api_source, monkeypatch):
    _stub_endpoint_broken(monkeypatch)
    response = client.post(
        f"/api/v1/api-sources/{api_source['uuid']}/credentials/rotate",
        json={"newCredential": NEW_CREDENTIAL},
    )
    assert response.status_code == 422
    assert response.json()["error"]["type"] == "credential_test_failed"
    # 旧凭据仍然工作（当前 UNTOUCHED）：换回健康上游后 Atom 地址照常 200，
    # 鉴权用的是旧凭据（若已被换掉会 404）
    _stub_endpoint_ok(monkeypatch)
    assert client.get(api_source["atomPath"]).status_code == 200


def test_api_rotate_swaps_and_parks_fallback(client, api_source, monkeypatch):
    _stub_endpoint_ok(monkeypatch)
    response = client.post(
        f"/api/v1/api-sources/{api_source['uuid']}/credentials/rotate",
        json={"newCredential": NEW_CREDENTIAL},
    )
    assert response.status_code == 200
    body = response.json()
    assert body == {
        "ok": True,
        "statusClass": "ok",
        "latencyMs": body["latencyMs"],
        "note": body["note"],
    }
    assert NEW_CREDENTIAL not in response.text  # 脱敏
    # 新 Atom 地址（含新凭据）可用
    from lumirss.api_sources import atom_path

    new_path = atom_path(api_source["uuid"], NEW_CREDENTIAL)
    assert client.get(new_path).status_code == 200
    # 宽限窗口内旧地址仍可用（fallback 被动一次并打标）
    old_response = client.get(api_source["atomPath"])
    assert old_response.status_code == 200
    detail = client.get("/api/v1/api-sources").json()["items"][0]
    assert detail["lastStatus"] == "fallback_used"
    # fallback 键已停在 SecretsStore（未过期）
    secrets = _user_secret_store(client.app)
    from lumirss.credential_rotation import API_SOURCE_KIND, fallback_still_stored

    assert fallback_still_stored(secrets, API_SOURCE_KIND, api_source["uuid"])


def test_api_rotate_fallback_is_prunable(client, api_source, monkeypatch):
    _stub_endpoint_ok(monkeypatch)
    rotated = client.post(
        f"/api/v1/api-sources/{api_source['uuid']}/credentials/rotate",
        json={"newCredential": NEW_CREDENTIAL},
    )
    assert rotated.status_code == 200
    secrets = _user_secret_store(client.app)
    from lumirss.credential_rotation import (
        API_SOURCE_KIND,
        fallback_key,
    )

    # 把轮换时间改到 11 分钟前 → 懒清扫判定过期 → 旧凭据彻底失效
    key = fallback_key(API_SOURCE_KIND, api_source["uuid"])
    payload = json.loads(secrets.get(key))
    from datetime import UTC, datetime, timedelta

    payload["rotated_at"] = (
        datetime.now(UTC) - timedelta(seconds=660)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")
    secrets.set(key, json.dumps(payload, sort_keys=True))
    assert client.get(api_source["atomPath"]).status_code == 404
    assert secrets.get(key) is None  # 懒清扫已剪枝


# -- 收件连接器：同一契约 ---------------------------------------------------------


@pytest.fixture()
def inbox_source(client):
    created = client.post(
        "/api/v1/inbox/sources", json={"name": "轮换连接器"}
    )
    assert created.status_code == 200
    return created.json()


def _ingest(client, source, secret):
    return client.post(
        f"/api/v1/inbox/ingest/{source['uuid']}",
        headers={"Authorization": f"Bearer {secret}"},
        json={"guid": f"g-{secret[:6]}", "title": "推送标题"},
    )


def test_inbox_test_rejects_weak_credential(client, inbox_source):
    response = client.post(
        f"/api/v1/inbox/sources/{inbox_source['uuid']}/credentials/test",
        json={"newCredential": "has space, bad"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["type"] == "credential_test_failed"


def test_inbox_rotate_swaps_with_fallback_window(client, inbox_source):
    old_secret = inbox_source["secret"]
    response = client.post(
        f"/api/v1/inbox/sources/{inbox_source['uuid']}/credentials/rotate",
        json={"newCredential": NEW_CREDENTIAL},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert NEW_CREDENTIAL not in response.text  # 响应脱敏（旧 rotate 会回显一次明文；N130 轮换结果不回显）
    # 新凭据立即可推送
    assert _ingest(client, inbox_source, NEW_CREDENTIAL).status_code == 200
    # 宽限窗口内旧凭据仍可推送一次（flagged）
    fallback_response = _ingest(client, inbox_source, old_secret)
    assert fallback_response.status_code == 200
    sources = client.get("/api/v1/inbox/sources").json()
    assert any("fallback_used" in (s.get("lastError") or "") for s in sources)
