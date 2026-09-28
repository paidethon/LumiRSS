"""R2 BFF4 admin/account-lifecycle FIX items — verifying evidence.

Covers FIX-042 / FIX-043 / FIX-035 / FIX-037 / FIX-039 / FIX-046 /
FIX-214 / FIX-215. Every test encodes the acceptance rule from its fix
item against the real store / routes. Where the described defect does
NOT reproduce on the baseline (the domain has had several security
passes), the passing run IS the BASELINE_OK evidence; mutation checks
(temporarily removing a guard → test turns red → restored) prove the
tests have teeth. All credentials are runtime-generated fakes.

Schema honesty (FIX-042/043 context): the invites table has NO
max_uses/remnant column — every invite is strictly single-use and the
"limit-N" construct is a batch of N independent one-time tokens. The
concurrency item is therefore verified in its real shape: per-token
test-and-set single-winner + batch-of-2 exactly-2.
"""

import asyncio
import os
import secrets as _secrets
import time

import pytest
from fastapi.testclient import TestClient

import lumirss.middleware as middleware
from lumirss.main import app
from lumirss.storage import Database


def _fake(prefix: str) -> str:
    return prefix + _secrets.token_urlsafe(9)


def _run(coroutine):
    return asyncio.run(coroutine)


def _session_env(monkeypatch, tmp_path) -> str:
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    monkeypatch.setenv("LUMIRSS_SESSION_SECURE_COOKIES", "false")
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", "")
    middleware._rate_windows.clear()
    middleware._login_failures.clear()
    middleware._implicit_owner_cache.clear()
    return str(tmp_path / "lumi.sqlite")


def _set_owner_password(db_path: str, password: str) -> str:
    """Give the startup-migration owner account a known (random) password."""

    async def go():
        from lumirss.accounts_store import AccountsStore, hash_password

        database = Database(db_path)
        await database.migrate()
        store = AccountsStore(database)
        for row in await store.list_users(limit=50):
            if row["role"] == "owner":
                await store.set_password_hash(str(row["id"]), hash_password(password))
                return str(row["id"])
        raise AssertionError("owner row missing after startup migration")

    return _run(go())


def _login(client: TestClient, *, username: str = "owner", password: str):
    return client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )


def _cookie_headers(response) -> dict[str, str]:
    return {"cookie": response.headers["set-cookie"].split(";")[0]}


def _step_up(client, headers, password: str) -> dict[str, str]:
    minted = client.post(
        "/api/v1/admin/step-up", json={"password": password}, headers=headers
    )
    assert minted.status_code == 200, minted.text
    return {**headers, "X-Lumi-Step-Up": minted.json()["token"]}


def _activate_member(client, owner_headers, username: str, password: str, extra=None):
    """Admin invite + activation; returns (headers, body)."""
    invite = client.post(
        "/api/v1/admin/invites", json={"label": username}, headers=owner_headers
    )
    assert invite.status_code == 200, invite.text
    body = {
        "token": invite.json()["token"],
        "username": username,
        "password": password,
    }
    body.update(extra or {})
    activation = client.post("/api/v1/auth/activate", json=body)
    return activation, body


# ---------------------------------------------------------------------------
# FIX-042 — 邀请消费并发：单 token 测试置位单赢家；「限 2 个名额」=
# 2 枚独立一次性 token 的批次，并发兑换恰好 2 成功（schema 无 max_uses
# 列——剩余次数不存在单独的计数行，因此没有可被竞态超额更新的计数）。
# FIX-213 已钉住 recovery kind；这里补 signup kind 与批次口径。


def test_fix042_concurrent_signup_redeem_single_winner_per_token(monkeypatch, tmp_path):
    from lumirss.accounts_store import AccountsStore, InviteInvalid

    db_path = str(tmp_path / "lumi.sqlite")
    monkeypatch.setenv("LUMIRSS_DB_PATH", db_path)

    async def setup():
        database = Database(db_path)
        await database.migrate()
        store = AccountsStore(database)
        raw, _invite = await store.create_invite(created_by="test", ttl_hours=1)
        return raw

    raw = _run(setup())

    async def redeem_all():
        database = Database(db_path)
        await database.migrate()
        store = AccountsStore(database)
        return await asyncio.gather(
            *[store.redeem_invite(raw) for _ in range(8)], return_exceptions=True
        )

    outcomes = _run(redeem_all())
    winners = [o for o in outcomes if not isinstance(o, BaseException)]
    losers = [o for o in outcomes if isinstance(o, InviteInvalid)]
    assert len(winners) == 1, [repr(o) for o in outcomes]
    assert len(losers) == 7

    async def used_rows():
        database = Database(db_path)
        await database.migrate()
        rows = await database.fetch_all(
            "SELECT used_at, used_by FROM invites WHERE used_at IS NOT NULL", ()
        )
        return rows

    rows = _run(used_rows())
    # 恰好 1 行被消费（used_by 的绑定由激活路由的 mark_invite_used_by
    # 完成——store 直接兑换时 signup 无 target_user，保持 NULL 是契约）。
    assert len(rows) == 1


def test_fix042_limit_two_batch_concurrent_exactly_two_succeed(monkeypatch, tmp_path):
    """限 2 名额 = 2 枚独立一次性邀请。8 个并发激活（每个 token 4 个
    竞争者）→ 恰好 2 成功、6 个干净的 InviteInvalid，库里恰好 2 行
    used——任何剩余次数超卖都不可能（没有共享计数可被双写）。"""
    from lumirss.accounts_store import AccountsStore, InviteInvalid

    db_path = str(tmp_path / "lumi.sqlite")
    monkeypatch.setenv("LUMIRSS_DB_PATH", db_path)

    async def setup():
        database = Database(db_path)
        await database.migrate()
        store = AccountsStore(database)
        raw_a, _ = await store.create_invite(created_by="test", ttl_hours=1)
        raw_b, _ = await store.create_invite(created_by="test", ttl_hours=1)
        return raw_a, raw_b

    raw_a, raw_b = _run(setup())
    tokens = [raw_a] * 4 + [raw_b] * 4

    async def redeem_all():
        database = Database(db_path)
        await database.migrate()
        store = AccountsStore(database)
        return await asyncio.gather(
            *[store.redeem_invite(token) for token in tokens],
            return_exceptions=True,
        )

    outcomes = _run(redeem_all())
    winners = [o for o in outcomes if not isinstance(o, BaseException)]
    losers = [o for o in outcomes if isinstance(o, InviteInvalid)]
    assert len(winners) == 2, [repr(o) for o in outcomes]
    assert len(losers) == 6

    async def used_rows():
        database = Database(db_path)
        await database.migrate()
        return await database.fetch_all(
            "SELECT id FROM invites WHERE used_at IS NOT NULL", ()
        )

    assert len(_run(used_rows())) == 2


# ---------------------------------------------------------------------------
# FIX-043 — 邀请有效期全程 UTC epoch：created_at/TTL 的纯 epoch 算术，
# 兑换判定只看服务器时钟；展示渲染固定 UTC（+00:00）。极端时区
# （UTC+14 / UTC-12）进程下，过期边界前一秒成功、边界当刻失效——
# 不提前失效、也不多用一天。


def _with_tz(name: str):
    """Context: switch process local timezone (any hidden localtime use
    in the boundary comparisons would then visibly shift results)."""

    class _Tz:
        def __enter__(self):
            self._old = os.environ.get("TZ")
            os.environ["TZ"] = name
            time.tzset()

        def __exit__(self, *exc):
            if self._old is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = self._old
            time.tzset()
            return False

    return _Tz()


@pytest.mark.parametrize("zone", ["Pacific/Kiritimati", "Etc/GMT+12"])  # UTC+14 / UTC-12
def test_fix043_invite_expiry_utc_epoch_boundary_is_timezone_free(
    monkeypatch, tmp_path, zone
):
    import lumirss.accounts_store as accounts_module
    from lumirss.accounts_store import AccountsStore, InviteInvalid
    from lumirss.routers.admin import _iso

    db_path = str(tmp_path / "lumi.sqlite")
    monkeypatch.setenv("LUMIRSS_DB_PATH", db_path)
    with _with_tz(zone):
        clock = {"now": 1_800_000_000}
        monkeypatch.setattr(accounts_module, "_now", lambda: clock["now"])

        async def go():
            database = Database(db_path)
            await database.migrate()
            store = AccountsStore(database)
            raw, invite = await store.create_invite(created_by="test", ttl_hours=1)
            created_at = int(invite["created_at"])
            expires_at = int(invite["expires_at"])
            # 纯 epoch 算术：与本地时区无关。
            assert expires_at == created_at + 3600
            # 展示渲染固定 UTC。
            assert _iso(expires_at).endswith("+00:00")
            # 边界前一秒：有效。
            clock["now"] = expires_at - 1
            winner = await store.redeem_invite(raw)
            assert int(winner["expires_at"]) == expires_at
            # 第二枚：它自己的边界当刻 → 失效（UTC+14 不提前、
            # UTC-12 不宽限）。
            raw2, invite2 = await store.create_invite(created_by="test", ttl_hours=1)
            expires2 = int(invite2["expires_at"])
            assert expires2 == int(invite2["created_at"]) + 3600
            clock["now"] = expires2
            try:
                await store.redeem_invite(raw2)
            except InviteInvalid:
                pass
            else:
                raise AssertionError("expired invite redeemed at boundary")

        _run(go())


# ---------------------------------------------------------------------------
# FIX-035 — 最后一个 owner 不可删除/禁用/降权：store 层 SQL 守卫
# （绕过 HTTP 路由检查的任何调用方也写不动 owner 行）+ HTTP 面
# owner 不可定位（pause/resume/role/background-pause）+ API 永远
# 铸不出第二个 owner（role pattern ^member|admin$）。物理删除路径
# 不存在（test_e3_n190_no_auto_deletion_path_exists 已钉住）。


def test_fix035_store_guards_owner_row_is_unwritable(monkeypatch, tmp_path):
    from lumirss.accounts_store import AccountsStore, hash_password

    db_path = str(tmp_path / "lumi.sqlite")
    monkeypatch.setenv("LUMIRSS_DB_PATH", db_path)
    password = _fake("pw-")

    async def go():
        database = Database(db_path)
        await database.migrate()
        store = AccountsStore(database)
        # 与 owner_migration 同一创建路径（此处不经 lifespan）。
        owner = await store.create_user(
            username="owner",
            password_hash=hash_password(password),
            role="owner",
        )
        owner_id = str(owner["id"])
        await store.set_password_hash(owner_id, hash_password(password))

        # 禁用：False，状态不变。
        assert await store.set_user_status(owner_id, "paused") is False
        assert (await store.get_user(owner_id))["status"] == "active"
        # 「恢复」同一路径也写不动 owner。
        assert await store.set_user_status(owner_id, "active") is False
        # 降权：False，角色不变。
        assert await store.set_user_role(owner_id, "member") is False
        assert (await store.get_user(owner_id))["role"] == "owner"
        # 自助停用（密码正确）：None——owner 无 pending_deletion 状态。
        assert await store.request_deactivation(owner_id, password) is None
        # 始终至少一个可用管理身份。
        owner = await store.get_user(owner_id)
        assert owner["role"] == "owner" and owner["status"] == "active"

    _run(go())


def test_fix035_owner_untargetable_on_every_http_lifecycle_path(monkeypatch, tmp_path):
    db_path = _session_env(monkeypatch, tmp_path)
    password = _fake("pw-")
    with TestClient(app, base_url="http://lumirss.test") as client:
        owner_id = _set_owner_password(db_path, password)
        owner = _login(client, password=password)
        assert owner.status_code == 200, owner.text
        owner_headers = _cookie_headers(owner)

        paused = client.post(
            f"/api/v1/admin/users/{owner_id}/pause", headers=owner_headers
        )
        assert paused.status_code == 403
        resumed = client.post(
            f"/api/v1/admin/users/{owner_id}/resume", headers=owner_headers
        )
        assert resumed.status_code == 403
        background_paused = client.post(
            f"/api/v1/admin/users/{owner_id}/background-pause",
            json={"reason": "nope"},
            headers=owner_headers,
        )
        assert background_paused.status_code == 403
        demoted = client.post(
            f"/api/v1/admin/users/{owner_id}/role",
            json={"role": "member"},
            headers=owner_headers,
        )
        assert demoted.status_code == 403

        # API 永远铸不出第二个 owner：role=owner 是 422（body 校验）。
        second_owner = client.post(
            f"/api/v1/admin/users/{owner_id}/role",
            json={"role": "owner"},
            headers=owner_headers,
        )
        assert second_owner.status_code == 422

        # 仍然恰好一个 owner、状态 active——可用管理身份仍在。
        users = client.get("/api/v1/admin/users", headers=owner_headers).json()
        owners = [u for u in users if u["role"] == "owner"]
        assert len(owners) == 1 and owners[0]["status"] == "active"


# ---------------------------------------------------------------------------
# FIX-037 — 批量用户操作：本 API 不存在任何批量用户操作端点（每个
# 生命周期操作都是单目标 /users/{user_id}/*）——「全部成功但部分
# 失败」的聚合谎报没有载体。测试钉住路由面：无 bulk 路径、无
# 多 id body。


def test_fix037_no_bulk_user_operation_endpoint_exists():
    paths = app.openapi()["paths"]
    admin_paths = [p for p in paths if p.startswith("/api/v1/admin")]
    assert not [p for p in admin_paths if "bulk" in p.lower()]
    # 每个用户变更端点都是单目标 {user_id}；users 集合端点只有只读 GET。
    user_writes = [p for p in admin_paths if "/users/" in p]
    assert user_writes, "admin user routes missing?"
    for path in user_writes:
        assert "{user_id}" in path, f"non-single-target user route: {path}"
    assert set(paths["/api/v1/admin/users"].keys()) == {"get"}


# ---------------------------------------------------------------------------
# FIX-039 — 配额单位/上下限/服务端校验一致：字段名即单位
# （maxSources=订阅来源个数、aiQuotaPerDay=AI 调用次数/天）；界内
# 1..10000 / 1..100000 两层（Pydantic 与 store）一致；0 一律拒绝，
# 未设限 = 键缺省/DELETE 清除——0 与无限额可区分。


@pytest.fixture()
def quota_env(monkeypatch, tmp_path):
    db_path = _session_env(monkeypatch, tmp_path)
    password = _fake("pw-")
    member_name = "q039a" + _secrets.token_hex(3)
    with TestClient(app, base_url="http://lumirss.test") as client:
        _set_owner_password(db_path, password)
        owner = _login(client, password=password)
        assert owner.status_code == 200, owner.text
        owner_headers = _cookie_headers(owner)
        activation, _body = _activate_member(
            client, owner_headers, member_name, password
        )
        assert activation.status_code == 200, activation.text
        users = client.get("/api/v1/admin/users", headers=owner_headers).json()
        member_id = next(str(u["id"]) for u in users if u["username"] == member_name)
        yield client, owner_headers, member_id, password


def test_fix039_quota_bounds_consistent_zero_is_not_unlimited(quota_env):
    client, owner_headers, member_id, password = quota_env

    def put(body):
        return client.put(
            f"/api/v1/admin/users/{member_id}/quota",
            json=body,
            headers=_step_up(client, owner_headers, password),
        )

    # 0 与负数：两层校验一致拒绝——0 不是「无限额」。
    for bad in ({"maxSources": 0}, {"maxSources": -1}, {"aiQuotaPerDay": 0}):
        response = put(bad)
        assert response.status_code == 422, (bad, response.text)
    # 上界恰好一致：10000 / 100000 接受，超一即 422。
    ceiling = put({"maxSources": 10_000, "aiQuotaPerDay": 100_000})
    assert ceiling.status_code == 200, ceiling.text
    assert ceiling.json()["caps"] == {"maxSources": 10000, "aiQuotaPerDay": 100000}
    assert put({"maxSources": 10_001}).status_code == 422
    assert put({"aiQuotaPerDay": 100_001}).status_code == 422
    # 布尔不是整数（bool 不得伪装成 1）。
    assert put({"maxSources": True}).status_code == 422
    # 缺省键 = 清除该上限（→ 无限额），不是 0。
    lowered = put({"maxSources": 3})
    assert lowered.status_code == 200
    assert lowered.json()["caps"] == {"maxSources": 3}
    # DELETE = 显式回到无限额，与「设为 0」（拒绝）可区分。
    cleared = client.delete(
        f"/api/v1/admin/users/{member_id}/quota",
        headers=_step_up(client, owner_headers, password),
    )
    assert cleared.status_code == 200
    assert cleared.json()["caps"] == {}


# ---------------------------------------------------------------------------
# FIX-046 — 自助资料修改字段白名单：不存在任何 self-profile 写端点；
# displayName 只在激活/注册时设定（role 服务端硬编码 member）；
# /api/v1/me 只有停用（extra=forbid）与活动清除。任何 role/quota/
# status 字段在激活体里都是被忽略的多余字段，绝不落库。


def test_fix046_no_self_profile_write_route_and_smuggled_fields_ignored(
    monkeypatch, tmp_path
):
    db_path = _session_env(monkeypatch, tmp_path)
    password = _fake("pw-")
    with TestClient(app, base_url="http://lumirss.test") as client:
        _set_owner_password(db_path, password)
        owner = _login(client, password=password)
        owner_headers = _cookie_headers(owner)

        me_paths = {
            path: set(methods)
            for path, methods in app.openapi()["paths"].items()
            if path.startswith("/api/v1/me")
        }
        # 无 PATCH/PUT 资料端点；me 面只有停用 + 活动清除。
        for path, methods in me_paths.items():
            assert not ({"patch", "put"} & methods), (path, methods)
        assert me_paths == {
            "/api/v1/me/deactivation-request": {"get", "post"},
            "/api/v1/me/activity-purge": {"post"},
            "/api/v1/me/activity-purge/preview": {"get"},
        }
        # 已知路径上的错误方法：中间件 401（假会话）或路由 405（真会话）
        # ——总之不存在可达的资料写入处理器（OpenAPI 面已证明无此路由）。
        patch_attempt = client.patch(
            "/api/v1/me/deactivation-request",
            json={"role": "owner"},
            headers={"cookie": "lumirss_session=fake"},
        )
        assert patch_attempt.status_code in (401, 405)
        # 停用体 extra=forbid：role/quota 字段 → 422，绝不静默接受
        #（用真会话穿过鉴权中间件，验证到 body 校验层）。先用无害体
        # 建一个真成员会话。
        member_name = "p046b" + _secrets.token_hex(3)
        activation0, _b = _activate_member(client, owner_headers, member_name, password)
        assert activation0.status_code == 200, activation0.text
        member_headers = _cookie_headers(activation0)
        smuggled_deact = client.post(
            "/api/v1/me/deactivation-request",
            json={"password": password, "role": "owner", "maxSources": 1},
            headers=member_headers,
        )
        assert smuggled_deact.status_code == 422

        # 激活体夹带 role/quota/status：多余字段被忽略，身份服务端派生。
        smuggle_name = "p046a" + _secrets.token_hex(3)
        activation, _body = _activate_member(
            client,
            owner_headers,
            smuggle_name,
            password,
            extra={
                "role": "owner",
                "maxSources": 999999,
                "aiQuotaPerDay": 999999,
                "status": "active",
            },
        )
        assert activation.status_code == 200, activation.text
        member_headers = _cookie_headers(activation)
        who = client.get("/api/v1/auth/session", headers=member_headers).json()
        assert who["role"] == "member"
        users = client.get("/api/v1/admin/users", headers=owner_headers).json()
        row = next(u for u in users if u["username"] == smuggle_name)
        assert row["role"] == "member" and row["status"] == "active"
        quota = client.get(
            f"/api/v1/admin/users/{row['id']}/quota", headers=owner_headers
        ).json()
        assert quota["caps"] == {} and quota["backgroundPaused"] is False


# ---------------------------------------------------------------------------
# FIX-214 — 登录名单一规范化契约：strip().lower() 于所有入口；存储
# 仅限 ASCII 小写（^a-z0-9][a-z0-9_-]{2,31}$）——"Alice"/"alice" 不可能
# 并存（创建即归一 + UNIQUE COLLATE NOCASE 兜底）；全角 Ａ 不做 NFKC
# 折叠而是直接拒绝（非 ASCII 永不入库），全角/半角对永不互相别名。


def test_fix214_username_one_normalization_contract(monkeypatch, tmp_path):
    db_path = _session_env(monkeypatch, tmp_path)
    password = _fake("pw-")
    with TestClient(app, base_url="http://lumirss.test") as client:
        _set_owner_password(db_path, password)
        owner = _login(client, password=password)
        owner_headers = _cookie_headers(owner)

        # 混合大小写 + 空白：激活时归一为小写存储。
        activation, _body = _activate_member(client, owner_headers, " Alice ", password)
        assert activation.status_code == 200, activation.text
        users = client.get("/api/v1/admin/users", headers=owner_headers).json()
        assert [u["username"] for u in users if u["username"] == "alice"]
        assert not [u for u in users if u["username"] != u["username"].lower()]

        # 登录任意大小写/空白都解析到同一账户。
        for variant in ("ALICE", "alice", " Alice ", "aLiCe"):
            assert _login(client, username=variant, password=password).status_code == 200

        # 同一小写名的第二次创建 → 占用（先归一再判重）。
        again, _b = _activate_member(client, owner_headers, "ALICE", password)
        assert again.status_code == 400
        assert again.json()["error"]["type"] == "invalid_username"

        # 全角 Ａｌｉｃｅ：拒绝入库（不是 NFKC 折叠成 alice）。
        fullwidth, _b = _activate_member(
            client, owner_headers, "ＡＬＩＣＥ", password
        )
        assert fullwidth.status_code == 400
        assert fullwidth.json()["error"]["type"] == "invalid_username"
        # 全角对不与半角互相别名：另一个全角名被拒后，半角名仍可创建。
        fw2, _b = _activate_member(client, owner_headers, "ＴＥＳＴ０１", password)
        assert fw2.status_code == 400
        ok, _b = _activate_member(client, owner_headers, "test01", password)
        assert ok.status_code == 200, ok.text

    # store 层同一契约：非 ASCII / 大写直接 InvalidUsername。
    from lumirss.accounts_store import AccountsStore, InvalidUsername, hash_password

    async def go():
        database = Database(db_path)
        await database.migrate()
        store = AccountsStore(database)
        for bad in ("Alice", "Ａｌｉｃｅ", "café"):
            try:
                await store.create_user(
                    username=bad, password_hash=hash_password(password), role="member"
                )
            except InvalidUsername:
                continue
            raise AssertionError(f"non-canonical username accepted: {bad!r}")

    _run(go())


# ---------------------------------------------------------------------------
# FIX-215 — 设备名当文本 + 限长：会话面的 deviceLabel 是服务端从 UA
# 解析的枚举式标签（永不回传原始 UA 作为标签），原始 UA 入库截断
# 200 字符、列表出参截断 64；reading-progress 的 deviceLabel 用户
# 自报、Pydantic 限 32、原样文本往返（无 HTML 语义，字面量进出）。


def test_fix215_session_device_label_derived_and_user_agent_bounded(
    monkeypatch, tmp_path
):
    from lumirss.auth_store import AuthStore

    db_path = _session_env(monkeypatch, tmp_path)
    password = _fake("pw-")
    member_name = "d215a" + _secrets.token_hex(3)
    with TestClient(app, base_url="http://lumirss.test") as client:
        _set_owner_password(db_path, password)
        owner = _login(client, password=password)
        owner_headers = _cookie_headers(owner)
        activation, _body = _activate_member(client, owner_headers, member_name, password)
        assert activation.status_code == 200, activation.text
        member_id = None
        users = client.get("/api/v1/admin/users", headers=owner_headers).json()
        member_id = next(
            str(u["id"]) for u in users if u["username"] == member_name
        )

        hostile = '<img src=x onerror="alert(1)"><script>pwn</script>' + "A" * 240
        assert len(hostile) > 200

        async def mint():
            database = Database(db_path)
            await database.migrate()
            store = AuthStore(database)
            return await store.create_session(
                7, user_agent=hostile, user_id=member_id
            )

        _raw, _expires = _run(mint())

        async def stored_row():
            database = Database(db_path)
            await database.migrate()
            return await database.fetch_one(
                "SELECT user_agent, device_label FROM auth_sessions WHERE user_agent LIKE '%<img src=x%'",
                (),
            )

        row = _run(stored_row())
        assert row is not None
        # 入库限长：200 字符整（截断，不是拒绝也永不加长）。
        assert row["user_agent"] == hostile[:200]
        assert len(row["user_agent"]) == 200
        # 设备标签是服务端解析的枚举文本，绝不含原始 UA 片段。
        assert "<img" not in row["device_label"]
        assert row["device_label"] == "浏览器/未知平台"

        # 会话列表出参：UA 截断 64，标签仍是脱敏枚举文本。
        async def listed():
            database = Database(db_path)
            await database.migrate()
            store = AuthStore(database)
            return await store.list_sessions(user_id=member_id, limit=20)

        sessions = _run(listed())
        target = next(s for s in sessions if (s["userAgent"] or "").startswith("<img"))
        assert target["userAgent"] == hostile[:64]
        assert target["deviceLabel"] == "浏览器/未知平台"

        # 登录事件面的标签同样脱敏。
        async def event():
            database = Database(db_path)
            await database.migrate()
            store = AuthStore(database)
            kind = await store.record_login_event(
                user_id=member_id, user_agent=hostile
            )
            events = await store.list_login_events(user_id=member_id, limit=5)
            return kind, events

        kind, events = _run(event())
        assert kind in ("new_device", "login")
        assert events and events[0]["deviceLabel"] == "浏览器/未知平台"


def test_fix215_reading_progress_device_label_literal_text_length_capped(client):
    label = "<img src=x onerror=alert(1)>abcd"  # 恰 32 字符
    assert len(label) == 32
    put = client.put(
        "/api/v1/reading-progress",
        json={"entryRef": "e215.a", "paraId": "p-1", "pct": 10.0, "deviceLabel": label},
    )
    assert put.status_code == 204, put.text
    listing = client.get("/api/v1/reading-progress").json()["items"]
    row = next(item for item in listing if item["entryRef"] == "e215.a")
    # 字面量进出：存的是文本，取回逐字符相同（无任何转写/剥除）。
    assert row["deviceLabel"] == label
    # 超长（33 字符）→ 422，输入侧限长。
    too_long = label + "x"
    assert (
        client.put(
            "/api/v1/reading-progress",
            json={
                "entryRef": "e215.b",
                "paraId": "p-1",
                "pct": 10.0,
                "deviceLabel": too_long,
            },
        ).status_code
        == 422
    )
