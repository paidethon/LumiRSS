"""N008 新设备登录提醒 — 设备标注会话 + login_events 事件流。

覆盖：新设备登录 → new_device 事件；同设备再次登录 → 不再产生
new_device（kind=login，seen 语义不受影响）；撤销会话仍然立即生效；
批量标记已读；事件流只属于本人且绝不含指纹/token 材料。
"""

import secrets as _secrets

import pytest
from fastapi.testclient import TestClient

from lumirss.accounts_store import AccountsStore, hash_password
from lumirss.auth_store import AuthStore, device_fingerprint, device_label_from_ua
from lumirss.main import app
from lumirss.storage import Database


def _fake(prefix: str) -> str:
    return prefix + _secrets.token_urlsafe(9)


PASSWORD = _fake("pw-")

CHROME_LINUX = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
FIREFOX_WIN = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0"


@pytest.fixture()
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    monkeypatch.setenv("LUMIRSS_SESSION_SECURE_COOKIES", "false")
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", "")
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    import lumirss.middleware as middleware

    middleware._rate_windows.clear()
    middleware._login_failures.clear()
    with TestClient(app, base_url="http://lumirss.test") as client:
        import asyncio

        async def _set_password():
            database = Database(tmp_path / "lumi.sqlite")
            await database.migrate()
            store = AccountsStore(database)
            owner = None
            for row in await store.list_users(limit=50):
                if row["role"] == "owner":
                    owner = row
                    break
            await store.set_password_hash(str(owner["id"]), hash_password(PASSWORD))

        asyncio.run(_set_password())
        yield {"client": client, "db_path": tmp_path}


def _login(client, password=PASSWORD, ua=None):
    headers = {"User-Agent": ua} if ua else {}
    return client.post(
        "/api/v1/auth/login",
        json={"username": "owner", "password": password},
        headers=headers,
    )


def test_device_label_masks_ua_family_and_platform():
    assert device_label_from_ua(CHROME_LINUX) == "Chrome/Linux"
    assert device_label_from_ua(FIREFOX_WIN) == "Firefox/Windows"
    assert device_label_from_ua(None) == "浏览器/未知平台"
    assert device_label_from_ua("curl/8.0") == "curl/未知平台"


def test_same_family_versions_share_fingerprint():
    ua_v125 = CHROME_LINUX.replace("Chrome/126.0", "Chrome/125.0")
    assert device_fingerprint(CHROME_LINUX) == device_fingerprint(ua_v125)
    assert device_fingerprint(CHROME_LINUX) != device_fingerprint(FIREFOX_WIN)


def test_new_device_then_known_device(env):
    client = env["client"]
    first = _login(client, ua=CHROME_LINUX)
    assert first.status_code == 200
    assert first.json().get("newDevice") is True  # 首次 = 新设备

    second = _login(client, ua=CHROME_LINUX)
    assert second.status_code == 200
    assert "newDevice" not in second.json()  # 已知设备不再提醒

    other = _login(client, ua=FIREFOX_WIN)
    assert other.status_code == 200
    assert other.json().get("newDevice") is True  # 又一台新设备

    events = client.get("/api/v1/auth/login-events").json()["items"]
    kinds = [e["kind"] for e in events]
    assert kinds.count("new_device") == 2
    assert kinds.count("login") == 1
    labels = {e["deviceLabel"] for e in events}
    assert labels == {"Chrome/Linux", "Firefox/Windows"}
    # 响应绝不含指纹/token 材料
    assert all("fingerprint" not in e and "token" not in e for e in events)


def test_login_events_cap_20(env):
    client = env["client"]
    for index in range(25):
        ua = f"curl/8.{index}"  # 同族不同小版本 → 同一指纹，事件持续累积
        response = _login(client, ua=ua)
        assert response.status_code == 200
    events = client.get("/api/v1/auth/login-events").json()["items"]
    assert len(events) == 20
    # 第一个事件（首登）已被裁掉最旧的一条……首条是 new_device 已被挤出？
    # 25 条登录 → cap 50 未触顶；GET cap 20 只显示最近 20 条。
    assert events[0]["createdAt"] >= events[-1]["createdAt"]


def test_seen_bulk_and_single(env):
    client = env["client"]
    _login(client, ua=CHROME_LINUX)
    _login(client, ua=FIREFOX_WIN)
    events = client.get("/api/v1/auth/login-events").json()["items"]
    assert all(e["seen"] is False for e in events)

    marked = client.post("/api/v1/auth/login-events/seen", json={})
    assert marked.status_code == 200
    assert marked.json()["marked"] == len(events)
    events = client.get("/api/v1/auth/login-events").json()["items"]
    assert all(e["seen"] is True for e in events)

    # 新设备再次出现 → 新事件未读；单独标记
    _login(client, ua="curl/9.0")
    events = client.get("/api/v1/auth/login-events").json()["items"]
    unread = [e for e in events if not e["seen"]]
    assert len(unread) == 1
    marked = client.post("/api/v1/auth/login-events/seen", json={"ids": [unread[0]["id"]]})
    assert marked.json()["marked"] == 1
    events = client.get("/api/v1/auth/login-events").json()["items"]
    assert all(e["seen"] is True for e in events)


def test_revoke_still_immediate(env):
    client = env["client"]
    response = _login(client, ua=CHROME_LINUX)
    cookie = response.headers["set-cookie"].split(";")[0]
    headers = {"cookie": cookie}
    # 第二台设备登录 → 存在一个非本机会话可供撤销
    _login(client, ua=FIREFOX_WIN)
    sessions = client.get("/api/v1/auth/sessions", headers=headers).json()
    assert any(s["current"] for s in sessions)
    target = next(s for s in sessions if not s["current"])
    revoked = client.delete(
        f"/api/v1/auth/sessions/{target['id']}", headers=headers
    )
    assert revoked.status_code == 204
    # 目标会话立即消失（撤销语义未被事件流改变）
    remaining_ids = {
        s["id"] for s in client.get("/api/v1/auth/sessions", headers=headers).json()
    }
    assert target["id"] not in remaining_ids


def test_sessions_carry_device_label(env):
    client = env["client"]
    response = _login(client, ua=CHROME_LINUX)
    cookie = response.headers["set-cookie"].split(";")[0]
    sessions = client.get(
        "/api/v1/auth/sessions", headers={"cookie": cookie}
    ).json()
    assert sessions[0]["deviceLabel"] == "Chrome/Linux"


def test_purge_before_counts(env):
    import asyncio
    import time as _time

    client = env["client"]
    _login(client, ua=CHROME_LINUX)
    _login(client, ua=FIREFOX_WIN)

    async def _purge():
        database = Database(env["db_path"] / "lumi.sqlite")
        await database.migrate()
        accounts = AccountsStore(database)
        owner = next(
            row
            for row in await accounts.list_users(limit=50)
            if row["role"] == "owner"
        )
        user_id = str(owner["id"])
        store = AuthStore(database)
        counted = await store.count_login_events_before(
            user_id, int(_time.time()) + 60
        )
        deleted = await store.purge_login_events_before(
            user_id, int(_time.time()) + 60
        )
        remaining = await store.list_login_events(user_id=user_id)
        return counted, deleted, remaining

    counted, deleted, remaining = asyncio.run(_purge())
    assert counted == 2
    assert deleted == 2
    assert remaining == []
