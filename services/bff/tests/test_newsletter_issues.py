"""R19 邮件简报发送账本 — /api/v1/newsletter/issues 路由与持久化。

- send-now 成功 → 账本 sent 行含正文快照（HTML/text）与逐收件人账目；
- SMTP 失败 → 502 + failed 行（无快照 → bodyAvailable=false 诚实降级）；
- 重试只投递账目中尚未成功的收件人（绝不重复投递已成功地址）；
- 收件人地址对非管理员脱敏（a***@domain），owner 明文；
- draft / scheduled 过滤诚实空列表；调度窗口 dedupe 同窗补写同一行。

上游网络全部 mock（send_digest_smtp 替身），测试绝不触碰真实第三方
邮件服务。main.py 的 router include 由主 Agent 统一接入；测试进程内
幂等挂载（路由已存在则跳过）以便直接走 HTTP 层。
"""

import asyncio
import uuid

import lumirss.mail_digest as digest_module
from lumirss.mail_digest import DigestStore, SmtpSendFailed
from lumirss.main import app
from lumirss.newsletter_issues import NewsletterIssueStore
from lumirss.routers import newsletter as newsletter_routes
from lumirss.secrets_store import SecretsStore
from lumirss.storage import Database

# main.py 尚未 include 时在测试进程内挂载；已 include（主 Agent 集成
# 后）则跳过——两种状态下套件都只注册一次。
_EXISTING_PATHS = {getattr(route, "path", "") for route in app.routes}
if "/api/v1/newsletter/issues" not in _EXISTING_PATHS:
    app.include_router(newsletter_routes.router)


def run(coroutine):
    return asyncio.run(coroutine)


RAW_MAIL = (
    "From: Newsletter <news@example.com>\r\n"
    "To: reader@example.com\r\n"
    "Subject: =?utf-8?B?5q+P5ZGo57K+6YCJ?=\r\n"
    "Message-ID: <issue-42@example.com>\r\n"
    "MIME-Version: 1.0\r\n"
    'Content-Type: multipart/alternative; boundary="BOUND"\r\n'
    "\r\n"
    "--BOUND\r\n"
    "Content-Type: text/plain; charset=utf-8\r\n"
    "\r\n"
    "纯文本版本第 42 期\r\n"
    "--BOUND\r\n"
    "Content-Type: text/html; charset=utf-8\r\n"
    "\r\n"
    "<html><body><h1>第 42 期</h1><p>正文内容</p></body></html>\r\n"
    "--BOUND--\r\n"
)


def _ok_send(calls: list[str]):
    def fake_send(**kwargs):
        calls.append(str(kwargs["to_addr"]))
        return ""

    return fake_send


def _setup_bridge_and_settings(
    client, monkeypatch, to_addr: str, headers: dict | None = None
) -> None:
    """一条 bridge 邮件 + 已配置的 SMTP（收件地址可含多个）。

    ``headers``：session 模式下必须显式给身份 cookie——TestClient 会
    持有上一次响应的会话 cookie，「不带头」的调用可能落到错误的
    per-user 库。"""
    created = client.post(
        "/api/v1/mail/bridge-lists", json={"name": "快报"}, headers=headers
    ).json()
    ingest = client.post(
        f"/api/mail/ingest/{created['uuid']}",
        content=RAW_MAIL.encode(),
        headers={"Authorization": f"Bearer {created['secret']}", **(headers or {})},
    )
    assert ingest.status_code == 200, ingest.text
    config = client.put(
        "/api/v1/digest/settings",
        json={"smtpHost": "127.0.0.1", "toAddr": to_addr, "source": "mail"},
        headers=headers,
    )
    assert config.status_code == 200, config.text


def test_send_now_records_sent_issue_with_body_snapshot(client, monkeypatch):
    """成功发送 → sent 行 + 正文快照 + 逐收件人账目（owner 明文地址）。"""
    _setup_bridge_and_settings(client, monkeypatch, "reader@local")
    calls: list[str] = []
    monkeypatch.setattr(digest_module, "send_digest_smtp", _ok_send(calls))

    sent = client.post("/api/v1/digest/send-now", json={"entryRefs": []})
    assert sent.status_code == 200, sent.text
    assert calls == ["reader@local"]

    listing = client.get("/api/v1/newsletter/issues", params={"status": "sent"})
    assert listing.status_code == 200
    items = listing.json()["items"]
    assert len(items) == 1
    row = items[0]
    assert row["subject"] == "LumiRSS 文章摘要"
    assert row["status"] == "sent"
    assert row["source"] == "mail"
    assert row["origin"] == "manual"
    assert row["recipientCount"] == 1
    assert row["sentAt"] is not None

    detail = client.get(f"/api/v1/newsletter/issues/{row['id']}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["bodyAvailable"] is True
    assert "每周精选" in body["text"]
    assert "每周精选" in body["html"]
    assert body["recipients"] == [
        {
            "address": "reader@local",
            "status": "sent",
            "error": None,
            "sentAt": body["recipients"][0]["sentAt"],
        }
    ]

    # failed 过滤与 sent 互斥；draft/scheduled 无持久化形态 → 诚实空。
    assert client.get("/api/v1/newsletter/issues", params={"status": "failed"}).json()["items"] == []
    assert client.get("/api/v1/newsletter/issues", params={"status": "draft"}).json()["items"] == []
    assert client.get("/api/v1/newsletter/issues", params={"status": "scheduled"}).json()["items"] == []
    assert (
        client.get("/api/v1/newsletter/issues", params={"status": "bogus"}).status_code
        == 422
    )
    assert client.get("/api/v1/newsletter/issues/99999").status_code == 404


def test_failed_send_records_failed_issue_without_body(client, monkeypatch):
    """SMTP 失败 → 502 + failed 行：错误留痕、无正文快照（诚实降级）。"""

    def failing_send(**kwargs):
        raise SmtpSendFailed("SMTP 服务器无法连接。", "unreachable")

    _setup_bridge_and_settings(client, monkeypatch, "reader@local")
    monkeypatch.setattr(digest_module, "send_digest_smtp", failing_send)

    sent = client.post("/api/v1/digest/send-now", json={"entryRefs": []})
    assert sent.status_code == 502
    assert sent.json()["error"]["type"] == "smtp_send_failed"

    listing = client.get("/api/v1/newsletter/issues", params={"status": "failed"})
    items = listing.json()["items"]
    assert len(items) == 1
    row = items[0]
    assert row["status"] == "failed"
    assert row["sentAt"] is None
    assert "unreachable" in (row["error"] or "")

    detail = client.get(f"/api/v1/newsletter/issues/{row['id']}")
    assert detail.status_code == 200
    body = detail.json()
    # 无快照 → 诚实 bodyAvailable=false，绝不伪造正文。
    assert body["bodyAvailable"] is False
    assert body["text"] is None
    assert body["html"] is None
    assert body["recipients"][0]["status"] == "failed"

    # sent 过滤下不可见；重试该行是合法入口（下一测试覆盖完整重试）。
    assert client.get("/api/v1/newsletter/issues", params={"status": "sent"}).json()["items"] == []


def test_retry_resends_only_unsent_recipients(client, monkeypatch):
    """重试不重复投递已成功收件人：第二次只发给失败的那个地址。"""
    calls: list[str] = []

    def flaky_send(**kwargs):
        calls.append(str(kwargs["to_addr"]))
        if kwargs["to_addr"] == "second@local":
            raise SmtpSendFailed("SMTP 发送失败。", "send_failed")

    _setup_bridge_and_settings(client, monkeypatch, "first@local, second@local")
    monkeypatch.setattr(digest_module, "send_digest_smtp", flaky_send)

    first = client.post("/api/v1/digest/send-now", json={"entryRefs": []})
    assert first.status_code == 502
    assert calls == ["first@local", "second@local"]

    listing = client.get("/api/v1/newsletter/issues", params={"status": "failed"})
    issue_id = listing.json()["items"][0]["id"]
    detail = client.get(f"/api/v1/newsletter/issues/{issue_id}").json()
    statuses = {r["address"]: r["status"] for r in detail["recipients"]}
    assert statuses == {"first@local": "sent", "second@local": "failed"}

    # 修复中继：重试只补投 second；first 不再收到第二封。
    calls.clear()
    monkeypatch.setattr(digest_module, "send_digest_smtp", _ok_send(calls))
    retried = client.post(f"/api/v1/newsletter/issues/{issue_id}/retry")
    assert retried.status_code == 200, retried.text
    payload = retried.json()
    assert payload["status"] == "sent"
    assert payload["sentCount"] == 1
    assert payload["skippedCount"] == 1
    assert calls == ["second@local"]

    detail = client.get(f"/api/v1/newsletter/issues/{issue_id}").json()
    assert detail["status"] == "sent"
    assert detail["bodyAvailable"] is True
    assert {r["address"]: r["status"] for r in detail["recipients"]} == {
        "first@local": "sent",
        "second@local": "sent",
    }
    assert detail["recipientCount"] == 2

    # 已 sent 的行不可重试（稳定 409）；再次重试不产生新投递。
    calls.clear()
    again = client.post(f"/api/v1/newsletter/issues/{issue_id}/retry")
    assert again.status_code == 409
    assert again.json()["error"]["type"] == "not_retryable"
    assert calls == []
    assert client.post("/api/v1/newsletter/issues/99999/retry").status_code == 404


def test_retry_empty_bridge_is_honest_422(client, monkeypatch):
    """快照缺失 + bridge 清空 → 重试拒绝（绝不发空邮件），行保持 failed。"""

    def failing_send(**kwargs):
        raise SmtpSendFailed("SMTP 发送失败。", "send_failed")

    _setup_bridge_and_settings(client, monkeypatch, "reader@local")
    monkeypatch.setattr(digest_module, "send_digest_smtp", failing_send)
    first = client.post("/api/v1/digest/send-now", json={"entryRefs": []})
    assert first.status_code == 502
    issue_id = client.get(
        "/api/v1/newsletter/issues", params={"status": "failed"}
    ).json()["items"][0]["id"]

    # 模拟「快照缺失的历史行」（ledger 之前的形态/外部写入）。
    run(
        Database(app.state.db.path).execute(
            "UPDATE newsletter_issues SET items_json = '[]' WHERE id = ?", (issue_id,)
        )
    )
    # 清空 bridge 派生源：删除列表后 recent items 为空。
    bridge_lists = client.get("/api/v1/mail/bridge-lists").json()["items"]
    for lst in bridge_lists:
        deleted = client.delete(f"/api/v1/mail/bridge-lists/{lst['uuid']}")
        assert deleted.status_code in (204, 409)

    calls: list[str] = []
    monkeypatch.setattr(digest_module, "send_digest_smtp", _ok_send(calls))
    retried = client.post(f"/api/v1/newsletter/issues/{issue_id}/retry")
    assert retried.status_code == 422
    assert retried.json()["error"]["type"] == "no_digest_items"
    assert calls == []  # 未触碰 SMTP

    detail = client.get(f"/api/v1/newsletter/issues/{issue_id}").json()
    assert detail["status"] == "failed"


def test_recipient_masked_for_non_admin(monkeypatch, tmp_path):
    """非管理员（member）看自己的简报：收件地址脱敏 a***@domain。"""
    from fastapi.testclient import TestClient

    import lumirss.middleware as middleware
    from lumirss.accounts_store import AccountsStore, hash_password

    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    monkeypatch.setenv("LUMIRSS_SESSION_SECURE_COOKIES", "false")
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", "")
    monkeypatch.setenv("LUMIRSS_SEARCH_SYNC_INTERVAL", "0")
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    middleware._rate_windows.clear()
    middleware._login_failures.clear()
    # 测试专用随机口令（本进程内存生成，非任何真实凭据）。
    parts = ["member", "mask", uuid.uuid4().hex]
    password = "-".join(parts)

    async def set_owner_password(db_path):
        database = Database(db_path / "lumi.sqlite")
        await database.migrate()
        store = AccountsStore(database)
        for row in await store.list_users(limit=50):
            if row["role"] == "owner":
                await store.set_password_hash(str(row["id"]), hash_password(password))
                return
        raise AssertionError("owner migration did not run")

    with TestClient(app, base_url="http://lumirss.test") as client:
        asyncio.run(set_owner_password(tmp_path))
        owner_login = client.post(
            "/api/v1/auth/login", json={"username": "owner", "password": password}
        )
        assert owner_login.status_code == 200
        owner_headers = {"cookie": owner_login.headers["set-cookie"].split(";")[0]}
        invite = client.post(
            "/api/v1/admin/invites", json={"label": "masky"}, headers=owner_headers
        )
        activation = client.post(
            "/api/v1/auth/activate",
            json={"token": invite.json()["token"], "username": "masky", "password": password},
        )
        assert activation.status_code == 200
        member_headers = {"cookie": activation.headers["set-cookie"].split(";")[0]}

        # member 在自己的库配置并发送（mock SMTP）。
        created = client.post(
            "/api/v1/mail/bridge-lists", json={"name": "会员快报"}, headers=member_headers
        ).json()
        ingest = client.post(
            f"/api/mail/ingest/{created['uuid']}",
            content=RAW_MAIL.encode(),
            headers={
                "Authorization": f"Bearer {created['secret']}",
                **member_headers,
            },
        )
        assert ingest.status_code == 200, ingest.text
        config = client.put(
            "/api/v1/digest/settings",
            json={"smtpHost": "127.0.0.1", "toAddr": "reader@local"},
            headers=member_headers,
        )
        assert config.status_code == 200
        calls: list[str] = []
        monkeypatch.setattr(digest_module, "send_digest_smtp", _ok_send(calls))
        sent = client.post(
            "/api/v1/digest/send-now", json={"entryRefs": []}, headers=member_headers
        )
        assert sent.status_code == 200, sent.text

        issue_id = client.get(
            "/api/v1/newsletter/issues", params={"status": "sent"}, headers=member_headers
        ).json()["items"][0]["id"]
        member_view = client.get(
            f"/api/v1/newsletter/issues/{issue_id}", headers=member_headers
        ).json()
        assert member_view["recipients"][0]["address"] == "r***@local"

        # owner 查看自己的库（另一份 per-user 数据）→ 明文不受影响。
        _setup_bridge_and_settings(
            client, monkeypatch, "reader@local", headers=owner_headers
        )
        owner_sent = client.post(
            "/api/v1/digest/send-now", json={"entryRefs": []}, headers=owner_headers
        )
        assert owner_sent.status_code == 200
        owner_issue = client.get(
            "/api/v1/newsletter/issues", params={"status": "sent"}, headers=owner_headers
        ).json()["items"][0]
        owner_view = client.get(
            f"/api/v1/newsletter/issues/{owner_issue['id']}", headers=owner_headers
        ).json()
        assert owner_view["recipients"][0]["address"] == "reader@local"


def test_mask_email_shape():
    assert newsletter_routes._mask_email("reader@local") == "r***@local"
    assert newsletter_routes._mask_email("a@b.example.com") == "a***@b.example.com"
    assert newsletter_routes._mask_email("@nodomain") == "***@nodomain"
    assert newsletter_routes._mask_email("no-at-sign") == "***"


def test_dedupe_window_updates_same_row(tmp_path):
    """调度窗口 dedupe：同窗补写 UPDATE 同一行（幂等，不产生重复已发送）。"""
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    store = NewsletterIssueStore(db)
    common = {
        "subject": "LumiRSS 文章摘要",
        "source": "mail",
        "origin": "scheduled",
        "recipients": [{"address": "reader@local", "status": "sent"}],
        "item_count": 2,
        "dedupe_key": "digest:2026-10-02T08",
    }
    first = run(
        store.record_result(status="failed", error="发送失败（1/1 个收件人）", **common)
    )
    second = run(store.record_result(status="sent", text="t", html="h", sent_at="x", **common))
    assert first == second
    rows = run(store.list_issues(None))
    assert len(rows) == 1
    assert rows[0]["status"] == "sent"
    # 手动发送（dedupe_key=''）不去重。
    manual = run(
        store.record_result(
            subject="LumiRSS 文章摘要",
            source="mail",
            origin="manual",
            status="sent",
            recipients=[{"address": "reader@local", "status": "sent"}],
            item_count=1,
        )
    )
    assert manual != first
    assert len(run(store.list_issues(None))) == 2


def test_digest_settings_schema_unchanged_after_migration(tmp_path):
    """迁移幂等：migrate 重复执行不报错，digest_settings 原有读写不受影响。"""
    db = Database(tmp_path / "lumi.sqlite")
    run(db.migrate())
    run(db.migrate())
    store = DigestStore(db, SecretsStore(tmp_path / "secrets.json"))
    settings = run(store.load())
    assert settings["enabled"] is False
    assert settings["hour"] == 8
