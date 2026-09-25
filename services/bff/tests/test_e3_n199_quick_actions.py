"""N199 自定义多步快捷操作 — 定义 CRUD + SAFE 白名单 + 步骤形状校验。

执行永远在 Web 端逐步走各动作的 NORMAL 端点（无服务端旁路）——本
套件验证服务端契约：词表白名单、2-3 步、params 键 ⊆ 允许集、上限；
白名单外动作（如改设置、删批注这类未列入 SAFE 的动作）被拒绝。
"""

import asyncio

from lumirss.main import app
from lumirss.quick_actions import QuickActionInvalid, validate_steps


def test_n199_validate_steps_whitelist_and_shape():
    # 合法：两步 SAFE 序列
    steps = validate_steps(
        [
            {"action": "add_to_queue", "params": {"entryRef": "e1.x"}},
            {"action": "open_reader"},
        ]
    )
    assert steps == [
        {"action": "add_to_queue", "params": {"entryRef": "e1.x"}},
        {"action": "open_reader", "params": {}},
    ]
    # 三步合法；未知 params 键拒绝；白名单外动作拒绝；步数越界拒绝
    assert len(validate_steps([
        {"action": "open_section", "params": {"section": "bookmarks"}},
        {"action": "open_search", "params": {"query": "rust"}},
        {"action": "open_reader"},
    ])) == 3
    for bad in (
        [{"action": "delete_all_annotations"}],  # 单步
        [{"action": "open_reader"}, {"action": "unknown_action"}],
        [{"action": "open_reader"}, {"action": "add_to_queue", "params": {"url": "x"}}],
        [{"action": "open_reader"}] * 4,
        "not-a-list",
    ):
        try:
            validate_steps(bad)
        except QuickActionInvalid:
            continue
        raise AssertionError(f"should have rejected: {bad!r}")


def test_n199_crud_roundtrip_and_validation(client):
    created = client.post(
        "/api/v1/quick-actions",
        json={
            "name": "加入队列并打开阅读器",
            "steps": [
                {"action": "add_to_queue", "params": {"entryRef": "e1.MDA"}},
                {"action": "open_reader"},
            ],
        },
    )
    assert created.status_code == 201, created.text
    action = created.json()
    assert action["steps"][0]["action"] == "add_to_queue"

    listing = client.get("/api/v1/quick-actions").json()
    assert [a["id"] for a in listing["items"]] == [action["id"]]

    # 白名单外动作 → 422（服务端不存任何可旁路 NORMAL 端点的定义）
    rejected = client.post(
        "/api/v1/quick-actions",
        json={
            "name": "危险动作",
            "steps": [
                {"action": "open_reader"},
                {"action": "delete_annotation", "params": {"id": "x"}},
            ],
        },
    )
    assert rejected.status_code == 422
    assert rejected.json()["error"]["type"] == "invalid_quick_action"

    # 步数 2-3
    too_few = client.post(
        "/api/v1/quick-actions",
        json={"name": "一步", "steps": [{"action": "open_reader"}]},
    )
    assert too_few.status_code == 422

    deleted = client.delete(f"/api/v1/quick-actions/{action['id']}")
    assert deleted.status_code == 204
    missing = client.delete(f"/api/v1/quick-actions/{action['id']}")
    assert missing.status_code == 404
    assert client.get("/api/v1/quick-actions").json()["items"] == []


PASSWORD = None


def test_n199_per_user_isolation(monkeypatch, tmp_path):
    """per-user 库：B 的快捷操作对 A 不可见（session 模式 + 真实路由）。"""
    import secrets as _secrets

    from fastapi.testclient import TestClient

    password = _secrets.token_urlsafe(16)
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    monkeypatch.setenv("LUMIRSS_SESSION_SECURE_COOKIES", "false")
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", "")

    import lumirss.middleware as middleware

    middleware._rate_windows.clear()
    middleware._login_failures.clear()

    async def _set_owner_password():
        from lumirss.accounts_store import AccountsStore, hash_password
        from lumirss.storage import Database

        database = Database(str(tmp_path / "lumi.sqlite"))
        await database.migrate()
        store = AccountsStore(database)
        for row in await store.list_users(limit=50):
            if row["role"] == "owner":
                await store.set_password_hash(str(row["id"]), hash_password(password))
                return

    def _run(coroutine):
        return asyncio.run(coroutine)

    with TestClient(app, base_url="http://lumirss.test") as session_client:
        _run(_set_owner_password())
        owner_login = session_client.post(
            "/api/v1/auth/login", json={"username": "owner", "password": password}
        )
        owner = {"cookie": owner_login.headers["set-cookie"].split(";")[0]}
        invite = session_client.post(
            "/api/v1/admin/invites", json={"label": "n199b"}, headers=owner
        )
        member = session_client.post(
            "/api/v1/auth/activate",
            json={"token": invite.json()["token"], "username": "n199b", "password": password},
        )
        member_headers = {"cookie": member.headers["set-cookie"].split(";")[0]}

        # B 创建动作
        created = session_client.post(
            "/api/v1/quick-actions",
            json={
                "name": "B 的操作",
                "steps": [
                    {"action": "open_section", "params": {"section": "bookmarks"}},
                    {"action": "open_reader"},
                ],
            },
            headers=member_headers,
        )
        assert created.status_code == 201
        b_action_id = created.json()["id"]

        # A 看不到 B 的动作，也删不掉
        owner_list = session_client.get("/api/v1/quick-actions", headers=owner).json()
        assert owner_list["items"] == []
        assert (
            session_client.delete(
                f"/api/v1/quick-actions/{b_action_id}", headers=owner
            ).status_code
            == 404
        )
        # B 自己仍可见、可删
        member_list = session_client.get(
            "/api/v1/quick-actions", headers=member_headers
        ).json()
        assert [a["id"] for a in member_list["items"]] == [b_action_id]
