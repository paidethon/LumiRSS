"""Mail bridge + digest tests (phase2 G5).

Sanitization matrix (scripts/forms/remote-image beacons removed),
Message-ID + fingerprint dedupe, bearer-secret auth (constant-time
refusal), digest composition, and a REAL local SMTP round trip against
an in-process sink — no third-party mail is ever touched.
"""

import asyncio
import socket

import pytest
from aiosmtpd.controller import Controller

from lumirss.mail_bridge import (
    MailBridgeInvalid,
    MailBridgeStore,
    new_list_secret,
)
from lumirss.mail_digest import (
    DigestScheduler,
    DigestStore,
    compose_digest,
    send_digest_smtp,
)
from lumirss.mail_sanitize import html_to_text, sanitize_email_html
from lumirss.secrets_store import SecretsStore
from lumirss.storage import Database


def _run(coroutine):
    return asyncio.run(coroutine)


@pytest.fixture()
def bridge_db(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    _run(db.migrate())
    return MailBridgeStore(db)


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
    "<html><body><h1>第 42 期</h1>"
    "<script>alert(1)</script>"
    '<img src="https://tracker.example/pixel.gif">'
    '<a href="javascript:bad()">坏链接</a>'
    '<a href="https://example.com/read">好链接</a>'
    '<form action="/steal"><input name="x"></form>'
    "<p>正文内容</p>"
    "</body></html>\r\n"
    "--BOUND--\r\n"
)


def test_sanitize_email_html_matrix():
    dirty = (
        "<h1>标题</h1><script>alert(1)</script>"
        '<img src="https://t.example/x.gif">'
        '<a href="javascript:x()" onclick="y()">链接</a>'
        '<form><input name="a"></form><iframe src="https://x"></iframe>'
        "<p>正文</p>"
    )
    clean = sanitize_email_html(dirty)
    assert "<script>" not in clean and "alert(1)" not in clean
    assert "<img" not in clean and "t.example" not in clean
    assert "javascript:" not in clean and "onclick" not in clean
    assert "<form" not in clean and "<iframe" not in clean
    assert "<h1>标题</h1>" in clean and "<p>正文</p>" in clean
    text = html_to_text(dirty)
    assert "标题" in text and "正文" in text and "alert" not in text


def test_ingest_parses_dedupes_and_sanitizes(bridge_db):
    created = _run(bridge_db.create_list("每周快报"))

    first = _run(bridge_db.ingest(created, RAW_MAIL.encode()))
    assert first["status"] == "accepted"
    assert first["subject"] == "每周精选"
    assert first["attachments"] == 0

    # Replay: same Message-ID → duplicate, no second entry.
    replay = _run(bridge_db.ingest(created, RAW_MAIL.encode()))
    assert replay["status"] == "duplicate"

    entries = _run(bridge_db.list_entries(created.uuid))
    assert len(entries) == 1
    html_body = entries[0]["html"]
    assert "<h1>" in html_body
    assert "tracker.example" not in html_body
    assert "alert" not in html_body
    assert "javascript:" not in html_body
    text_body = entries[0]["text"]
    assert "第 42 期" in text_body


def test_ingest_rejects_oversize(bridge_db):
    created = _run(bridge_db.create_list("大邮件"))
    with pytest.raises(MailBridgeInvalid):
        _run(bridge_db.ingest(created, b"x" * (10 * 1024 * 1024 + 1)))


def test_fingerprint_dedupe_without_message_id(bridge_db):
    created = _run(bridge_db.create_list("无名邮件"))
    raw = RAW_MAIL.replace("Message-ID: <issue-42@example.com>\r\n", "")
    first = _run(bridge_db.ingest(created, raw.encode()))
    assert first["status"] == "accepted"
    replay = _run(bridge_db.ingest(created, raw.encode()))
    assert replay["status"] == "duplicate"


def test_attachment_metadata_only(bridge_db):
    created = _run(bridge_db.create_list("带附件"))
    raw = (
        "From: a@b.c\r\nSubject: with file\r\n"
        "Message-ID: <att-1@x>\r\n"
        "MIME-Version: 1.0\r\n"
        'Content-Type: multipart/mixed; boundary="AB"\r\n\r\n'
        "--AB\r\nContent-Type: text/plain\r\n\r\nhello\r\n"
        "--AB\r\n"
        'Content-Type: application/pdf; name="report.pdf"\r\n'
        'Content-Disposition: attachment; filename="report.pdf"\r\n'
        "Content-Transfer-Encoding: base64\r\n\r\n"
        "JVBERi0xLjQK\r\n"
        "--AB--\r\n"
    )
    result = _run(bridge_db.ingest(created, raw.encode()))
    assert result["status"] == "accepted"
    assert result["attachments"] == 1
    import json

    entries = _run(bridge_db.list_entries(created.uuid))
    meta = json.loads(entries[0]["attachment_meta"])
    assert meta[0]["filename"] == "report.pdf"
    assert "JVBERi0xLjQK" not in entries[0]["html"]  # body never stored


def test_webhook_auth(client):
    created = client.post("/api/v1/mail/bridge-lists", json={"name": "订阅列表"})
    assert created.status_code == 201
    secret = created.json()["secret"]
    assert secret

    # No/wrong bearer → 404-shaped refusal (does not leak list existence).
    assert (
        client.post(
            f"/api/mail/ingest/{created.json()['uuid']}", content=b"x"
        ).status_code
        == 404
    )
    wrong = client.post(
        f"/api/mail/ingest/{created.json()['uuid']}",
        content=b"x",
        headers={"Authorization": "Bearer " + "0" * 40},
    )
    assert wrong.status_code == 404

    # Correct bearer → accepted (or honest duplicate).
    ok = client.post(
        f"/api/mail/ingest/{created.json()['uuid']}",
        content=RAW_MAIL.encode(),
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert ok.status_code == 200
    assert ok.json()["status"] in ("accepted", "duplicate")


def test_secret_is_high_entropy():
    import re

    value = new_list_secret()
    assert re.fullmatch(r"[0-9a-f]{40}", value)


def test_digest_compose_and_local_smtp():
    """Real SMTP round trip against a local in-process sink."""
    items = [
        {"title": "文章一", "url": "https://example.com/1", "source": "源A"},
        {"title": "文章二 <加粗>", "url": "", "source": ""},
    ]
    text, html = compose_digest("LumiRSS 文章摘要", items)
    assert "文章一" in text and "文章二" in text
    assert "&lt;加粗&gt;" in html and "<strong>文章二" in html

    received: list = []

    class SinkHandler:
        async def handle_DATA(self, server, session, envelope):
            received.append(envelope)
            return "250 OK"

    server_sock = socket.socket()
    server_sock.bind(("127.0.0.1", 0))
    server_sock.listen(1)
    port = server_sock.getsockname()[1]
    server_sock.close()

    controller = Controller(SinkHandler(), hostname="127.0.0.1", port=port)
    controller.start()
    try:
        send_digest_smtp(
            host="127.0.0.1",
            port=port,
            user="",
            password="",
            from_addr="lumirss@local",
            to_addr="reader@local",
            subject="LumiRSS 文章摘要",
            text=text,
            html=html,
        )
        assert len(received) == 1
        assert "文章一" in received[0].content.decode("utf-8", errors="replace")
    finally:
        controller.stop()


def test_send_now_requires_configuration(client):
    response = client.post("/api/v1/digest/send-now", json={"entryRefs": []})
    assert response.status_code == 503
    assert response.json()["error"]["type"] == "smtp_not_configured"


def test_digest_scheduler_idempotent(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    _run(db.migrate())
    store = DigestStore(db, SecretsStore(tmp_path / "secrets.json"))
    _run(store.save({"enabled": True, "hour": _current_utc_hour()}))
    sends: list[int] = []

    async def send_fn():
        sends.append(1)
        await store.mark_sent()

    scheduler = DigestScheduler(db)
    # Same hour boundary twice → second call is a no-op (restart-safe).
    _run(scheduler.maybe_send(send_fn))
    _run(scheduler.maybe_send(send_fn))
    assert len(sends) == 1


def _current_utc_hour() -> int:
    from lumirss.util import utc_now

    return int(utc_now()[11:13])
