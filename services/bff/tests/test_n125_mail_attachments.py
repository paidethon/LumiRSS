"""N125 邮件附件阅读 — 有界附件存储 + 下载。

安全文件（pdf）ingest 时入库并可下载（Content-Disposition: attachment、
大小一致）；脚本/可执行类型（.exe/.sh/.js/.html）按扩展名+MIME 双重
判定拒绝（如实列为 skipped）；单文件 5MB / 每封 20 个上限执行；
跨用户访问 → 同型 404（无存在性泄露）。
"""

import asyncio
import base64

import pytest

from lumirss.mail_attachments import (
    MAX_ATTACHMENT_BYTES,
    MAX_ATTACHMENTS_PER_MAIL,
    classify_attachment,
)
from lumirss.main import app


def run(coro):
    return asyncio.run(coro)


def _mime_with_attachments(*parts: tuple[str, str, bytes]) -> bytes:
    """(filename, mime, content) 列表 → multipart/mixed 原始邮件。"""
    chunks = []
    for filename, mime, content in parts:
        b64 = base64.b64encode(content).decode()
        chunks.append(
            f"--BND\r\n"
            f"Content-Type: {mime}; name=\"{filename}\"\r\n"
            f"Content-Disposition: attachment; filename=\"{filename}\"\r\n"
            "Content-Transfer-Encoding: base64\r\n\r\n"
            f"{b64}\r\n"
        )
    return (
        "From: Newsletter <news@example.com>\r\n"
        "To: reader@example.com\r\n"
        "Subject: 带附件\r\n"
        "Message-ID: <att-n125@example.com>\r\n"
        "MIME-Version: 1.0\r\n"
        'Content-Type: multipart/mixed; boundary="BND"\r\n'
        "\r\n"
        "--BND\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n正文\r\n"
        + "".join(chunks)
        + "--BND--\r\n"
    ).encode()


def _bridge_list(client, name="附件列表"):
    created = client.post("/api/v1/mail/bridge-lists", json={"name": name})
    assert created.status_code == 201, created.text
    return created.json()


def _ingest(client, lst, raw: bytes):
    return client.post(
        f"/api/mail/ingest/{lst['uuid']}",
        content=raw,
        headers={"Authorization": f"Bearer {lst['secret']}"},
    )


def test_safe_attachment_stored_and_downloaded(client):
    lst = _bridge_list(client)
    pdf_bytes = b"%PDF-1.4\n" + b"x" * 512
    ingested = _ingest(client, lst, _mime_with_attachments(("report.pdf", "application/pdf", pdf_bytes)))
    assert ingested.status_code == 200
    assert ingested.json()["status"] == "accepted"
    assert ingested.json()["attachments"] == 1

    message_id = ingested.json()["messageId"]
    detail = client.get(
        f"/api/v1/mail/lists/{lst['uuid']}/messages/{message_id}/detail"
    )
    assert detail.status_code == 200
    attachments = detail.json()["attachments"]
    assert len(attachments) == 1
    att = attachments[0]
    assert att["filename"] == "report.pdf"
    assert att["mime"] == "application/pdf"
    assert att["size"] == len(pdf_bytes)
    assert detail.json()["skippedAttachments"] == []

    download = client.get(f"/api/v1/mail/attachments/{att['id']}")
    assert download.status_code == 200
    assert download.content == pdf_bytes
    assert download.headers["content-type"].startswith("application/pdf")
    disposition = download.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert "report.pdf" in disposition


def test_executable_and_script_attachments_denied(client):
    lst = _bridge_list(client, "危险附件")
    raw = _mime_with_attachments(
        ("evil.exe", "application/octet-stream", b"MZ...."),
        ("run.sh", "text/x-shellscript", b"#!/bin/sh\nrm -rf /"),
        ("inject.js", "text/javascript", b"alert(1)"),
        ("page.html", "text/html", b"<script>alert(1)</script>"),
    )
    ingested = _ingest(client, lst, raw)
    assert ingested.status_code == 200
    message_id = ingested.json()["messageId"]
    detail = client.get(
        f"/api/v1/mail/lists/{lst['uuid']}/messages/{message_id}/detail"
    ).json()
    assert detail["attachments"] == []  # 没有任何危险附件入库
    skipped = detail["skippedAttachments"]
    assert len(skipped) == 4
    assert all(item["status"] == "skipped_unsafe" for item in skipped)
    # 存储层确认零行
    rows = run(
        app.state.db.fetch_all("SELECT id FROM mail_attachments")
    )
    assert rows == []


def test_oversize_and_count_caps_enforced(client):
    lst = _bridge_list(client, "上限附件")
    oversize = b"%PDF-1.4\n" + b"y" * (MAX_ATTACHMENT_BYTES + 1024)
    small = b"%PDF-1.4 tiny"
    parts = [("too-big.pdf", "application/pdf", oversize)]
    parts += [
        (f"doc-{i}.pdf", "application/pdf", small)
        for i in range(MAX_ATTACHMENTS_PER_MAIL + 3)
    ]
    ingested = _ingest(client, lst, _mime_with_attachments(*parts))
    assert ingested.status_code == 200
    message_id = ingested.json()["messageId"]
    detail = client.get(
        f"/api/v1/mail/lists/{lst['uuid']}/messages/{message_id}/detail"
    ).json()
    assert len(detail["attachments"]) == MAX_ATTACHMENTS_PER_MAIL
    statuses = [item["status"] for item in detail["skippedAttachments"]]
    assert statuses.count("skipped_oversize") == 1
    assert statuses.count("skipped_limit") == 3
    rows = run(app.state.db.fetch_all("SELECT size FROM mail_attachments"))
    assert all(int(row["size"]) <= MAX_ATTACHMENT_BYTES for row in rows)


def test_attachment_download_404_for_unknown_id(client):
    response = client.get("/api/v1/mail/attachments/no-such-id")
    assert response.status_code == 404
    assert response.json()["error"]["type"] == "mail_list_not_found" or (
        response.json()["error"]["type"] == "mail_attachment_not_found"
    )


# -- 跨用户隔离（0067 session 模式） --------------------------------------------

PASSWORD = "n125-" + "x" * 12


@pytest.fixture()
def two_users(monkeypatch, tmp_path):
    """owner + 成员 A/B（独立数据库）；返回带会话 cookie 的客户端。"""
    from fastapi.testclient import TestClient

    import lumirss.middleware as middleware

    monkeypatch.setenv("LUMIRSS_AUTH_MODE", "session")
    monkeypatch.setenv("LUMIRSS_SESSION_SECURE_COOKIES", "false")
    monkeypatch.setenv("LUMIRSS_INTERNAL_TOKEN", "")
    monkeypatch.setenv("LUMIRSS_SEARCH_SYNC_INTERVAL", "0")
    monkeypatch.setenv("LUMIRSS_DB_PATH", str(tmp_path / "lumi.sqlite"))
    middleware._rate_windows.clear()
    middleware._login_failures.clear()

    with TestClient(app, base_url="http://lumirss.test") as test_client:
        # 替换 owner 迁移生成的不可知密码
        from lumirss.accounts_store import AccountsStore, hash_password
        from lumirss.storage import Database

        async def _fix_owner():
            database = Database(tmp_path / "lumi.sqlite")
            await database.migrate()
            store = AccountsStore(database)
            for row in await store.list_users(limit=50):
                if row["role"] == "owner":
                    await store.set_password_hash(str(row["id"]), hash_password(PASSWORD))
                    break

        asyncio.run(_fix_owner())
        owner = test_client.post(
            "/api/v1/auth/login", json={"username": "owner", "password": PASSWORD}
        )
        assert owner.status_code == 200
        owner_headers = {"cookie": owner.headers["set-cookie"].split(";")[0]}
        users = {}
        for username in ("alice", "bob"):
            invite = test_client.post(
                "/api/v1/admin/invites",
                json={"label": username},
                headers=owner_headers,
            )
            assert invite.status_code == 200
            activation = test_client.post(
                "/api/v1/auth/activate",
                json={
                    "token": invite.json()["token"],
                    "username": username,
                    "password": PASSWORD,
                    "displayName": username,
                },
            )
            assert activation.status_code == 200
            users[username] = {"cookie": activation.headers["set-cookie"].split(";")[0]}
        yield {"client": test_client, **users}


def _get(env, who: str, path: str):
    return env["client"].get(path, headers={"cookie": env[who]["cookie"]})


def test_attachment_cross_user_404(two_users):
    """A 收到的附件：B 与 owner 都拿不到（同型 404，不泄露存在性）。"""
    env = two_users
    client = env["client"]
    alice_cookie = env["alice"]["cookie"]
    created = client.post(
        "/api/v1/mail/bridge-lists",
        json={"name": "A 的列表"},
        headers={"cookie": alice_cookie},
    )
    assert created.status_code == 201, created.text
    lst = created.json()
    pdf = b"%PDF-1.4 alice-only" + b"z" * 64
    ingested = client.post(
        f"/api/mail/ingest/{lst['uuid']}",
        content=_mime_with_attachments(("private.pdf", "application/pdf", pdf)),
        headers={"Authorization": f"Bearer {lst['secret']}"},
    )
    assert ingested.status_code == 200
    message_id = ingested.json()["messageId"]

    detail_a = client.get(
        f"/api/v1/mail/lists/{lst['uuid']}/messages/{message_id}/detail",
        headers={"cookie": alice_cookie},
    )
    assert detail_a.status_code == 200
    attachment_id = detail_a.json()["attachments"][0]["id"]

    ok = client.get(
        f"/api/v1/mail/attachments/{attachment_id}",
        headers={"cookie": alice_cookie},
    )
    assert ok.status_code == 200
    assert ok.content == pdf

    for who in ("bob",):
        borrowed = _get(env, who, f"/api/v1/mail/attachments/{attachment_id}")
        assert borrowed.status_code == 404
    owner_login = client.post(
        "/api/v1/auth/login", json={"username": "owner", "password": PASSWORD}
    )
    assert owner_login.status_code == 200
    owner_borrowed = client.get(
        f"/api/v1/mail/attachments/{attachment_id}",
        headers={"cookie": owner_login.headers["set-cookie"].split(";")[0]},
    )
    assert owner_borrowed.status_code == 404


def test_classify_attachment_deny_allow_matrix():
    assert classify_attachment("a.pdf", "application/pdf") == "application/pdf"
    assert classify_attachment("a.png", "image/png") == "image/png"
    assert classify_attachment("a.JPG", "image/jpeg") == "image/jpeg"
    assert classify_attachment("notes.txt", "text/plain") == "text/plain"
    assert (
        classify_attachment(
            "b.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        is not None
    )
    # 双重判定：扩展名放行 + MIME 不匹配 → 拒绝
    assert classify_attachment("fake.png", "application/pdf") is None
    # 脚本 / 可执行 / 活动内容：一律拒绝
    for name, mime in (
        ("evil.exe", "application/octet-stream"),
        ("evil.msi", "application/x-msi"),
        ("run.sh", "text/x-shellscript"),
        ("run.ps1", "text/plain"),
        ("inject.js", "text/javascript"),
        ("inject.mjs", "text/javascript"),
        ("page.html", "text/html"),
        ("page.htm", "text/html"),
        ("vector.svg", "image/svg+xml"),
        ("macro.bat", "text/plain"),
        ("lib.jar", "application/java-archive"),
        ("script.py", "text/x-python"),
        ("noext", "application/octet-stream"),
    ):
        assert classify_attachment(name, mime) is None, name
