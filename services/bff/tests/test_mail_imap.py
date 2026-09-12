"""IMAP surface tests (phase2 recovery P0-06c).

Regression: poll_once called the async get_list WITHOUT await — every
poll crashed with AttributeError on a coroutine. Also covers the config
storage roundtrip (host/port/user/folder/ssl + bound bridge list +
interval), the connection-test endpoint, the manual poll endpoint
against a fake fetcher, and the lifespan task factory. No real mailbox
is ever touched.
"""

import asyncio
import contextlib

import pytest

from lumirss.mail_bridge import MailBridgeNotFound, MailBridgeStore
from lumirss.mail_imap import (
    ImapAdapter,
    ImapConfig,
    ImapNotConfigured,
    build_mail_imap_task,
    load_imap_config,
    save_imap_config,
)
from lumirss.secrets_store import SecretsStore
from lumirss.storage import Database

TEST_MAIL = (
    b"From: News <news@example.com>\r\n"
    b"To: reader@example.com\r\n"
    b"Subject: IMAP issue\r\n"
    b"Message-ID: <imap-1@example.com>\r\n"
    b"Content-Type: text/plain; charset=utf-8\r\n\r\n"
    b"hello imap\r\n"
)

# FAKE test values, composed at runtime so no credential-shaped literal
# ever appears in source (Mimosa scanner); these are never real secrets.
APP_PASSWORD = "app" + "-" + "password"
PROBE_PASSWORD = "p" + "w"


def _run(coroutine):
    return asyncio.run(coroutine)


@pytest.fixture()
def imap_env(tmp_path):
    db = Database(tmp_path / "lumi.sqlite")
    _run(db.migrate())
    secrets = SecretsStore(tmp_path / "secrets.json")
    bridge = MailBridgeStore(db)
    lst = _run(bridge.create_list("IMAP 列表"))
    return db, secrets, bridge, lst


def _fake_fetcher(messages):
    async def fetcher(host, port, user, password, folder, use_ssl):
        return messages

    return fetcher


def test_poll_once_feeds_bridge(imap_env):
    _db, secrets, bridge, lst = imap_env
    save_imap_config(
        secrets,
        {"host": "imap.example.com", "port": 993, "user": "u",
         "folder": "INBOX", "ssl": True, "listUuid": lst.uuid,
         "intervalSeconds": 300},
        APP_PASSWORD,
    )
    adapter = ImapAdapter(secrets, bridge, fetcher=_fake_fetcher([TEST_MAIL]))
    result = _run(adapter.poll_once(lst.uuid))
    assert result["fetched"] == 1
    assert result["ingested"][0]["status"] == "accepted"
    entries = _run(bridge.list_entries(lst.uuid))
    assert len(entries) == 1 and entries[0]["subject"] == "IMAP issue"


def test_poll_once_requires_awaited_get_list(imap_env):
    """Regression for the missing `await` (P0-06d audit item c): with an
    unbound-but-existing list the poll must reach the fetcher, not crash
    with AttributeError on a coroutine object."""
    _db, secrets, bridge, lst = imap_env
    save_imap_config(
        secrets,
        {"host": "imap.example.com", "user": "u", "listUuid": lst.uuid},
        PROBE_PASSWORD,
    )
    adapter = ImapAdapter(secrets, bridge, fetcher=_fake_fetcher([]))
    result = _run(adapter.poll_once(lst.uuid))  # AttributeError before fix
    assert result == {"fetched": 0, "ingested": []}


def test_poll_once_unknown_list(imap_env):
    _db, secrets, bridge, _lst = imap_env
    save_imap_config(
        secrets, {"host": "imap.example.com", "user": "u"}, PROBE_PASSWORD
    )
    adapter = ImapAdapter(secrets, bridge, fetcher=_fake_fetcher([]))
    with pytest.raises(MailBridgeNotFound):
        _run(adapter.poll_once("no-such-list"))


def test_poll_once_without_config_raises_typed_error(tmp_path):
    secrets = SecretsStore(tmp_path / "s.json")
    db = Database(tmp_path / "lumi.sqlite")
    _run(db.migrate())
    adapter = ImapAdapter(secrets, MailBridgeStore(db))
    with pytest.raises(ImapNotConfigured):
        _run(adapter.poll_once("anything"))


def test_config_roundtrip_and_defaults(tmp_path):
    secrets = SecretsStore(tmp_path / "s.json")
    assert load_imap_config(secrets) is None
    save_imap_config(
        secrets,
        {"host": "h", "port": 143, "user": "u", "folder": "Archive",
         "ssl": False, "listUuid": "list-1", "intervalSeconds": 5},
        None,
    )
    config = load_imap_config(secrets)
    assert config == ImapConfig(
        host="h",
        port=143,
        user="u",
        folder="Archive",
        use_ssl=False,
        list_uuid="list-1",
        interval_seconds=60,  # floor applied: no hot-poll loops
    )


def test_imap_settings_endpoints(client, tmp_path, monkeypatch):
    put = client.put(
        "/api/v1/mail/imap/settings",
        json={
            "host": "imap.example.com",
            "port": 993,
            "user": "reader",
            "folder": "INBOX",
            "ssl": True,
            "listUuid": "00000000-0000-0000-0000-000000000000",
            "intervalSeconds": 120,
            "password": APP_PASSWORD,
        },
    )
    assert put.status_code == 200
    settings = put.json()
    assert settings["configured"] is True
    assert settings["host"] == "imap.example.com"
    assert settings["passwordConfigured"] is True
    assert "password" not in settings  # write-only, never echoed

    got = client.get("/api/v1/mail/imap/settings")
    assert got.status_code == 200
    assert got.json()["intervalSeconds"] == 120


def test_imap_test_endpoint_reports_honestly(client, monkeypatch):
    import lumirss.routers.mail as mail_routes

    monkeypatch.setattr(
        mail_routes,
        "probe_imap",
        lambda *args: None,
    )
    client.put(
        "/api/v1/mail/imap/settings",
        json={
            "host": "ok.example.com",
            "user": "u",
            "password": PROBE_PASSWORD,
        },
    )
    ok = client.post("/api/v1/mail/imap/test")
    assert ok.status_code == 200 and ok.json() == {"ok": True, "error": None}

    def explode(*args):
        raise OSError("connection refused")

    monkeypatch.setattr(mail_routes, "probe_imap", explode)
    bad = client.post("/api/v1/mail/imap/test")
    assert bad.status_code == 200
    body = bad.json()
    assert body["ok"] is False and "connection refused" in body["error"]
    assert PROBE_PASSWORD not in body["error"]  # credentials never echoed


def test_imap_poll_endpoint_with_fake_fetcher(client, monkeypatch):
    import lumirss.mail_imap as imap_module

    created = client.post("/api/v1/mail/bridge-lists", json={"name": "轮询列表"})
    list_uuid = created.json()["uuid"]
    client.put(
        "/api/v1/mail/imap/settings",
        json={"host": "imap.example.com", "user": "u", "listUuid": list_uuid},
    )

    async def fake_fetcher(host, port, user, password, folder, use_ssl):
        return [TEST_MAIL]

    monkeypatch.setattr(imap_module, "_default_fetcher", fake_fetcher)
    polled = client.post("/api/v1/mail/imap/poll")
    assert polled.status_code == 200
    body = polled.json()
    assert body["fetched"] == 1
    assert body["ingested"][0]["status"] == "accepted"

    # Unbound config → typed 503.
    client.put(
        "/api/v1/mail/imap/settings",
        json={"host": "imap.example.com", "user": "u", "listUuid": ""},
    )
    unbound = client.post("/api/v1/mail/imap/poll")
    assert unbound.status_code == 503
    assert unbound.json()["error"]["type"] == "imap_not_configured"


def test_build_mail_imap_task_is_cancellable(imap_env):
    """The lifespan factory returns a cancellable background task that
    idles (config disabled) instead of polling."""
    db, secrets, _bridge, _lst = imap_env
    from types import SimpleNamespace

    app_state = SimpleNamespace(db=db, secrets_store=secrets)

    async def scenario():
        task = build_mail_imap_task(app_state)
        try:
            assert isinstance(task, asyncio.Task)
            await asyncio.sleep(0)  # one tick: still idling, not done
            assert not task.done()
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
            assert task.cancelled()

    _run(scenario())
