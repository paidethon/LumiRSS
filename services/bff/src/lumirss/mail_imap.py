"""IMAP polling adapter for newsletter inbound (phase2 G5, recovery
P0-06c).

Disabled by default: without configured IMAP credentials nothing polls.
Connection settings live in the secrets store as one JSON entry
(host/port/user/folder/ssl + the bound bridge list + poll interval);
the password is a separate write-only entry. The protocol surface is
injectable so tests run against a fake client — no real mailbox is
ever touched. Polling moves messages through the same MailBridgeStore
ingest path as the webhook (single chain, per-list dedupe).
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from lumirss.mail_bridge import MailBridgeStore
from lumirss.secrets_store import SecretsStore

# secrets-store entry names (NOT credential values; values live only in
# the encrypted-at-rest secrets file, never in source or logs).
_IMAP_CONFIG_ENTRY = "mail_imap"
_IMAP_PASSWORD_ENTRY = "mail_imap_password"

_POLL_LOCK = asyncio.Lock()
_INTERVAL_FLOOR_SECONDS = 60
_DEFAULT_INTERVAL_SECONDS = 300
_MAX_BATCH_PER_POLL = 20

_logger = logging.getLogger("lumirss.mail_imap")


class ImapNotConfigured(Exception):
    """IMAP credentials are not set in the secrets store."""


@dataclass(frozen=True)
class ImapConfig:
    host: str
    port: int
    user: str
    folder: str
    use_ssl: bool
    list_uuid: str = ""
    interval_seconds: int = _DEFAULT_INTERVAL_SECONDS

    @classmethod
    def from_dict(cls, value: dict) -> "ImapConfig":
        try:
            interval = int(value.get("intervalSeconds", _DEFAULT_INTERVAL_SECONDS))
        except (TypeError, ValueError):
            interval = _DEFAULT_INTERVAL_SECONDS
        try:
            port = int(value.get("port", 993))
        except (TypeError, ValueError):
            port = 993
        return cls(
            host=str(value.get("host", "")),
            port=port,
            user=str(value.get("user", "")),
            folder=str(value.get("folder", "INBOX")),
            use_ssl=bool(value.get("ssl", True)),
            list_uuid=str(value.get("listUuid", "")),
            interval_seconds=max(interval, _INTERVAL_FLOOR_SECONDS),
        )


def load_imap_config(secrets: SecretsStore) -> ImapConfig | None:
    raw = secrets.get(_IMAP_CONFIG_ENTRY)
    if not raw:
        return None
    import json

    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not data.get("host") or not data.get("user"):
        return None
    return ImapConfig.from_dict(data)


def save_imap_config(secrets: SecretsStore, config: dict, password: str | None) -> None:
    """Persist connection settings + optional password (write-only)."""
    import json

    secrets.set(_IMAP_CONFIG_ENTRY, json.dumps(config, ensure_ascii=False))
    if password:
        secrets.set(_IMAP_PASSWORD_ENTRY, password)


def imap_password_configured(secrets: SecretsStore) -> bool:
    return secrets.get(_IMAP_PASSWORD_ENTRY) is not None


def imap_password(secrets: SecretsStore) -> str:
    """The stored IMAP password (empty when unset); never logged."""
    return secrets.get(_IMAP_PASSWORD_ENTRY) or ""


# Protocol surface: (host, port, user, password, folder, ssl) -> raw bytes
Fetcher = Callable[[str, int, str, str, str, bool], Awaitable[list[bytes]]]


def probe_imap(
    host: str, port: int, user: str, password: str, folder: str, use_ssl: bool
) -> None:
    """Synchronous connectivity + auth probe (P0-06c).

    Logs in, selects the folder, disconnects — downloads nothing. Any
    failure raises (imaplib/OSError); the endpoint turns it into an
    honest ok/error report (never a stack trace to the client, never
    credentials in the message)."""
    import imaplib

    client = imaplib.IMAP4_SSL(host, port) if use_ssl else imaplib.IMAP4(host, port)
    try:
        client.login(user, password)
        client.select(folder)
    finally:
        with contextlib.suppress(Exception):
            client.logout()


async def _default_fetcher(
    host: str, port: int, user: str, password: str, folder: str, use_ssl: bool
) -> list[bytes]:
    """imaplib-based real fetch (only used with configured credentials)."""
    import imaplib

    def _sync() -> list[bytes]:
        imap_client = (
            imaplib.IMAP4_SSL(host, port) if use_ssl else imaplib.IMAP4(host, port)
        )
        try:
            imap_client.login(user, password)
            imap_client.select(folder)
            status, data = imap_client.search(None, "UNSEEN")
            if status != "OK":
                return []
            raw_messages: list[bytes] = []
            for message_set in data:
                for number in message_set.split():
                    status, parts = imap_client.fetch(number, "(RFC822)")
                    if status != "OK":
                        continue
                    for part in parts:
                        if isinstance(part, tuple) and part[1]:
                            raw_messages.append(part[1])
            return raw_messages
        finally:
            with contextlib.suppress(Exception):
                imap_client.logout()

    return await asyncio.to_thread(_sync)


class ImapAdapter:
    """Poll a mailbox and feed raw messages into the bridge store."""

    def __init__(
        self,
        secrets: SecretsStore,
        bridge: MailBridgeStore,
        fetcher: Fetcher | None = None,
    ) -> None:
        self._secrets = secrets
        self._bridge = bridge
        self._fetcher: Fetcher = fetcher or _default_fetcher

    async def poll_once(self, list_uuid: str) -> dict:
        """One bounded poll; honest report (not-configured = disabled
        feature, reported as an error type the UI can explain)."""
        config = load_imap_config(self._secrets)
        if config is None:
            raise ImapNotConfigured("IMAP 未配置。")
        password = self._secrets.get(_IMAP_PASSWORD_ENTRY) or ""
        target = await self._bridge.get_list(list_uuid)
        if target is None:
            from lumirss.mail_bridge import MailBridgeNotFound

            raise MailBridgeNotFound(list_uuid)
        async with _POLL_LOCK:
            raw_messages = await self._fetcher(
                config.host,
                config.port,
                config.user,
                password,
                config.folder,
                config.use_ssl,
            )
        results = []
        for raw in raw_messages[:_MAX_BATCH_PER_POLL]:  # bounded batch per poll
            results.append(await self._bridge.ingest(target, raw))
        return {
            "fetched": len(raw_messages),
            "ingested": results,
        }


async def mail_imap_poll_loop(app_state: Any) -> None:
    """Background IMAP poll (P0-06c): re-reads the config every cycle so
    interval/list changes apply without a restart; disabled (no config,
    no bound list) simply idles. Poll-first-sleep ordering keeps boot
    light; failures are logged, never fatal."""
    while True:
        config = load_imap_config(app_state.secrets_store)
        interval = (
            config.interval_seconds if config else _DEFAULT_INTERVAL_SECONDS
        )
        await asyncio.sleep(max(interval, _INTERVAL_FLOOR_SECONDS))
        if config is None or not config.list_uuid:
            continue
        try:
            adapter = ImapAdapter(
                app_state.secrets_store, MailBridgeStore(app_state.db)
            )
            await adapter.poll_once(config.list_uuid)
        except ImapNotConfigured:
            continue
        except Exception:  # noqa: BLE001 — polling must never kill the app
            _logger.exception("mail IMAP poll failed; will retry next cycle")


def build_mail_imap_task(app_state: Any) -> asyncio.Task:
    """Lifespan wiring factory — main.py creates the task in TWO lines
    (see the phase2 recovery report for the exact diff)."""
    return asyncio.create_task(mail_imap_poll_loop(app_state))
