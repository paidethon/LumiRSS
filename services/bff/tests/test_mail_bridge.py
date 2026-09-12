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
from defusedxml import ElementTree as SafeET

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


# -- Recovery P0-06 ----------------------------------------------------------


def test_same_message_id_to_two_lists_both_stored(bridge_db):
    """Per-list dedupe (P0-06e): the same Message-ID delivered to two
    bridge lists must be stored TWICE (the old global PK silently
    dropped the second list's copy)."""
    list_a = _run(bridge_db.create_list("列表 A"))
    list_b = _run(bridge_db.create_list("列表 B"))
    first = _run(bridge_db.ingest(list_a, RAW_MAIL.encode()))
    second = _run(bridge_db.ingest(list_b, RAW_MAIL.encode()))
    assert first["status"] == "accepted"
    assert second["status"] == "accepted"
    assert len(_run(bridge_db.list_entries(list_a.uuid))) == 1
    assert len(_run(bridge_db.list_entries(list_b.uuid))) == 1


def test_fingerprint_stable_across_second_boundaries(bridge_db, monkeypatch):
    """The fallback identity is content-derived, never wall-clock: a
    re-delivery far in the future still dedupes deterministically (the
    old fingerprint mixed in second-resolution utc_now and only passed
    when both ingests landed in the same second)."""
    import lumirss.mail_bridge as bridge_module

    created = _run(bridge_db.create_list("无名邮件"))
    raw = RAW_MAIL.replace("Message-ID: <issue-42@example.com>\r\n", "")
    first = _run(bridge_db.ingest(created, raw.encode()))
    assert first["status"] == "accepted"
    # Move the persisted clock far forward — identity must not move.
    monkeypatch.setattr(
        bridge_module, "utc_now", lambda: "2030-06-01T00:00:00+00:00"
    )
    replay = _run(bridge_db.ingest(created, raw.encode()))
    assert replay["status"] == "duplicate"
    assert len(_run(bridge_db.list_entries(created.uuid))) == 1


def test_ingest_transaction_all_or_nothing(bridge_db):
    """Seen rows and the entry body commit together (P0-06f): a failure
    between statements rolls back the whole batch — no orphan dedupe row
    that would silently swallow the retried mail forever."""
    import sqlite3

    created = _run(bridge_db.create_list("原子性"))
    statements = [
        (
            "INSERT INTO mail_seen (list_uuid, identity, seen_at) VALUES (?, ?, ?)",
            (created.uuid, "<mid@x>", "2026-01-01T00:00:00+00:00"),
        ),
        # Malformed on purpose: crashes mid-transaction.
        (
            "INSERT INTO mail_bridge_entries (list_uuid, message_id) VALUES (?, ?)",
            (created.uuid,),
        ),
    ]
    with pytest.raises(sqlite3.ProgrammingError):
        _run(bridge_db._transaction(statements))
    row = _run(
        bridge_db._db.fetch_one(
            "SELECT identity FROM mail_seen WHERE list_uuid = ? AND identity = ?",
            (created.uuid, "<mid@x>"),
        )
    )
    assert row is None  # rolled back together


def test_delete_list_removes_all_state(bridge_db):
    created = _run(bridge_db.create_list("待删列表"))
    _run(bridge_db.ingest(created, RAW_MAIL.encode()))
    assert _run(bridge_db.delete_list(created.uuid)) is True
    assert _run(bridge_db.get_list(created.uuid)) is None
    assert _run(bridge_db.list_entries(created.uuid)) == []
    row = _run(
        bridge_db._db.fetch_one(
            "SELECT identity FROM mail_seen WHERE list_uuid = ?",
            (created.uuid,),
        )
    )
    assert row is None
    # Unknown uuid → honest False.
    assert _run(bridge_db.delete_list("no-such-uuid")) is False


def test_migration_0018_copies_legacy_seen_rows(tmp_path):
    """Forward-only 0018: legacy global-PK mail_seen rows are copied
    into the per-list (list_uuid, identity) table, so Message-ID dedupe
    survives the upgrade (dropping the old table is safe — dedupe cache
    only, entries live in mail_bridge_entries)."""
    db = Database(tmp_path / "lumi.sqlite")
    _run(db.migrate())
    # Recreate the LEGACY shape with legacy rows, then re-run 0018.
    _run(db.execute("DROP TABLE mail_seen"))
    _run(
        db.execute(
            "CREATE TABLE mail_seen (message_id TEXT PRIMARY KEY, list_uuid TEXT NOT NULL, seen_at TEXT NOT NULL)"
        )
    )
    _run(
        db.execute(
            "INSERT INTO mail_seen (message_id, list_uuid, seen_at) VALUES (?, ?, ?)",
            ("<legacy@example.com>", "list-1", "2026-01-01T00:00:00+00:00"),
        )
    )
    _run(
        db.execute(
            "DELETE FROM schema_migrations WHERE version = 18"
        )
    )
    db.invalidate_migration_cache()
    applied = _run(db.migrate())
    assert 18 in applied
    row = _run(
        db.fetch_one(
            "SELECT list_uuid, identity FROM mail_seen WHERE identity = ?",
            ("<legacy@example.com>",),
        )
    )
    assert row is not None and str(row["list_uuid"]) == "list-1"
    # Composite PK: same identity under another list is allowed now.
    _run(
        db.execute(
            "INSERT INTO mail_seen (list_uuid, identity, seen_at) VALUES (?, ?, ?)",
            ("list-2", "<legacy@example.com>", "2026-01-01T00:00:00+00:00"),
        )
    )


def test_digest_scheduler_respects_enabled_and_hour(tmp_path):
    from datetime import datetime

    db = Database(tmp_path / "lumi.sqlite")
    _run(db.migrate())
    store = DigestStore(db, SecretsStore(tmp_path / "secrets.json"))
    sends: list[int] = []

    async def send_fn():
        sends.append(1)
        await store.mark_sent()

    scheduler = DigestScheduler(db)
    local_hour = datetime.now().hour

    # Disabled → never sends (scheduled path respects `enabled`).
    _run(store.save({"enabled": False, "hour": local_hour}))
    _run(scheduler.maybe_send(send_fn))
    assert sends == []

    # Wrong hour → no send.
    _run(store.save({"enabled": True, "hour": (local_hour + 1) % 24}))
    _run(scheduler.maybe_send(send_fn))
    assert sends == []

    # Enabled + matching hour → exactly one send (idempotent restart).
    _run(store.save({"enabled": True, "hour": local_hour}))
    _run(scheduler.maybe_send(send_fn))
    _run(scheduler.maybe_send(send_fn))
    assert len(sends) == 1


def test_scheduled_digest_source_and_limit_drive_behavior(tmp_path, monkeypatch):
    """`source` gates the scheduled send (only `mail` is server-derived
    today — honest error, never an empty email); `limitCount` bounds the
    item pool; items come from stored bridge entries, never client text."""
    from types import SimpleNamespace

    import lumirss.mail_digest as digest_module

    db = Database(tmp_path / "lumi.sqlite")
    _run(db.migrate())
    secrets = SecretsStore(tmp_path / "secrets.json")
    store = DigestStore(db, secrets)
    _run(
        store.save(
            {
                "enabled": True,
                "source": "mail",
                "limitCount": 2,
                "smtpHost": "127.0.0.1",
                "toAddr": "reader@local",
            }
        )
    )
    bridge = MailBridgeStore(db)
    for name in ("列表一", "列表二"):
        lst = _run(bridge.create_list(name))
        _run(bridge.ingest(lst, RAW_MAIL.replace("issue-42", name).encode()))
    items = _run(digest_module.build_bridge_digest_items(bridge, 2))
    assert len(items) == 2  # limitCount bounds the pool
    assert {item["title"] for item in items} == {"每周精选"}
    assert all(item["url"] == "" for item in items)  # server-derived only

    sent: list[dict] = []

    def fake_send(**kwargs):
        sent.append(kwargs)

    monkeypatch.setattr(digest_module, "send_digest_smtp", fake_send)
    app_state = SimpleNamespace(db=db, secrets_store=secrets)
    _run(digest_module._send_scheduled_digest(app_state))
    assert len(sent) == 1
    assert "每周精选" in sent[0]["text"]

    # Non-mail source → honest lastError, nothing sent.
    _run(store.save({"source": "read_later"}))
    _run(digest_module._send_scheduled_digest(app_state))
    assert len(sent) == 1  # unchanged
    settings = _run(store.load())
    assert "read_later" in (settings["lastError"] or "")


def test_digest_send_now_server_derived(client, monkeypatch):
    """send-now builds content ONLY from stored bridge entries (P0-06b/j):
    empty selection with no bridge mail → 422 no_digest_items; with mail
    → real subjects; client-supplied title/url text is never trusted."""
    import lumirss.mail_digest as digest_module
    import lumirss.routers.mail as mail_routes

    class _Adapter:
        async def subscribe(self, url, title=""):
            return None

    monkeypatch.setattr(
        mail_routes, "_get_control_adapter", lambda request: _Adapter()
    )
    created = client.post(
        "/api/v1/mail/bridge-lists", json={"name": "快报"}
    ).json()
    secret = created["secret"]

    # No bridge mail yet → honest 422, never an empty email.
    config = client.put(
        "/api/v1/digest/settings",
        json={"smtpHost": "127.0.0.1", "toAddr": "reader@local"},
    )
    assert config.status_code == 200
    empty = client.post("/api/v1/digest/send-now", json={"entryRefs": []})
    assert empty.status_code == 422
    assert empty.json()["error"]["type"] == "no_digest_items"

    # A junk ref (client-supplied title/url) is NOT a resolvable entry.
    junk = client.post(
        "/api/v1/digest/send-now",
        json={"entryRefs": [{"title": "假文章", "url": "https://attacker.example"}]},
    )
    assert junk.status_code == 422

    # Real mail arrives → send-now derives the item from the stored row.
    ingest = client.post(
        f"/api/mail/ingest/{created['uuid']}",
        content=RAW_MAIL.encode(),
        headers={"Authorization": f"Bearer {secret}"},
    )
    assert ingest.status_code == 200

    sent: list[dict] = []

    def fake_send(**kwargs):
        sent.append(kwargs)

    monkeypatch.setattr(digest_module, "send_digest_smtp", fake_send)
    ok = client.post("/api/v1/digest/send-now", json={"entryRefs": []})
    assert ok.status_code == 200
    assert ok.json()["status"] == "sent"
    assert len(sent) == 1
    assert "每周精选" in sent[0]["text"]
    assert "假文章" not in sent[0]["html"]
    assert "attacker.example" not in sent[0]["html"]

    # Explicit entryRefs resolve against stored entries by messageId.
    message_id = ingest.json()["messageId"]
    explicit = client.post(
        "/api/v1/digest/send-now",
        json={"entryRefs": [{"messageId": message_id}]},
    )
    assert explicit.status_code == 200
    assert "每周精选" in sent[1]["text"]

    # An explicit ref matching nothing → 422 (honest).
    missing = client.post(
        "/api/v1/digest/send-now",
        json={"entryRefs": [{"messageId": "<ghost@nowhere>"}]},
    )
    assert missing.status_code == 422


def test_bridge_list_auto_subscribe_reports_failure(client, monkeypatch):
    """FreshRSS auto-subscribe (P0-06i): success → no subscribeFailed;
    failure → honest subscribeFailed text, create still succeeds."""
    import lumirss.routers.mail as mail_routes

    class _FailingAdapter:
        async def subscribe(self, url, title=""):
            raise RuntimeError("FreshRSS 不可达")

    monkeypatch.setattr(
        mail_routes, "_get_control_adapter", lambda request: _FailingAdapter()
    )
    created = client.post("/api/v1/mail/bridge-lists", json={"name": "失败订阅"})
    assert created.status_code == 201
    body = created.json()
    assert "自动订阅失败" in body["subscribeFailed"]
    assert body["atomPath"].startswith("/feeds/mail/")

    # Unconfigured FreshRSS → honest status, create still succeeds.
    def raise_config(request):
        from lumirss.adapters.freshrss import ConfigError

        raise ConfigError("FreshRSS not configured")

    monkeypatch.setattr(mail_routes, "_get_control_adapter", raise_config)
    second = client.post("/api/v1/mail/bridge-lists", json={"name": "未配置"})
    assert second.status_code == 201
    assert "FreshRSS 未配置" in second.json()["subscribeFailed"]


def test_mail_atom_rfc4287_shape(client, monkeypatch):
    """Per-list Atom (P0-06h): feed id/title/updated (never empty)/
    link rel=self (absolute)/author; entries carry updated + author."""
    import lumirss.routers.mail as mail_routes

    class _Adapter:
        async def subscribe(self, url, title=""):
            return None

    monkeypatch.setenv("LUMIRSS_ATOM_BASE_URL", "http://bff:8000")
    monkeypatch.setattr(
        mail_routes, "_get_control_adapter", lambda request: _Adapter()
    )
    created = client.post("/api/v1/mail/bridge-lists", json={"name": "周报 <A&>"})
    body = created.json()
    ingest = client.post(
        f"/api/mail/ingest/{body['uuid']}",
        content=RAW_MAIL.encode(),
        headers={"Authorization": f"Bearer {body['secret']}"},
    )
    assert ingest.status_code == 200

    atom = client.get(body["atomPath"])
    assert atom.status_code == 200
    assert "atom+xml" in atom.headers["content-type"]
    root = SafeET.fromstring(atom.text)
    ns = "{http://www.w3.org/2005/Atom}"
    assert root.tag == f"{ns}feed"
    assert root.find(f"{ns}title").text == "周报 <A&>"
    assert root.find(f"{ns}id").text.startswith("urn:lumirss:mailbridge:")
    feed_updated = root.find(f"{ns}updated").text
    assert feed_updated  # never empty, even before entries
    self_link = [
        link for link in root.findall(f"{ns}link") if link.get("rel") == "self"
    ]
    assert self_link[0].get("href").startswith("http://bff:8000/feeds/mail/")
    assert root.find(f"{ns}author/{ns}name") is not None
    entries = root.findall(f"{ns}entry")
    assert len(entries) == 1
    entry = entries[0]
    assert entry.find(f"{ns}id").text.startswith("urn:lumirss:mailentry:")
    assert entry.find(f"{ns}title").text == "每周精选"
    assert entry.find(f"{ns}updated") is not None and entry.find(f"{ns}updated").text
    assert "Newsletter" in entry.find(f"{ns}author/{ns}name").text  # From header
    assert entry.find(f"{ns}content") is not None
    assert "<script>" not in atom.text  # sanitized, not executable markup

    # Empty list → feed updated falls back to the list creation time.
    empty = client.post("/api/v1/mail/bridge-lists", json={"name": "空列表"})
    empty_atom = SafeET.fromstring(client.get(empty.json()["atomPath"]).text)
    assert empty_atom.find(f"{ns}updated").text == empty.json()["createdAt"]
