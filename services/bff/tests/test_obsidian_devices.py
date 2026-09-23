"""P16 设备档案 + 导出模板 + 交接 —— 用户级 CRUD、跨账户 404、
模板读写（默认回退）、交接 URI/file 裁决（路由 + 纯函数）。

- 设备路由是 user-scoped（无 owner 门槛）：member 各自管理自己的设备；
- RoutingDatabase 路由即隔离：跨用户读改删都是 404，不是数据泄露；
- handoff 的 adapter 用假件替换（测试不打真实上游，约定同全 suite）。"""

import asyncio
import secrets as _secrets

import pytest
from fastapi.testclient import TestClient

from lumirss.accounts_store import AccountsStore, hash_password
from lumirss.main import app
from lumirss.obsidian_devices import (
    DeviceProfileInvalid,
    ObsidianDeviceStore,
    ObsidianExportSettingsStore,
)
from lumirss.obsidian_handoff import prepare_handoff
from lumirss.obsidian_template import DEFAULT_TEMPLATE
from lumirss.storage import Database
from lumirss.user_scope import RoutingDatabase, user_context

PASSWORD = "p16-" + _secrets.token_urlsafe(9)


# ---------------------------------------------------------------------------
# Store 级（RoutingDatabase + user_context，路由即隔离）
# ---------------------------------------------------------------------------


@pytest.fixture()
def routed_db(tmp_path):
    # 不预迁移：RoutingDatabase.migrate 依赖用户上下文，store 各方法
    # 会在上下文内自行惰性迁移（与生产路径一致）。
    return RoutingDatabase(tmp_path / "control.sqlite", tmp_path / "users")


def _run(coro):
    return asyncio.run(coro)


class _Detail:
    """Minimal EntryDetail stand-in for the pure handoff path."""

    entryRef = "e1.a"
    title = "中文标题：P16 交接"
    feedTitle = "示例源"
    url = "https://example.com/a"
    publishedAt = "2026-09-23T08:00:00Z"
    crawledAt = None
    contentText = "第一段。\n\n第二段。"


def test_store_crud_roundtrip_scoped_by_context(routed_db):
    with user_context("alice"):
        created = _run(
            ObsidianDeviceStore(routed_db).create(
                label="Windows 台式机",
                vault_name="我的笔记库",
                vault_identifier="",
                platform="windows",
            )
        )
        assert created["platform"] == "windows"
        assert created["label"] == "Windows 台式机"
        items = _run(ObsidianDeviceStore(routed_db).list_profiles())
        assert [i["id"] for i in items] == [created["id"]]

        updated = _run(
            ObsidianDeviceStore(routed_db).update(
                created["id"],
                label="Windows 台式机（改名）",
                vault_name="我的笔记库",
                vault_identifier="vault-1",
                platform="windows",
            )
        )
        assert updated is not None
        assert updated["label"] == "Windows 台式机（改名）"
        assert updated["vault_identifier"] == "vault-1"

    with user_context("bob"):
        # 水平隔离：bob 看不见 alice 的设备；改/删都等于「不存在」。
        assert _run(ObsidianDeviceStore(routed_db).list_profiles()) == []
        assert _run(ObsidianDeviceStore(routed_db).get(created["id"])) is None
        assert (
            _run(
                ObsidianDeviceStore(routed_db).update(
                    created["id"],
                    label="偷改",
                    vault_name="v",
                    platform="other",
                )
            )
            is None
        )
        assert _run(ObsidianDeviceStore(routed_db).delete(created["id"])) is False


def test_store_validation(routed_db):
    with user_context("alice"):
        store = ObsidianDeviceStore(routed_db)
        with pytest.raises(DeviceProfileInvalid):
            _run(store.create(label="", vault_name="v"))
        with pytest.raises(DeviceProfileInvalid):
            _run(store.create(label="x", vault_name="  "))
        with pytest.raises(DeviceProfileInvalid):
            _run(store.create(label="x", vault_name="v", platform="android"))
        with pytest.raises(DeviceProfileInvalid):
            _run(store.create(label="x" * 101, vault_name="v"))


def test_template_store_default_fallback(routed_db):
    with user_context("alice"):
        store = ObsidianExportSettingsStore(routed_db)
        # 空 = 代码默认（DEFAULT_TEMPLATE 是唯一默认事实源）。
        assert _run(store.get_template()) == DEFAULT_TEMPLATE
        assert _run(store.get_stored_template()) == ""
        custom = "{{title}}\n\n{{annotations}}"
        assert _run(store.set_template(custom)) == custom
        assert _run(store.get_stored_template()) == custom
    with user_context("bob"):
        # 模板同样每用户隔离。
        assert _run(ObsidianExportSettingsStore(routed_db).get_template()) == DEFAULT_TEMPLATE


def test_prepare_handoff_uri_and_budget():
    profile = {"label": "台式机", "vault_name": "我的笔记库", "platform": "windows"}
    prepared = prepare_handoff(profile=profile, detail=_Detail(), annotations=[])
    assert prepared.mode == "uri"
    assert prepared.uri is not None
    assert prepared.uri.startswith("obsidian://new?")
    assert prepared.filename.endswith(".md")
    assert "P16" in prepared.filename or prepared.filename == "文章.md"
    assert prepared.content.startswith("中文标题：P16 交接")

    # 8000 字符预算按编码后 URI 计量：大段中文正文 → file 回退。
    huge = _Detail()
    huge.contentText = "汉" * 6000
    oversized = prepare_handoff(profile=profile, detail=huge, annotations=[])
    assert oversized.mode == "file"
    assert oversized.reason == "tooLong"
    assert oversized.uri is None
    assert huge.contentText in oversized.content  # 内容完整保留（下载路径用）


def test_prepare_handoff_includes_annotation_para_links():
    annotations = [
        {
            "entry_ref": "e1.a",
            "anchor": {"paraId": "abcd1234-2"},
            "excerpt": "关键一句",
            "note": "",
        }
    ]
    prepared = prepare_handoff(
        profile={"label": "iPhone", "vault_name": "v", "platform": "ios"},
        detail=_Detail(),
        annotations=annotations,
        template="{{annotations}}",
    )
    assert "/reader?entry=e1.a&para=abcd1234-2" in prepared.content
    assert "关键一句" in prepared.content


# ---------------------------------------------------------------------------
# 路由级（basic 模式，conftest 的 client fixture：单用户无会话门槛）
# ---------------------------------------------------------------------------


def _payload(**over):
    base = {
        "label": "iPhone 15",
        "vaultName": "移动笔记库",
        "vaultIdentifier": "",
        "platform": "ios",
    }
    base.update(over)
    return base


def test_device_routes_crud_and_errors(client, monkeypatch):
    created = client.post("/api/v1/obsidian/devices", json=_payload())
    assert created.status_code == 201, created.text
    device = created.json()
    assert device["platform"] == "ios"
    assert device["vaultName"] == "移动笔记库"

    listed = client.get("/api/v1/obsidian/devices")
    assert listed.status_code == 200
    assert [i["id"] for i in listed.json()["items"]] == [device["id"]]

    updated = client.put(
        f"/api/v1/obsidian/devices/{device['id']}",
        json=_payload(label="iPad Pro", platform="ipados"),
    )
    assert updated.status_code == 200
    assert updated.json()["platform"] == "ipados"

    invalid = client.post(
        "/api/v1/obsidian/devices", json=_payload(platform="android")
    )
    assert invalid.status_code == 422

    missing_update = client.put(
        "/api/v1/obsidian/devices/no-such-id", json=_payload()
    )
    assert missing_update.status_code == 404
    assert missing_update.json()["error"]["type"] == "device_profile_not_found"

    missing_delete = client.delete("/api/v1/obsidian/devices/no-such-id")
    assert missing_delete.status_code == 404

    deleted = client.delete(f"/api/v1/obsidian/devices/{device['id']}")
    assert deleted.status_code == 204
    assert client.get("/api/v1/obsidian/devices").json()["items"] == []


def test_template_routes_and_handoff_route(client, monkeypatch):
    from lumirss.entryref import encode_entry_ref

    view = client.get("/api/v1/obsidian/export-template")
    assert view.status_code == 200
    body = view.json()
    assert body["template"] == ""
    assert body["defaultTemplate"] == DEFAULT_TEMPLATE
    assert "annotations" in body["allowedVars"]

    saved = client.put(
        "/api/v1/obsidian/export-template", json={"template": "{{title}}"}
    )
    assert saved.status_code == 200
    assert client.get("/api/v1/obsidian/export-template").json()["template"] == "{{title}}"

    preview = client.post(
        "/api/v1/obsidian/export-template/preview",
        json={"template": "{{title}} {{nope}}"},
    )
    assert preview.status_code == 200
    assert preview.json()["source"] == "fixture"
    assert preview.json()["unknownVars"] == ["nope"]

    device = client.post("/api/v1/obsidian/devices", json=_payload()).json()
    # 设备不存在 → 404（先于 adapter 解析）。
    missing = client.post(
        "/api/v1/obsidian/export-handoff",
        json={"entryRef": encode_entry_ref("item-1"), "deviceId": "no-such"},
    )
    assert missing.status_code == 404

    # 假 adapter：交接路由全链路（不打上游）。
    class _FakeAdapter:
        async def get_entry(self, item_id):
            return _Detail()

    from lumirss import deps

    monkeypatch.setattr(deps, "_get_adapter", lambda request: _FakeAdapter())
    handoff = client.post(
        "/api/v1/obsidian/export-handoff",
        json={"entryRef": encode_entry_ref("item-1"), "deviceId": device["id"]},
    )
    assert handoff.status_code == 200, handoff.text
    result = handoff.json()
    assert result["mode"] == "uri"
    assert result["uri"].startswith("obsidian://new?")
    assert result["deviceLabel"] == "iPhone 15"
    assert "量子" not in result["content"]  # 夹具正文如实渲染
    assert result["content"].startswith("中文标题：P16 交接")


def test_handoff_too_long_returns_file_mode(client, monkeypatch):
    from lumirss.entryref import encode_entry_ref

    device = client.post(
        "/api/v1/obsidian/devices", json=_payload(label="台式机", platform="windows")
    ).json()

    class _FakeAdapter:
        async def get_entry(self, item_id):
            detail = _Detail()
            detail.contentText = "汉" * 6000
            return detail

    from lumirss import deps

    monkeypatch.setattr(deps, "_get_adapter", lambda request: _FakeAdapter())
    handoff = client.post(
        "/api/v1/obsidian/export-handoff",
        json={"entryRef": encode_entry_ref("item-1"), "deviceId": device["id"]},
    )
    assert handoff.status_code == 200
    result = handoff.json()
    assert result["mode"] == "file"
    assert result["reason"] == "tooLong"
    assert result["uri"] is None
    assert len(result["content"]) > 0


# ---------------------------------------------------------------------------
# 跨账户（session 模式）：member 各自 CRUD，横向 404
# ---------------------------------------------------------------------------


def _iso_env(monkeypatch, tmp_path):
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    monkeypatch.setenv("LUMIRSS_SESSION_SECURE_COOKIES", "false")
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", "")
    monkeypatch.setenv("LUMIRSS_SEARCH_SYNC_INTERVAL", "0")
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    import lumirss.middleware as middleware

    middleware._rate_windows.clear()
    middleware._login_failures.clear()
    return tmp_path


def _set_owner_password(db_path):
    async def run():
        database = Database(db_path / "lumi.sqlite")
        await database.migrate()
        store = AccountsStore(database)
        for row in await store.list_users(limit=50):
            if row["role"] == "owner":
                await store.set_password_hash(str(row["id"]), hash_password(PASSWORD))
                return

    asyncio.run(run())


def test_cross_user_device_isolation(monkeypatch, tmp_path):
    _iso_env(monkeypatch, tmp_path)
    with TestClient(app, base_url="http://lumirss.test") as client:
        _set_owner_password(tmp_path)
        owner_login = client.post(
            "/api/v1/auth/login",
            json={"username": "owner", "password": PASSWORD},
        )
        assert owner_login.status_code == 200
        owner_headers = {"cookie": owner_login.headers["set-cookie"].split(";")[0]}
        cookies = {}
        for username in ("alice", "bob"):
            invite = client.post(
                "/api/v1/admin/invites",
                json={"label": username},
                headers=owner_headers,
            )
            assert invite.status_code == 200, invite.text
            activation = client.post(
                "/api/v1/auth/activate",
                json={
                    "token": invite.json()["token"],
                    "username": username,
                    "password": PASSWORD,
                    "displayName": username,
                },
            )
            assert activation.status_code == 200, activation.text
            cookies[username] = activation.headers["set-cookie"].split(";")[0]

        def _get(who, path, **kw):
            return client.get(path, headers={"cookie": cookies[who]}, **kw)

        # member 可自建设备（无 owner 门槛）。
        alice_created = client.post(
            "/api/v1/obsidian/devices",
            json=_payload(label="Alice 的 iPhone"),
            headers={"cookie": cookies["alice"]},
        )
        assert alice_created.status_code == 201, alice_created.text
        alice_device = alice_created.json()

        bob_list = _get("bob", "/api/v1/obsidian/devices")
        assert bob_list.status_code == 200
        assert bob_list.json()["items"] == []

        # bob 侧的改/删都等价于「不存在」（路由即隔离，横向 404）。
        bob_update = client.put(
            f"/api/v1/obsidian/devices/{alice_device['id']}",
            json=_payload(),
            headers={"cookie": cookies["bob"]},
        )
        assert bob_update.status_code == 404
        bob_delete = client.delete(
            f"/api/v1/obsidian/devices/{alice_device['id']}",
            headers={"cookie": cookies["bob"]},
        )
        assert bob_delete.status_code == 404

        # alice 自己仍可删。
        alice_delete = client.delete(
            f"/api/v1/obsidian/devices/{alice_device['id']}",
            headers={"cookie": cookies["alice"]},
        )
        assert alice_delete.status_code == 204
        # 模板隔离：alice 存的模板 bob 读不到。
        client.put(
            "/api/v1/obsidian/export-template",
            json={"template": "{{title}}-alice"},
            headers={"cookie": cookies["alice"]},
        )
        bob_template = _get("bob", "/api/v1/obsidian/export-template")
        assert bob_template.json()["template"] == ""
