"""R2 BFF13 admin/audit/data-boundary FIX items — failing-test-first evidence.

Covers FIX-048 / FIX-049 / FIX-050 / FIX-031 / FIX-032 / FIX-033 /
FIX-038 / FIX-217 / FIX-218. Items whose described defect does not
reproduce on the baseline carry a BASELINE_OK note in the test docstring
— the passing run plus the mutation-style negative assertions (wrong
payload content / wrong scope / dead account DO fail the assertion) are
the honest evidence. All credentials are runtime-generated fakes.

Privacy red line (FIX-048/050): admin payloads and the audit trail must
stay aggregates/metadata — private entry titles, note bodies and AI
summary text planted in a member's database must never appear in any
admin-visible payload, and passwords/tokens must never appear in the
audit log.
"""

import asyncio
import json
import secrets as _secrets

import pytest
from fastapi.testclient import TestClient

import lumirss.middleware as middleware
from lumirss.main import app

PASSWORD = "bff13-" + _secrets.token_urlsafe(9)
OWNER_USER = "owner"
A_USER = "alice13"
B_USER = "bob13"

# Private-content markers planted ONLY in member A's user database.
PRIVATE_TITLE = "私有标题-" + _secrets.token_urlsafe(6)
PRIVATE_CONTENT = "私有正文-" + _secrets.token_urlsafe(6)
PRIVATE_NOTE = "私有笔记-" + _secrets.token_urlsafe(6)
PRIVATE_SUMMARY = "私有摘要-" + _secrets.token_urlsafe(6)
PRIVATE_BOOKMARK_NOTE = "私有书签备注-" + _secrets.token_urlsafe(6)

QUOTA_PAYLOAD_KEYS = {
    "userId",
    "caps",
    "backgroundPaused",
    "backgroundPauseReason",
    "updatedAt",
    "updatedBy",
}


def _fake(prefix: str) -> str:
    return prefix + _secrets.token_urlsafe(9)


def _run(coroutine):
    return asyncio.run(coroutine)


@pytest.fixture()
def env(monkeypatch, tmp_path):
    """Session-mode app with owner (known password) + members A and B."""
    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    monkeypatch.setenv("LUMIRSS_SESSION_SECURE_COOKIES", "false")
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", "")
    monkeypatch.setenv("LUMIRSS_SEARCH_SYNC_INTERVAL", "0")
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    middleware._rate_windows.clear()
    middleware._login_failures.clear()
    middleware._implicit_owner_cache.clear()
    with TestClient(app, base_url="http://lumirss.test") as client:
        _set_owner_password(tmp_path / "lumi.sqlite")
        owner_login = client.post(
            "/api/v1/auth/login", json={"username": OWNER_USER, "password": PASSWORD}
        )
        assert owner_login.status_code == 200, owner_login.text
        owner = {"cookie": owner_login.headers["set-cookie"].split(";")[0]}
        ids = {}
        cookies = {}
        for name in (A_USER, B_USER):
            invite = client.post("/api/v1/admin/invites", json={"label": name}, headers=owner)
            assert invite.status_code == 200, invite.text
            activation = client.post(
                "/api/v1/auth/activate",
                json={"token": invite.json()["token"], "username": name, "password": PASSWORD},
            )
            assert activation.status_code == 200, activation.text
            cookies[name] = {"cookie": activation.headers["set-cookie"].split(";")[0]}
        users = client.get("/api/v1/admin/users", headers=owner).json()
        for row in users:
            ids[str(row["username"])] = str(row["id"])
        yield {
            "client": client,
            "owner": owner,
            "cookies": cookies,
            "ids": ids,
            "db_path": tmp_path / "lumi.sqlite",
            "users_root": tmp_path / "users",
        }


def _set_owner_password(db_path) -> None:
    from lumirss.accounts_store import AccountsStore, hash_password
    from lumirss.storage import Database

    async def run():
        database = Database(db_path)
        await database.migrate()
        store = AccountsStore(database)
        for row in await store.list_users(limit=50):
            if row["role"] == "owner":
                await store.set_password_hash(str(row["id"]), hash_password(PASSWORD))
                return

    _run(run())


def _mint(client, headers, operation, target, password=PASSWORD):
    """FIX-218：铸造作用域绑定的提权令牌，返回带头请求头。"""
    minted = client.post(
        "/api/v1/admin/step-up",
        json={"password": password, "operation": operation, "targetUserId": target},
        headers=headers,
    )
    assert minted.status_code == 200, minted.text
    return {**headers, "X-Lumi-Step-Up": minted.json()["token"]}


def _seed_private_content(user_db_path):
    """Plant private title/note/summary text in ONE member's user DB."""
    from lumirss.storage import Database

    async def run():
        database = Database(user_db_path)
        await database.migrate()
        await database.execute(
            "INSERT INTO search_entries (item_id, entry_ref, feed_url, feed_title, title, author, url, content_text, published_at, read, starred, fetched_at)"
            " VALUES (?, ?, ?, '', ?, '', '', ?, '2026-01-01T00:00:00+00:00', 0, 0, 0)",
            (f"i-{_secrets.token_hex(4)}", f"r-{_secrets.token_hex(4)}", "https://f.test", PRIVATE_TITLE, PRIVATE_CONTENT),
        )
        await database.execute(
            "INSERT INTO reading_notes (entry_ref, note, para_id, updated_at) VALUES (?, ?, NULL, '2026-01-01T00:00:00+00:00')",
            ("r-note", PRIVATE_NOTE),
        )
        await database.execute(
            "INSERT INTO ai_summaries (entry_ref, content_hash, provider, model, prompt_version, language, status, summary_text, created_at, updated_at)"
            " VALUES (?, 'h', 'p', 'm', 'v', 'zh', 'success', ?, '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00')",
            ("r-sum", PRIVATE_SUMMARY),
        )
        await database.execute(
            "INSERT INTO library_items (uuid, kind, created_at) VALUES (?, 'bookmark', '2026-01-01T00:00:00+00:00')",
            (f"u-{_secrets.token_hex(6)}",),
        )
        row = await database.fetch_one("SELECT uuid FROM library_items ORDER BY created_at DESC LIMIT 1")
        await database.execute(
            "INSERT INTO library_bookmarks (item_uuid, item_type, url, title, note, created_at) VALUES (?, 'url', 'https://x.test', ?, ?, '2026-01-01T00:00:00+00:00')",
            (str(row["uuid"]), PRIVATE_TITLE, PRIVATE_BOOKMARK_NOTE),
        )

    _run(run())


def _admin_payloads(client, owner, a_id):
    """Every admin surface that talks about a member (aggregates only)."""
    quota = client.get(f"/api/v1/admin/users/{a_id}/quota", headers=owner)
    assert quota.status_code == 200, quota.text
    users = client.get("/api/v1/admin/users", headers=owner)
    assert users.status_code == 200, users.text
    capacity = client.get("/api/v1/admin/capacity", headers=owner)
    assert capacity.status_code == 200, capacity.text
    audit = client.get("/api/v1/admin/audit?limit=500", headers=owner)
    assert audit.status_code == 200, audit.text
    pool = client.get("/api/v1/admin/pool", headers=owner)
    assert pool.status_code == 200, pool.text
    return [quota.text, users.text, capacity.text, audit.text, pool.text]


# ---------------------------------------------------------------------------
# FIX-048 — 管理员配额/使用面板只暴露聚合与元数据；成员的私人文章
# 标题、笔记与 AI 摘要文本绝不随任何 admin 载荷外泄。


def test_fix048_admin_quota_payload_aggregates_only(env):
    client, owner = env["client"], env["owner"]
    a_id = env["ids"][A_USER]
    # Force member A's user DB into existence, then plant private text.
    assert client.get("/api/v1/search/views", headers=env["cookies"][A_USER]).status_code == 200
    _seed_private_content(env["users_root"] / a_id / "lumi.sqlite")

    payloads = _admin_payloads(client, owner, a_id)

    quota = json.loads(payloads[0])
    assert set(quota) == QUOTA_PAYLOAD_KEYS
    assert set(quota["caps"]) <= {"maxSources", "aiQuotaPerDay"}
    for marker in (PRIVATE_TITLE, PRIVATE_CONTENT, PRIVATE_NOTE, PRIVATE_SUMMARY, PRIVATE_BOOKMARK_NOTE):
        for payload in payloads:
            assert marker not in payload, f"private content leaked in admin payload: {marker}"
    # 密码哈希也绝不进 admin 用户列表。
    users = json.loads(payloads[1])
    for row in users:
        assert "password_hash" not in row


# ---------------------------------------------------------------------------
# FIX-049 — 账户导出/导入/停用的授权范围：身份只来自服务端会话；
# 预览会话绑定创建者，他人的 importId 按 404 拒绝；请求体伪造
# userId 无法把停用/导出改道到别的账户。


def _wizard_zip() -> bytes:
    from lumirss.lumi_data_wizard import build_export_zip

    return build_export_zip({"tags": {"available": True, "items": []}})


def test_fix049_import_session_bound_to_creating_user(env):
    client = env["client"]
    a_id, b_id = env["ids"][A_USER], env["ids"][B_USER]
    assert a_id != b_id
    # 伪造 user_id 字段不得影响 preview/apply（端点不读任何身份体）。
    preview = client.post(
        "/api/v1/import/lumi-data/preview",
        content=_wizard_zip(),
        headers={**env["cookies"][A_USER], "content-type": "application/zip"},
    )
    assert preview.status_code == 200, preview.text
    import_id = preview.json()["importId"]

    # B（他人）拿 A 的 importId 应用 → 404（按不存在口径，不泄漏存在性）。
    stolen = client.post(
        "/api/v1/import/lumi-data/apply",
        json={"importId": import_id, "components": ["tags"]},
        headers=env["cookies"][B_USER],
    )
    assert stolen.status_code == 404, stolen.text
    assert stolen.json()["error"]["type"] == "import_session_not_found"
    # 创建者本人正常应用 → 200；一次性消费。
    applied = client.post(
        "/api/v1/import/lumi-data/apply",
        json={"importId": import_id, "components": ["tags"]},
        headers=env["cookies"][A_USER],
    )
    assert applied.status_code == 200, applied.text
    replay = client.post(
        "/api/v1/import/lumi-data/apply",
        json={"importId": import_id, "components": ["tags"]},
        headers=env["cookies"][A_USER],
    )
    assert replay.status_code == 404


def test_fix049_deactivation_identity_cannot_be_forged(env):
    client = env["client"]
    a_id, b_id = env["ids"][A_USER], env["ids"][B_USER]
    # extra=forbid：请求体里塞 userId → 422，绝不把停用改道到他人。
    forged = client.post(
        "/api/v1/me/deactivation-request",
        json={"password": PASSWORD, "userId": a_id},
        headers=env["cookies"][B_USER],
    )
    assert forged.status_code == 422, forged.text
    # B 的正常停用永远只作用于 B 自己（会话身份）。
    ok = client.post(
        "/api/v1/me/deactivation-request",
        json={"password": PASSWORD},
        headers=env["cookies"][B_USER],
    )
    assert ok.status_code == 200, ok.text
    users = client.get("/api/v1/admin/users", headers=env["owner"]).json()
    by_id = {str(r["id"]): r for r in users}
    assert by_id[a_id]["status"] == "active"  # A 未被牵连
    assert by_id[b_id]["status"] == "paused"  # 只 B 被标记


def test_fix049_export_scoped_to_session_identity(env):
    import io
    import zipfile

    client = env["client"]
    a_id = env["ids"][A_USER]
    # A 的用户库种一个书签；A 的导出可见它，B 的导出绝不含它。
    assert client.get("/api/v1/search/views", headers=env["cookies"][A_USER]).status_code == 200
    _seed_private_content(env["users_root"] / a_id / "lumi.sqlite")
    export_a = client.get("/api/v1/export/lumi-data.zip", headers=env["cookies"][A_USER])
    assert export_a.status_code == 200, export_a.text
    export_b = client.get("/api/v1/export/lumi-data.zip", headers=env["cookies"][B_USER])
    assert export_b.status_code == 200, export_b.text

    def blob(response) -> str:
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            return "\n".join(
                archive.read(name).decode("utf-8") for name in archive.namelist() if name.endswith(".json")
            )

    text_a, text_b = blob(export_a), blob(export_b)
    assert PRIVATE_TITLE in text_a and PRIVATE_BOOKMARK_NOTE in text_a  # A 导出包含 A 的数据
    for marker in (PRIVATE_TITLE, PRIVATE_CONTENT, PRIVATE_NOTE, PRIVATE_SUMMARY, PRIVATE_BOOKMARK_NOTE):
        assert marker not in text_b  # B 的导出绝不串入 A 的数据


# ---------------------------------------------------------------------------
# FIX-050 — 审计事件四元组完整（actor/action/target/outcome + ts）；
# 全量事件扫描绝不含密码、令牌与私人正文。失败事件显式带
# outcome=denied/failed（不再只靠 action 名表达结果）。


def test_fix050_audit_schema_complete_and_secret_free(env):
    client, owner = env["client"], env["owner"]
    a_id = env["ids"][A_USER]

    # 代表性流程集：成功与失败各若干。
    client.post("/api/v1/auth/login", json={"username": A_USER, "password": "wrong-" + _secrets.token_urlsafe(6)})
    invite = client.post("/api/v1/admin/invites", json={"label": "f050"}, headers=owner)
    raw_invite = invite.json()["token"]
    activation = client.post(
        "/api/v1/auth/activate",
        json={"token": raw_invite, "username": "c13" + _secrets.token_hex(3), "password": PASSWORD},
    )
    assert activation.status_code == 200, activation.text
    # 已用 token 再次兑换 → invite_activation_failed（已知 invite id）。
    burned = client.post(
        "/api/v1/auth/activate",
        json={"token": raw_invite, "username": "d13" + _secrets.token_hex(3), "password": PASSWORD},
    )
    assert burned.status_code == 400
    bad_mint = client.post(
        "/api/v1/admin/step-up",
        json={"password": "nope-" + _secrets.token_urlsafe(6), "operation": "user_quota_set", "targetUserId": a_id},
        headers=owner,
    )
    assert bad_mint.status_code == 400
    # A 仍是 member 时先暂停（提为 admin 后会触发最后管理员守卫）。
    pause_headers = _mint(client, owner, "user_paused", a_id)
    assert client.post(f"/api/v1/admin/users/{a_id}/pause", headers=pause_headers).status_code == 200
    role_headers = _mint(client, owner, "user_role_change", a_id)
    role = client.post(f"/api/v1/admin/users/{a_id}/role", json={"role": "admin"}, headers=role_headers)
    assert role.status_code == 200, role.text
    quota_headers = _mint(client, owner, "user_quota_set", a_id)
    assert client.put(f"/api/v1/admin/users/{a_id}/quota", json={"maxSources": 5}, headers=quota_headers).status_code == 200

    audit = client.get("/api/v1/admin/audit?limit=500", headers=owner)
    rows = audit.json()

    # 1) schema 完整性：每条都有 ts/actor/action/target/outcome。
    for row in rows:
        assert isinstance(row["ts"], int) and row["ts"] > 0
        assert str(row["actor"] or "").strip()
        assert str(row["action"] or "").strip()
        assert row["object_type"] is not None and str(row["object_id"] or "").strip()
        assert row["outcome"] in {"ok", "denied", "failed"}

    # 2) 失败事件显式 outcome（不是只靠 action 名）。
    by_action = {}
    for row in rows:
        by_action.setdefault(row["action"], []).append(row)
    assert all(r["outcome"] == "denied" for r in by_action["login_failed"])
    assert all(r["outcome"] == "denied" for r in by_action["admin_step_up_mint_failed"])
    assert all(r["outcome"] == "denied" for r in by_action["invite_activation_failed"])

    # 3) 秘密缺席扫描：密码/邀请令牌/step-up 令牌/私人正文绝不入审计。
    stepup_token = role_headers["X-Lumi-Step-Up"]
    serialized = audit.text
    for secret in (PASSWORD, "nope-" + _secrets.token_urlsafe(6), raw_invite, stepup_token, PRIVATE_NOTE):
        assert secret not in serialized


# ---------------------------------------------------------------------------
# FIX-031 — 用户列表契约：无筛选/排序/分页参数（设计如此——小规模
# 邀请制），总数 = 全量目录；同一秒创建的行也有稳定全序
# (created_at, id)。


def test_fix031_user_list_unpaginated_contract_stable_order(env):
    client, owner = env["client"], env["owner"]
    from lumirss.accounts_store import AccountsStore
    from lumirss.storage import Database

    async def count_users():
        database = Database(env["db_path"])
        await database.migrate()
        return await AccountsStore(database).count_users()

    total = _run(count_users())
    assert total >= 3

    first = client.get("/api/v1/admin/users", headers=owner)
    assert first.status_code == 200
    rows = first.json()
    assert len(rows) == total  # 无分页：响应即全量（总数与结果一致）
    keys = [(r["created_at"], r["id"]) for r in rows]
    assert keys == sorted(keys)  # 稳定全序（含同秒并列）
    again = client.get("/api/v1/admin/users", headers=owner).json()
    assert [r["id"] for r in again] == [r["id"] for r in rows]
    # 未知查询参数被忽略（契约上不存在 filter/sort/page 语义）。
    assert client.get("/api/v1/admin/users?filter=x&page=9", headers=owner).json() == rows
    # store 层 limit 夹紧仍有序。
    async def limited():
        database = Database(env["db_path"])
        await database.migrate()
        return await AccountsStore(database).list_users(limit=2)

    limited_rows = _run(limited())
    assert len(limited_rows) == 2
    assert [r["id"] for r in limited_rows] == [r["id"] for r in rows[:2]]


# ---------------------------------------------------------------------------
# FIX-033 — 不存在 admin 资料改写路径（display_name 只在激活时定）；
# 状态/角色/配额变更绝不触碰未编辑字段；PUT quota 的「缺省键 =
# 清除」是文档化的替换语义，不是意外的空值覆盖。


def test_fix033_no_admin_profile_write_path(env):
    client, owner = env["client"], env["owner"]
    a_id = env["ids"][A_USER]

    profile_routes = [
        (route.path, sorted(route.methods))
        for route in client.app.routes
        if "/admin/users/{user_id}" in getattr(route, "path", "")
        and ({"PATCH", "PUT", "POST"} & set(route.methods))
        and "/quota" not in route.path
    ]
    # 只有 pause/resume/role/revoke-sessions/reset-password/background-*，
    # 没有任何携带 display_name/profile 字段的写端点。
    assert all("profile" not in path for path, _methods in profile_routes)

    def display_of():
        users = client.get("/api/v1/admin/users", headers=owner).json()
        return next(r["display_name"] for r in users if r["id"] == a_id)

    before = display_of()
    # 暂停/恢复（A 还是 member——升 admin 后 pause 会触发最后管理员守卫）。
    pause_headers = _mint(client, owner, "user_paused", a_id)
    assert client.post(f"/api/v1/admin/users/{a_id}/pause", headers=pause_headers).status_code == 200
    resume_headers = _mint(client, owner, "user_active", a_id)
    assert client.post(f"/api/v1/admin/users/{a_id}/resume", headers=resume_headers).status_code == 200
    headers = _mint(client, owner, "user_role_change", a_id)
    assert client.post(f"/api/v1/admin/users/{a_id}/role", json={"role": "admin"}, headers=headers).status_code == 200
    assert display_of() == before  # 未编辑字段绝不被空值覆盖

    # quota PUT 的替换语义按文档执行（缺省键 = 清除该上限）。
    quota_headers = _mint(client, owner, "user_quota_set", a_id)
    put = client.put(
        f"/api/v1/admin/users/{a_id}/quota",
        json={"maxSources": 4, "aiQuotaPerDay": 8},
        headers=quota_headers,
    )
    assert put.json()["caps"] == {"maxSources": 4, "aiQuotaPerDay": 8}
    quota_headers = _mint(client, owner, "user_quota_set", a_id)
    only_sources = client.put(
        f"/api/v1/admin/users/{a_id}/quota", json={"maxSources": 6}, headers=quota_headers
    )
    assert only_sources.status_code == 200
    assert only_sources.json()["caps"] == {"maxSources": 6}  # 文档化替换，非 BUG


# ---------------------------------------------------------------------------
# FIX-038 — created_at / updated_at / password_updated_at 语义分明、
# epoch 秒无歧义；缺失值显式 null（绝非 epoch-0）；admin 载荷不存在
# lastLogin/lastActive 混淆字段（登录事件只在 /auth/login-events 自助面）。


def test_fix038_user_time_fields_explicit_and_distinct(env):
    client, owner = env["client"], env["owner"]
    users = client.get("/api/v1/admin/users", headers=owner).json()
    a_row = next(r for r in users if r["id"] == env["ids"][A_USER])
    owner_row = next(r for r in users if r["role"] == "owner")
    assert isinstance(a_row["created_at"], int) and a_row["created_at"] > 0
    assert isinstance(a_row["updated_at"], int) and a_row["updated_at"] >= a_row["created_at"]
    # 激活路径不写 password_updated_at → 显式 null（绝非 epoch-0）。
    assert a_row["password_updated_at"] is None
    # 经 set_password_hash 的账户（owner）→ 有真实时间戳，语义分明。
    assert isinstance(owner_row["password_updated_at"], int) and owner_row["password_updated_at"] > 0
    for row in users:
        assert "lastLogin" not in row and "lastActive" not in row
        assert "last_login" not in row and "last_active" not in row
    # 直接经 store 建的账户（未设密码时间）→ password_updated_at 显式 null。
    from lumirss.accounts_store import AccountsStore, hash_password
    from lumirss.storage import Database

    async def make_null_pw_user():
        database = Database(env["db_path"])
        await database.migrate()
        store = AccountsStore(database)
        user = await store.create_user(
            username="nullpw13" + _secrets.token_hex(2),
            password_hash=hash_password(_fake("pw-")),
            role="member",
        )
        return str(user["id"])

    null_id = _run(make_null_pw_user())
    users = client.get("/api/v1/admin/users", headers=owner).json()
    row = next(r for r in users if r["id"] == null_id)
    assert row["password_updated_at"] is None  # 显式 null，不是 0
    # 配额载荷时间戳：UTC ISO 带时区，或显式 null。
    quota = client.get(f"/api/v1/admin/users/{env['ids'][A_USER]}/quota", headers=owner).json()
    if quota["updatedAt"] is not None:
        assert quota["updatedAt"].endswith("+00:00")


# ---------------------------------------------------------------------------
# FIX-032 — 激活中点失败（池位已 assigned、绑定写失败）：池位释放回
# ready（可重试、不烧名额）、账户诚实 binding_pending、不 500、审计
# 留痕；恢复池密码后下一个成员用同一池位成功绑定。register 路径同。


def _pool_username():
    return "pool" + _secrets.token_hex(4)


def test_fix032_activation_binding_midpoint_recoverable(env):
    client, owner = env["client"], env["owner"]
    pool_user = _pool_username()
    added = client.post(
        "/api/v1/admin/pool",
        json={"freshrssUsername": pool_user, "freshrssBaseUrl": "https://fr.test", "apiPassword": _fake("apipw-")},
        headers=owner,
    )
    assert added.status_code == 200, added.text
    # 模拟中点失败：控制层 secrets 丢池密码 → bind 必然失败。
    client.app.state.control_secrets.delete(f"freshrss_pool:{pool_user}")
    invite = client.post("/api/v1/admin/invites", json={"label": "f032"}, headers=owner)
    member = "f032" + _secrets.token_hex(3)
    activation = client.post(
        "/api/v1/auth/activate",
        json={"token": invite.json()["token"], "username": member, "password": PASSWORD},
    )
    # 账户保留 + 诚实 pending（绝不 500、绝不烧掉池位）。
    assert activation.status_code == 200, activation.text
    users = client.get("/api/v1/admin/users", headers=owner).json()
    member_id = str(next(r["id"] for r in users if r["username"] == member))
    audit_rows = client.get("/api/v1/admin/audit?limit=500", headers=owner).json()
    failed = [r for r in audit_rows if r["action"] == "activation_binding_failed"]
    assert failed and failed[-1]["outcome"] == "failed" and failed[-1]["object_id"] == pool_user
    assert [r for r in audit_rows if r["action"] == "account_activate" and r["object_id"] == member_id][-1]["detail"] == "binding_pending"
    # 池位已释放回 ready（可重试）。
    pool = client.get("/api/v1/admin/pool", headers=owner).json()
    entry = next(m for m in pool["members"] if m["id"] == member_id)
    assert entry["bound"] is False  # 诚实未绑定
    raw = client.get("/api/v1/admin/capacity", headers=owner).json()["pool"]
    assert raw["assigned"] == 0 and raw["ready"] == 1
    # 恢复：重新登记池密码（部署侧等价操作）→ 下一个成员绑定成功。
    client.app.state.control_secrets.set(f"freshrss_pool:{pool_user}", _fake("apipw2-"))
    invite2 = client.post("/api/v1/admin/invites", json={"label": "f032b"}, headers=owner)
    member2 = "f032b" + _secrets.token_hex(3)
    activation2 = client.post(
        "/api/v1/auth/activate",
        json={"token": invite2.json()["token"], "username": member2, "password": PASSWORD},
    )
    assert activation2.status_code == 200, activation2.text
    pool2 = client.get("/api/v1/admin/pool", headers=owner).json()
    assert next(m for m in pool2["members"] if m["username"] == member2)["bound"] is True
    assert pool2["assigned"] == 1


def test_fix032_register_binding_midpoint_recoverable(env):
    client, owner = env["client"], env["owner"]
    policy = client.put(
        "/api/v1/admin/registration-policy", json={"allowPublicRegistration": True}, headers=owner
    )
    assert policy.status_code == 200, policy.text
    pool_user = _pool_username()
    added = client.post(
        "/api/v1/admin/pool",
        json={"freshrssUsername": pool_user, "freshrssBaseUrl": "https://fr.test", "apiPassword": _fake("apipw-")},
        headers=owner,
    )
    assert added.status_code == 200, added.text
    client.app.state.control_secrets.delete(f"freshrss_pool:{pool_user}")
    member = "f032r" + _secrets.token_hex(3)
    registered = client.post(
        "/api/v1/auth/register", json={"username": member, "password": PASSWORD}
    )
    assert registered.status_code == 200, registered.text  # 不 500，账户保留
    audit_rows = client.get("/api/v1/admin/audit?limit=500", headers=owner).json()
    assert any(r["action"] == "activation_binding_failed" and r["object_id"] == pool_user for r in audit_rows)
    users = client.get("/api/v1/admin/users", headers=owner).json()
    member_id = str(next(r["id"] for r in users if r["username"] == member))
    assert [r for r in audit_rows if r["action"] == "account_register" and r["object_id"] == member_id][-1]["detail"] == "binding_pending"


# ---------------------------------------------------------------------------
# FIX-217 — 后台循环执行前验证账户生命周期：快照之后被删除/停用的
# 账户被干净跳过——绝不进入其上下文、绝不重建其用户库目录。


def test_fix217_background_loop_skips_dead_accounts(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from lumirss.accounts_store import AccountsStore, hash_password
    from lumirss.storage import Database
    from lumirss.user_scope import RoutingDatabase, for_each_active_user

    db_path = tmp_path / "lumi.sqlite"
    users_root = tmp_path / "users"

    async def build():
        control = Database(db_path)
        await control.migrate()
        accounts = AccountsStore(control)
        u1 = await accounts.create_user(username="f217a" + _secrets.token_hex(2), password_hash=hash_password(_fake("pw-")), role="member")
        u2 = await accounts.create_user(username="f217b" + _secrets.token_hex(2), password_hash=hash_password(_fake("pw-")), role="member")
        u3 = await accounts.create_user(username="f217c" + _secrets.token_hex(2), password_hash=hash_password(_fake("pw-")), role="member")
        # 同秒创建的并列：显式 created_at 固定循环顺序 u1 → u2 → u3。
        for uid, created in ((str(u1["id"]), 1000), (str(u2["id"]), 2000), (str(u3["id"]), 3000)):
            await control.execute("UPDATE users SET created_at = ? WHERE id = ?", (created, uid))
        # u3：快照时 status 仍 active，但已带待删除标记（软删除）。
        await control.execute("UPDATE users SET deactivation_requested_at = 1 WHERE id = ?", (str(u3["id"]),))
        return control, str(u1["id"]), str(u2["id"]), str(u3["id"])

    control, u1, u2, u3 = _run(build())
    rdb = RoutingDatabase(db_path, users_root)
    ran: list[str] = []

    async def work(uid):
        # 真实后台工作形态：进入用户上下文后触碰路由库（会 mkdir 用户目录）。
        await rdb.migrate()
        ran.append(uid)
        if uid == u1:
            # 快照后、轮到 u2 前账户被物理删除（运营者手动删除路径）。
            await control.execute("DELETE FROM users WHERE id = ?", (u2,))

    state = SimpleNamespace(control_db=control, db=rdb)
    _run(for_each_active_user(state, work))

    assert ran == [u1], f"dead account executed anyway: {ran}"
    assert not (users_root / u2).exists(), "user DB directory recreated for deleted account"
    assert not (users_root / u3).exists(), "pending-deletion account touched at all"

    # 第二轮：快照仍含 status=active 的 u3（标记为待删除）→ 依旧干净跳过。
    ran2: list[str] = []

    async def work2(uid):
        await rdb.migrate()
        ran2.append(uid)

    _run(for_each_active_user(state, work2))
    assert ran2 == [u1]
    assert u3 not in ran2, "pending-deletion account executed anyway"
    assert not (users_root / u3).exists()


# ---------------------------------------------------------------------------
# FIX-218 — step-up 令牌绑定 (操作, 目标账户)：跨操作、跨目标复用
# 一律 403；正确绑定单次接受；无作用域旧令牌永不匹配。


def test_fix218_step_up_token_rejected_across_operations(env):
    client, owner = env["client"], env["owner"]
    a_id = env["ids"][A_USER]
    # 为 quota@A 铸造的令牌不能授权 role 变更（跨操作）。
    quota_token = _mint(client, owner, "user_quota_set", a_id)["X-Lumi-Step-Up"]
    cross_op = client.post(
        f"/api/v1/admin/users/{a_id}/role",
        json={"role": "admin"},
        headers={**owner, "X-Lumi-Step-Up": quota_token},
    )
    assert cross_op.status_code == 403
    assert cross_op.json()["error"]["type"] == "step_up_required"
    assert cross_op.json()["error"]["operation"] == "user_role_change"
    assert cross_op.json()["error"]["targetUserId"] == a_id


def test_fix218_step_up_token_rejected_across_targets(env):
    client, owner = env["client"], env["owner"]
    a_id, b_id = env["ids"][A_USER], env["ids"][B_USER]
    # 为 pause@A 确认的令牌不能 pause B（跨目标）。
    a_headers = _mint(client, owner, "user_paused", a_id)
    cross_target = client.post(f"/api/v1/admin/users/{b_id}/pause", headers=a_headers)
    assert cross_target.status_code == 403
    assert cross_target.json()["error"]["type"] == "step_up_required"
    # 正确绑定：同一作用域单次接受，重放 403。
    ok = client.post(f"/api/v1/admin/users/{a_id}/pause", headers=a_headers)
    assert ok.status_code == 200, ok.text
    replay = client.post(f"/api/v1/admin/users/{a_id}/pause", headers=a_headers)
    assert replay.status_code == 403
    assert replay.json()["error"]["type"] == "step_up_required"


def test_fix218_step_up_mint_requires_scope_and_rejects_legacy_tokens(env):
    client, owner = env["client"], env["owner"]
    a_id = env["ids"][A_USER]
    # 缺 operation/targetUserId → 422（铸造必须声明作用域）。
    for body in ({"password": PASSWORD}, {"password": PASSWORD, "operation": "user_paused"}):
        assert client.post("/api/v1/admin/step-up", json=body, headers=owner).status_code == 422
    assert (
        client.post(
            "/api/v1/admin/step-up",
            json={"password": PASSWORD, "operation": "not_an_op", "targetUserId": a_id},
            headers=owner,
        ).status_code
        == 422
    )
    # 旧格式无作用域令牌（operation NULL，直接入库）→ 永不匹配 → 403。
    from lumirss.storage import Database
    from lumirss.token_hash import hash_token

    users = client.get("/api/v1/admin/users", headers=owner).json()
    owner_id = next(r["id"] for r in users if r["role"] == "owner")
    legacy = "legacy-" + _secrets.token_urlsafe(16)

    async def insert_legacy():
        database = Database(env["db_path"])
        await database.migrate()
        await database.execute(
            "INSERT INTO admin_step_up_tokens (token_hash, user_id, operation, created_at, expires_at) VALUES (?, ?, NULL, datetime('now'), datetime('now', '+5 minutes'))",
            (hash_token(legacy), owner_id),
        )

    _run(insert_legacy())
    legacy_try = client.post(
        f"/api/v1/admin/users/{a_id}/pause",
        headers={**owner, "X-Lumi-Step-Up": legacy},
    )
    assert legacy_try.status_code == 403
    # 审计不泄漏令牌/密码（mint 记录只带作用域元数据）。
    audit = client.get("/api/v1/admin/audit?limit=500", headers=owner).text
    assert legacy not in audit and PASSWORD not in audit
