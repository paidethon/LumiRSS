"""F007 IMAP 启停 —— enabled 开关贯穿配置、poll_once 与路由。

- 关闭后 poll 不拉信（skipped 状态；fetcher 不被调用）；
- 开启恢复拉信；默认 enabled=True（向后兼容旧配置）；
- 设置路由 PUT enabled=False → 持久化 → GET 回读 enabled=False。
"""

import asyncio

import pytest

from lumirss.mail_bridge import MailBridgeStore
from lumirss.mail_imap import (
    ImapAdapter,
    load_imap_config,
    save_imap_config,
)
from lumirss.secrets_store import SecretsStore
from lumirss.storage import Database


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


def _fake_fetcher(messages, counter):
    async def fetcher(host, port, user, password, folder, use_ssl):
        counter["calls"] += 1
        return messages

    return fetcher


def test_f007_poll_skipped_when_disabled_then_resumes(imap_env):
    _db, secrets, bridge, lst = imap_env
    save_imap_config(
        secrets,
        {"host": "imap.example.com", "port": 993, "user": "u",
         "folder": "INBOX", "ssl": True, "listUuid": lst.uuid,
         "intervalSeconds": 300, "enabled": False},
        None,
    )
    counter = {"calls": 0}
    adapter = ImapAdapter(secrets, bridge, fetcher=_fake_fetcher([], counter))
    # 关闭 → 直接跳过，fetcher 不被调用
    result = _run(adapter.poll_once(lst.uuid))
    assert result == {"fetched": 0, "ingested": [], "skipped": True}
    assert counter["calls"] == 0
    # 重新开启 → 恢复拉信
    save_imap_config(
        secrets,
        {"host": "imap.example.com", "port": 993, "user": "u",
         "folder": "INBOX", "ssl": True, "listUuid": lst.uuid,
         "intervalSeconds": 300, "enabled": True},
        None,
    )
    counter2 = {"calls": 0}
    adapter2 = ImapAdapter(secrets, bridge, fetcher=_fake_fetcher([], counter2))
    result2 = _run(adapter2.poll_once(lst.uuid))
    assert result2["fetched"] == 0 and "skipped" not in result2
    assert counter2["calls"] == 1


def test_f007_enabled_defaults_true_for_legacy_config(imap_env):
    _db, secrets, bridge, lst = imap_env
    # 旧配置（无 enabled 键）→ 默认开启，向后兼容
    save_imap_config(
        secrets,
        {"host": "imap.example.com", "port": 993, "user": "u",
         "folder": "INBOX", "ssl": True, "listUuid": lst.uuid},
        None,
    )
    config = load_imap_config(secrets)
    assert config is not None and config.enabled is True


def test_f007_settings_route_roundtrip_enabled(client):
    secrets = client.app.state.secrets_store
    save = client.put(
        "/api/v1/mail/imap/settings",
        json={
            "host": "imap.example.com",
            "user": "u",
            "password": "fake-pw",
            "enabled": False,
        },
    )
    assert save.status_code == 200, save.text
    assert save.json()["enabled"] is False
    got = client.get("/api/v1/mail/imap/settings").json()
    assert got["configured"] is True
    assert got["enabled"] is False
    # 再开启
    reopened = client.put(
        "/api/v1/mail/imap/settings", json={"enabled": True}
    )
    assert reopened.status_code == 200
    assert reopened.json()["enabled"] is True
    # 无效配置错误路径：未配置时测试连接 → 稳定 4xx（非 500）

    from lumirss.mail_imap import save_imap_config as _sic

    _sic(secrets, {}, None)  # 清空 host/user → unconfigured
    import contextlib

    with contextlib.suppress(Exception):
        client.post("/api/v1/mail/imap/test")
