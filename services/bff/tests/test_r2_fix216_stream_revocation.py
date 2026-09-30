"""FIX-216 — 停用账户的在途 SSE 流式连接必须随权限撤回终止。

场景（合成 A/B 会话）：成员 A 建立一条活跃的 agent SSE 订阅（线程带
运行中回合标记，生成器停在 delta 等待循环里）。管理员随后把 A 置为
paused（只改 users.status，不吊销会话行——比「吊销后再连」更严格的
前置）。断言：这条在途流在数秒内被服务端终止（终态 done/revoked），
而不是继续吐 keep-alive 直到 120s 空闲超时——不是只让「下一次 HTTP
请求」失败，是连接本身被终止。

测试直接驱动路由的流生成器：TestClient 的传输层会把流式响应缓冲到
结束才返回，观察不到「在途」行为；直接迭代 body_iterator 才能真实
复现长连接生命周期（鉴权上下文、cookie 与中间件装配完全一致）。
"""

import asyncio
import secrets
import time

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from lumirss.main import app


def _fake(prefix: str) -> str:
    return prefix + secrets.token_urlsafe(9)


def _run(coroutine):
    return asyncio.run(coroutine)


def _session_env(monkeypatch, tmp_path) -> str:
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    monkeypatch.setenv("LUMIRSS_SESSION_SECURE_COOKIES", "false")
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", "")
    from lumirss import middleware

    middleware._rate_windows.clear()
    middleware._login_failures.clear()
    middleware._implicit_owner_cache.clear()
    return str(tmp_path / "lumi.sqlite")


def _set_owner_password(db_path: str, password: str) -> str:
    async def go():
        from lumirss.accounts_store import AccountsStore, hash_password
        from lumirss.storage import Database

        database = Database(db_path)
        await database.migrate()
        store = AccountsStore(database)
        for row in await store.list_users(limit=50):
            if row["role"] == "owner":
                await store.set_password_hash(str(row["id"]), hash_password(password))
                return str(row["id"])
        raise AssertionError("owner row missing after startup migration")

    return _run(go())


def _cookie_headers(response) -> dict[str, str]:
    return {"cookie": response.headers["set-cookie"].split(";")[0]}


def _activate_member(client: TestClient, owner_headers, username: str, password: str):
    invite = client.post(
        "/api/v1/admin/invites", json={"label": username}, headers=owner_headers
    )
    assert invite.status_code == 200, invite.text
    activation = client.post(
        "/api/v1/auth/activate",
        json={
            "token": invite.json()["token"],
            "username": username,
            "password": password,
        },
    )
    assert activation.status_code == 200, activation.text
    cookie = activation.headers["set-cookie"].split(";")[0]
    return {"cookie": cookie}, cookie.split("=", 1)[1]


def _user_id(db_path: str, username: str) -> str:
    async def go():
        from lumirss.accounts_store import AccountsStore
        from lumirss.storage import Database

        database = Database(db_path)
        await database.migrate()
        rows = await AccountsStore(database).list_users(limit=50)
        return next(str(r["id"]) for r in rows if str(r["username"]) == username)

    return _run(go())


async def _pause_member(control_db, member_uid: str) -> None:
    from lumirss.accounts_store import AccountsStore

    assert await AccountsStore(control_db).set_user_status(member_uid, "paused")


def test_fix216_paused_member_stream_terminates(monkeypatch, tmp_path):
    db_path = _session_env(monkeypatch, tmp_path)
    password = _fake("pw-")
    member_name = "fx216" + secrets.token_hex(3)
    with TestClient(app, base_url="http://lumirss.test") as client:
        _set_owner_password(db_path, password)
        owner = client.post(
            "/api/v1/auth/login", json={"username": "owner", "password": password}
        )
        assert owner.status_code == 200
        owner_headers = _cookie_headers(owner)
        member_headers, member_token = _activate_member(
            client, owner_headers, member_name, password
        )
        member_uid = _user_id(db_path, member_name)

        thread = client.post("/api/v1/agent/threads", headers=member_headers)
        assert thread.status_code == 201, thread.text
        thread_id = thread.json()["id"]

        # 消息（replay 内容）与运行标记直接落库（POST /messages 会真的
        # 启动一个无 provider 回合并立刻终态，流就活不过守卫窗口了）。
        async def seed():
            from lumirss.agent_store import AgentStore
            from lumirss.storage import Database
            from lumirss.user_scope import RoutingDatabase, user_context

            routing = RoutingDatabase(db_path, Database(db_path).path.parent / "users")
            with user_context(member_uid):
                await routing.migrate()
                store = AgentStore(routing)
                await store.append_message(
                    thread_id, role="user", content={"text": "停用前的问题"}
                )
                await store.mark_run_processing(thread_id)

        _run(seed())

        # 直接驱动流生成器（与中间件一致的 scope：cookie + 已验证身份）。
        from lumirss.routers.agent import stream_events
        from lumirss.user_scope import load_user_env, user_context

        async def collect():
            request = Request(
                {
                    "type": "http",
                    "method": "GET",
                    "path": f"/api/v1/agent/threads/{thread_id}/events",
                    "query_string": b"after=0",
                    "headers": [(b"cookie", f"lumirss_session={member_token}".encode())],
                    "app": app,
                    "lumi_principal": {
                        "user_id": member_uid,
                        "role": "member",
                        "username": member_name,
                    },
                    "lumi_user_env": await load_user_env(
                        app.state, member_uid, "member", member_name
                    ),
                }
            )
            with user_context(member_uid):
                response = await stream_events(thread_id, request, 0)
                iterator = response.body_iterator.__aiter__()
                first = await asyncio.wait_for(iterator.__anext__(), 15)
                assert "event: message" in first, f"replay missing: {first[:80]}"

                # 权限撤回：成员置为 paused（会话行保留——状态规则本身
                # 就是边界；这正是「下一次请求才失败」的严格前 condition）。
                paused_at = time.monotonic()
                await _pause_member(app.state.control_db, member_uid)

                # 流必须在一个守卫 tick（1s）量级内终止并给出诚实终态，
                # 绝不允许继续无限吐 keep-alive。
                tail: list[str] = []
                terminated = False
                try:
                    for _ in range(8):
                        chunk = await asyncio.wait_for(iterator.__anext__(), 15)
                        text = chunk.decode() if isinstance(chunk, bytes) else str(chunk)
                        tail.append(text)
                        if "event: done" in text:
                            terminated = True
                            break
                except StopAsyncIteration:
                    terminated = True
                elapsed = time.monotonic() - paused_at
                return terminated, elapsed, "".join(tail)

        terminated, elapsed, tail = _run(collect())
        assert terminated, (
            "paused member's in-flight SSE stream kept emitting "
            f"without a terminal done (tail: {tail[-200:]})"
        )
        assert '"status": "revoked"' in tail or '"status":"revoked"' in tail, (
            f"terminal done must carry revoked status (tail: {tail[-200:]})"
        )
        assert elapsed < 10, f"termination took {elapsed:.1f}s — not a prompt guard kill"


@pytest.fixture()
def _drain_agent_tasks():
    yield
    import time as _time

    deadline = _time.time() + 10
    while app.state.agent_tasks and _time.time() < deadline:
        _time.sleep(0.05)
