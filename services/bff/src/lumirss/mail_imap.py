"""IMAP polling adapter for newsletter inbound (phase2 G5, optional).

Disabled by default: without configured IMAP credentials nothing polls.
Credentials live in the secrets store (host/port/user/password); the
protocol surface is injectable so tests run against a fake client — no
real mailbox is ever touched. Polling moves messages through the same
MailBridgeStore ingest path as the webhook (single chain).
"""

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from lumirss.mail_bridge import MailBridgeStore
from lumirss.secrets_store import SecretsStore

# secrets-store entry names (NOT credential values; values live only in
# the encrypted-at-rest secrets file, never in source or logs).
_IMAP_CONFIG_ENTRY = "mail_imap"
_IMAP_PASSWORD_ENTRY = "mail_imap_password"

_POLL_LOCK = asyncio.Lock()


class ImapNotConfigured(Exception):
    """IMAP credentials are not set in the secrets store."""


@dataclass(frozen=True)
class ImapConfig:
    host: str
    port: int
    user: str
    folder: str
    use_ssl: bool

    @classmethod
    def from_dict(cls, value: dict) -> "ImapConfig":
        return cls(
            host=str(value.get("host", "")),
            port=int(value.get("port", 993)),
            user=str(value.get("user", "")),
            folder=str(value.get("folder", "INBOX")),
            use_ssl=bool(value.get("ssl", True)),
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


# Protocol surface: (host, port, user, password, folder, ssl) -> raw bytes
Fetcher = Callable[[str, int, str, str, str, bool], Awaitable[list[bytes]]]


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
        target = self._bridge.get_list(list_uuid)
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
        for raw in raw_messages[:20]:  # bounded batch per poll
            results.append(await self._bridge.ingest(target, raw))
        return {
            "fetched": len(raw_messages),
            "ingested": results,
        }
