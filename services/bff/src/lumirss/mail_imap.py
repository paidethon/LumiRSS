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
_UIDVALIDITY_ENTRY = "mail_imap_uidvalidity"  # F106：回填一致性标记

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
    enabled: bool = True  # F007：False = 轮询与手动拉信均直接跳过

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
            enabled=bool(value.get("enabled", True)),
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
        feature, reported as an error type the UI can explain).

        F007：enabled=False → 直接跳过（返回 skipped 状态，不触碰邮箱）。"""
        config = load_imap_config(self._secrets)
        if config is None:
            raise ImapNotConfigured("IMAP 未配置。")
        if not config.enabled:
            return {"fetched": 0, "ingested": [], "skipped": True}
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
    """Background IMAP poll (P0-06c), per user (0067/O163): every active
    user's own IMAP config is polled under that user's context; config
    re-reads every cycle so interval/list changes apply without a
    restart. Failures are isolated per user and never fatal."""
    from lumirss.user_scope import for_each_active_user

    while True:
        await asyncio.sleep(_DEFAULT_INTERVAL_SECONDS)

        async def poll_user(_uid: str) -> None:
            config = load_imap_config(app_state.secrets_store)
            if config is None or not config.list_uuid or not config.enabled:
                return  # F007：enabled=False 调度入口同样直接跳过
            adapter = ImapAdapter(
                app_state.secrets_store, MailBridgeStore(app_state.db)
            )
            await adapter.poll_once(config.list_uuid)

        try:
            await for_each_active_user(app_state, poll_user)
        except Exception:  # noqa: BLE001 — polling must never kill the app
            _logger.exception("mail IMAP poll cycle failed; will retry")


def build_mail_imap_task(app_state: Any) -> asyncio.Task:
    """Lifespan wiring factory — main.py creates the task in TWO lines
    (see the phase2 recovery report for the exact diff)."""
    return asyncio.create_task(mail_imap_poll_loop(app_state))


# ---- F106 邮件历史回填 ------------------------------------------------------

BackfillFetcher = Callable[
    [str, int, str, str, str, bool, str, tuple[int, int] | None],
    Awaitable[tuple[str, list[tuple[int, bytes]]]],
]
"""(host, port, user, password, folder, ssl, since_iso, uid_range) →
(uidvalidity, [(uid, raw_bytes)]). 有界：实现负责数量上限。"""

_MAX_BACKFILL = 200
_MAX_SAMPLE = 20


def _default_backfill_fetcher(
    host: str,
    port: int,
    user: str,
    password: str,
    folder: str,
    use_ssl: bool,
    since: str,
    uid_range: tuple[int, int] | None,
) -> Awaitable[tuple[str, list[tuple[int, bytes]]]]:
    """imaplib-based bounded fetch by date or UID range (real creds only)."""
    import imaplib

    async def _run() -> tuple[str, list[tuple[int, bytes]]]:
        def _sync() -> tuple[str, list[tuple[int, bytes]]]:
            client = (
                imaplib.IMAP4_SSL(host, port) if use_ssl else imaplib.IMAP4(host, port)
            )
            try:
                client.login(user, password)
                status, _data = client.select(folder, readonly=True)
                if status != "OK":
                    return "", []
                # UIDVALIDITY 出现在 SELECT 的 untagged 响应里（imaplib 暂存）。
                uidvalidity = ""
                untagged = getattr(client, "untagged_responses", {}) or {}
                values = untagged.get("UIDVALIDITY") or untagged.get(b"UIDVALIDITY") or []
                if values:
                    last = values[-1]
                    uidvalidity = last.decode() if isinstance(last, bytes) else str(last)
                if uid_range is not None:
                    query = f"UID {uid_range[0]}:{uid_range[1]}"
                else:
                    query = f"SINCE {since}" if since else "ALL"
                status, found = client.uid("search", None, query)
                if status != "OK":
                    return uidvalidity, []
                messages: list[tuple[int, bytes]] = []
                for chunk in found:
                    for number in chunk.split()[:_MAX_BACKFILL]:
                        status, parts = client.uid("fetch", number, "(RFC822)")
                        if status != "OK":
                            continue
                        for part in parts:
                            if isinstance(part, tuple) and part[1]:
                                messages.append((int(number), part[1]))
                return uidvalidity, messages[:_MAX_BACKFILL]
            finally:
                with contextlib.suppress(Exception):
                    client.logout()

        return await asyncio.to_thread(_sync)

    return _run()


async def _load_uidvalidity(secrets: SecretsStore) -> str:
    value = secrets.get(_UIDVALIDITY_ENTRY)
    return str(value or "")


def _store_uidvalidity(secrets: SecretsStore, uidvalidity: str) -> None:
    if uidvalidity:
        secrets.set(_UIDVALIDITY_ENTRY, uidvalidity)


async def backfill_mail_history(
    secrets: SecretsStore,
    bridge: MailBridgeStore,
    *,
    since: str | None = None,
    uids: list[int] | None = None,
    dry_run: bool = False,
    fetcher: BackfillFetcher | None = None,
) -> dict[str, Any]:
    """F106：历史邮件回填。dry_run → 采样 ≤20（uid/主题/日期）零写入；
    执行 → 逐封走既有幂等身份（Message-ID）入桥。UIDVALIDITY 与上次
    记录不一致 → 中止（诚实：服务器邮箱可能已重建，UID 语义已失效）。
    同步有界（≤200 封）；坏邮件计入 failed 不中断。"""
    config = load_imap_config(secrets)
    if config is None or not config.list_uuid:
        raise ImapNotConfigured("IMAP 未配置或未绑定 bridge 列表。")
    uid_range: tuple[int, int] | None = None
    if uids is not None:
        clean_uids = sorted({int(u) for u in uids})[:_MAX_BACKFILL]
        if clean_uids:
            uid_range = (clean_uids[0], clean_uids[-1])
    target = await bridge.get_list(config.list_uuid)
    if target is None:
        from lumirss.mail_bridge import MailBridgeNotFound

        raise MailBridgeNotFound(config.list_uuid)
    fetch = fetcher or _default_backfill_fetcher
    uidvalidity, messages = await fetch(
        config.host,
        config.port,
        config.user,
        imap_password(secrets),
        config.folder,
        config.use_ssl,
        since or "",
        uid_range,
    )
    stored_validity = await _load_uidvalidity(secrets)
    validity_note: str | None = None
    if uidvalidity and stored_validity and str(uidvalidity) != str(stored_validity):
        if not dry_run:
            return {
                "aborted": True,
                "reason": "uidvalidity_changed",
                "storedUidvalidity": stored_validity,
                "currentUidvalidity": str(uidvalidity),
                "processed": 0,
                "created": 0,
                "skippedDup": 0,
                "failed": [],
            }
        validity_note = "uidvalidity_changed"
    import email as _email
    import email.policy as _policy

    def _headers(raw: bytes) -> tuple[str, str]:
        try:
            message = _email.message_from_bytes(raw, policy=_policy.default)
            subject = str(message.get("Subject", "") or "")[:200]
            date = str(message.get("Date", "") or "")[:80]
            return subject, date
        except Exception:  # noqa: BLE001 — 坏载荷诚实占位，不中断采样
            return "(解析失败)", ""

    if dry_run:
        sample = []
        for uid, raw in messages[:_MAX_SAMPLE]:
            subject, date = _headers(raw)
            sample.append({"uid": uid, "subject": subject, "date": date})
        return {
            "dryRun": True,
            "sample": sample,
            "matched": len(messages),
            "uidvalidity": str(uidvalidity or "") or None,
            "note": validity_note,
        }
    created = 0
    skipped_dup = 0
    failed: list[dict[str, str]] = []
    processed = 0
    for uid, raw in messages[:_MAX_BACKFILL]:
        processed += 1
        try:
            result = await bridge.ingest(target, raw)
        except Exception as exc:  # noqa: BLE001 — 坏邮件诚实计数，不中断
            failed.append({"uid": str(uid), "reason": str(exc)[:50] or "parse_failed"})
            continue
        if result.get("status") == "accepted":
            created += 1
        else:
            skipped_dup += 1
    _store_uidvalidity(secrets, str(uidvalidity))
    return {
        "processed": processed,
        "created": created,
        "skippedDup": skipped_dup,
        "failed": failed[:50],
    }
