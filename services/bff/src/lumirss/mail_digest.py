"""Outbound digest (phase2 G5, recovery P0-06a/b/j).

Selected items → text+HTML email → the user's own SMTP relay → the
single configured address. Content is ALWAYS server-derived (bridge
lists' recent entries — P0-06b): the client can reference stored
entries but never inject arbitrary title/url text, so the relay cannot
be abused as an open sender.

SMTP credentials live in the secrets store (never SQLite, never logs);
sending happens only when explicitly configured (disabled by default).
``send-now`` is an explicit user action and ignores ``enabled``; the
scheduled path only sends when ``enabled`` is true (P0-06j). Scheduling
is timezone-aware (migration 0024): ``hour`` is interpreted in the
configured IANA timezone; ``timezone=''`` keeps the historical server-
local semantics. Errors are typed for honest UI (unreachable / auth
failed / TLS). Tests use a local in-process SMTP sink (aiosmtpd-style)
— real third-party mail is never touched.
"""

import asyncio
import logging
import smtplib
import ssl
from datetime import datetime, timedelta
from email.message import EmailMessage
from typing import Any
from zoneinfo import ZoneInfo

from lumirss.mail_bridge import MailBridgeStore
from lumirss.secrets_store import SecretsStore
from lumirss.storage import Database
from lumirss.util import utc_now

_DEFAULT_LIMIT = 10
_MAX_LIMIT = 50
_DIGEST_TITLE = "LumiRSS 文章摘要"
# Background scheduler cadence (seconds). One tick per 5 minutes is
# plenty for hour-boundary scheduling and keeps restart catch-up tight.
_SCHEDULE_TICK_SECONDS = 300
_VALID_SOURCES = ("read_later", "starred", "mail")


class SmtpNotConfigured(Exception):
    """SMTP relay or recipient address is missing."""


class SmtpSendFailed(Exception):
    """The relay refused or dropped the message."""

    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


def _normalize_timezone(value: Any, fallback: str) -> str:
    """''（服务器本地）或合法 IANA 名称；非法输入保留现值。"""
    if not isinstance(value, str):
        return fallback
    name = value.strip()
    if name == "":
        return ""
    try:
        ZoneInfo(name)
    except Exception:  # noqa: BLE001 — ZoneInfo 的失败形态不固定
        return fallback
    return name


def now_in_timezone(timezone: str) -> datetime:
    """配置时区下的当前时间；'' 或无效名回退服务器本地。"""
    if timezone:
        try:
            return datetime.now(ZoneInfo(timezone))
        except Exception:  # noqa: BLE001
            pass
    return datetime.now().astimezone()


def next_send_at(now: datetime, hour: int) -> str:
    """下一次发送时间（配置时区的墙钟）：今天 HH:00 已过则明天 HH:00。

    DST 语义：墙钟构造（ZoneInfo fold 规则）——春令时缺失的墙钟时间
    落到其后第一个真实时刻；只发送一次由 last_sent 的边界比较保证，
    与该构造方式解耦。"""
    candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate.isoformat()


def digest_settings_defaults() -> dict[str, Any]:
    return {
        "enabled": False,
        "hour": 8,
        "source": "read_later",
        "limitCount": _DEFAULT_LIMIT,
        "smtpHost": "",
        "smtpPort": 587,
        "smtpUser": "",
        "fromAddr": "",
        "toAddr": "",
        "timezone": "",
        "lastSentAt": None,
        "lastError": None,
    }


class DigestStore:
    """Single-row digest configuration (SQLite) + secret in secrets."""

    def __init__(self, db: Database, secrets: SecretsStore) -> None:
        self._db = db
        self._secrets = secrets

    async def load(self) -> dict[str, Any]:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT id, enabled, hour, source, limit_count, smtp_host, smtp_port, smtp_user, from_addr, to_addr, timezone, last_sent_at, last_error FROM digest_settings WHERE id = 1"
        )
        if row is None:
            return digest_settings_defaults()
        return {
            "enabled": bool(row["enabled"]),
            "hour": int(row["hour"]),
            "source": str(row["source"]),
            "limitCount": int(row["limit_count"]),
            "smtpHost": str(row["smtp_host"]),
            "smtpPort": int(row["smtp_port"]),
            "smtpUser": str(row["smtp_user"]),
            "fromAddr": str(row["from_addr"]),
            "toAddr": str(row["to_addr"]),
            "timezone": str(row["timezone"] or ""),
            "lastSentAt": row["last_sent_at"],
            "lastError": row["last_error"],
            "passwordConfigured": self._secrets.get("digest_smtp_password") is not None,
        }

    async def save(self, update: dict[str, Any]) -> dict[str, Any]:
        await self._db.migrate()
        current = await self.load()
        enabled = update.get("enabled", current["enabled"])
        hour = update.get("hour", current["hour"])
        source = update.get("source", current["source"])
        limit = update.get("limitCount", current["limitCount"])
        smtp_host = update.get("smtpHost", current["smtpHost"])
        smtp_port = update.get("smtpPort", current["smtpPort"])
        smtp_user = update.get("smtpUser", current["smtpUser"])
        from_addr = update.get("fromAddr", current["fromAddr"])
        to_addr = update.get("toAddr", current["toAddr"])
        timezone = update.get("timezone", current["timezone"])
        if not isinstance(hour, int) or not 0 <= hour <= 23:
            hour = current["hour"]
        if source not in _VALID_SOURCES:
            source = current["source"]
        if not isinstance(limit, int) or not 1 <= limit <= _MAX_LIMIT:
            limit = min(max(limit, 1), _MAX_LIMIT) if isinstance(limit, int) else _DEFAULT_LIMIT
        # '' = 服务器本地时区；非空必须是合法 IANA 名称，否则保留现值。
        timezone = _normalize_timezone(timezone, current["timezone"])
        await self._db.execute(
            "UPDATE digest_settings SET enabled = ?, hour = ?, source = ?, limit_count = ?, smtp_host = ?, smtp_port = ?, smtp_user = ?, from_addr = ?, to_addr = ?, timezone = ? WHERE id = 1",
            (
                1 if enabled else 0,
                hour,
                source,
                limit,
                str(smtp_host),
                int(smtp_port),
                str(smtp_user),
                str(from_addr),
                str(to_addr),
                timezone,
            ),
        )
        return await self.load()

    async def set_password(self, value: str | None) -> None:
        if value is None or value == "":
            self._secrets.delete("digest_smtp_password")
        else:
            self._secrets.set("digest_smtp_password", value)

    async def mark_sent(self) -> None:
        await self._db.execute(
            "UPDATE digest_settings SET last_sent_at = ?, last_error = NULL WHERE id = 1",
            (utc_now(),),
        )

    async def mark_error(self, error: str) -> None:
        await self._db.execute(
            "UPDATE digest_settings SET last_error = ? WHERE id = 1",
            (error[:500],),
        )


def compose_digest(
    title: str, items: list[dict[str, Any]], *, base_url: str = ""
) -> tuple[str, str]:
    """(text, html) pair; HTML keeps a minimal inline-safe structure."""
    lines = [f"{title}", ""]
    html_parts = [f"<h2>{title}</h2>", "<ol>"]
    for index, item in enumerate(items, start=1):
        entry_title = str(item.get("title") or "(无标题)")
        url = str(item.get("url") or "")
        source = str(item.get("source") or "")
        lines.append(f"{index}. {entry_title}" + (f" — {source}" if source else ""))
        if url:
            lines.append(f"   {url}")
        html_parts.append(
            f'<li><p><strong>{_esc(entry_title)}</strong>'
            + (f' <span style="color:#888">· {_esc(source)}</span>' if source else "")
            + (f'<br/><a href="{_esc(url)}">{_esc(url)}</a>' if url else "")
            + "</p></li>"
        )
    html_parts.append("</ol>")
    lines.append("")
    lines.append("由 LumiRSS 汇总发送")
    html_parts.append('<p style="color:#888">由 LumiRSS 汇总发送</p>')
    return "\n".join(lines), "\n".join(html_parts)


def _esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def send_digest_smtp(
    *,
    host: str,
    port: int,
    user: str,
    password: str,
    from_addr: str,
    to_addr: str,
    subject: str,
    text: str,
    html: str,
) -> None:
    """One synchronous SMTP send with STARTTLS + typed failures."""
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = from_addr or user
    message["To"] = to_addr
    message.set_content(text)
    message.add_alternative(html, subtype="html")
    try:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            try:
                context = ssl.create_default_context()
                smtp.starttls(context=context)
            except smtplib.SMTPNotSupportedError:
                pass  # relay is TLS-on-connect or plaintext local sink
            if user and password:
                smtp.login(user, password)
            smtp.send_message(message)
    except smtplib.SMTPAuthenticationError as exc:
        raise SmtpSendFailed("SMTP 认证失败。", "auth_failed") from exc
    except (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, OSError) as exc:
        raise SmtpSendFailed("SMTP 服务器无法连接。", "unreachable") from exc
    except smtplib.SMTPException as exc:
        raise SmtpSendFailed("SMTP 发送失败。", "send_failed") from exc


class DigestScheduler:
    """Hourly check inside the BFF's shared background loop.

    ``hour`` is interpreted in the CONFIGURED IANA timezone (migration
    0024; ``timezone=''`` keeps the historical server-local semantics).
    The once-per-boundary marker compares the persisted UTC
    ``last_sent_at`` converted to the SAME timezone, so restarts stay
    idempotent and a deployment move never shifts send times. A fixed
    ``clock`` can be injected for deterministic tests (cross-day, DST).
    Concurrency-safe via a process-local flag.
    """

    def __init__(self, db: Database, *, clock: Any = None) -> None:
        self._db = db
        self._busy = False
        self._clock = clock

    def _now(self, timezone: str) -> datetime:
        if self._clock is not None:
            return self._clock(timezone)
        return now_in_timezone(timezone)

    async def maybe_send(self, send_fn) -> None:
        if self._busy:
            return
        row = await self._db.fetch_one(
            "SELECT enabled, hour, timezone, last_sent_at FROM digest_settings WHERE id = 1"
        )
        if row is None or not row["enabled"]:
            return
        timezone = str(row["timezone"] or "")
        now = self._now(timezone)
        if now.hour != int(row["hour"]):
            return
        last_sent_at = str(row["last_sent_at"] or "")
        if last_sent_at:
            try:
                last = datetime.fromisoformat(last_sent_at.replace("Z", "+00:00"))
                if timezone:
                    last = last.astimezone(ZoneInfo(timezone))
                else:
                    last = last.astimezone()
            except ValueError:
                last = None
            if last is not None and (
                last.strftime("%Y-%m-%dT%H") == now.strftime("%Y-%m-%dT%H")
            ):
                return
        self._busy = True
        try:
            await send_fn()
        finally:
            self._busy = False


# -- Server-derived digest content + background scheduling (P0-06a/b/j) -----


async def build_bridge_digest_items(
    bridge: MailBridgeStore, limit: int
) -> list[dict[str, Any]]:
    """Digest items from the bridge's OWN recent entries (bounded)."""
    entries = await bridge.recent_digest_items(limit)
    return [
        {
            "title": str(entry["subject"]),
            "url": "",
            "source": str(entry.get("list_name") or ""),
        }
        for entry in entries
    ]


async def deliver_digest(
    db: Database,
    secrets: SecretsStore,
    settings: dict[str, Any],
    items: list[dict[str, Any]],
) -> None:
    """Compose + send via the configured relay, then record the outcome.

    Shared by the send-now route and the scheduler so both paths send
    exactly the same server-derived shape."""
    text, html = compose_digest(_DIGEST_TITLE, items)
    store = DigestStore(db, secrets)
    password = secrets.get("digest_smtp_password") or ""
    try:
        send_digest_smtp(
            host=settings["smtpHost"],
            port=settings["smtpPort"],
            user=settings["smtpUser"],
            password=password,
            from_addr=settings["fromAddr"] or settings["smtpUser"],
            to_addr=settings["toAddr"],
            subject=_DIGEST_TITLE,
            text=text,
            html=html,
        )
    except SmtpSendFailed as exc:
        await store.mark_error(str(exc))
        raise
    await store.mark_sent()


async def _send_scheduled_digest(app_state: Any) -> None:
    """The scheduler's send: enabled+hour already gated by maybe_send.

    Honest failure modes (never an empty email): a non-mail source is
    reported (read_later/starred server-side aggregation is not built
    yet), and an empty bridge simply records the reason."""
    db, secrets = app_state.db, app_state.secrets_store
    store = DigestStore(db, secrets)
    settings = await store.load()
    if not settings["smtpHost"] or not settings["toAddr"]:
        await store.mark_error("SMTP 未配置完成（服务器或收件地址缺失）。")
        return
    if settings["source"] != "mail":
        await store.mark_error(
            "定时摘要当前仅支持 source=mail（bridge 列表）；"
            "read_later/starred 的服务端聚合尚未实现。"
        )
        return
    items = await build_bridge_digest_items(
        MailBridgeStore(db), settings["limitCount"]
    )
    if not items:
        await store.mark_error("没有可发送的摘要条目（bridge 列表暂无邮件）。")
        return
    await deliver_digest(db, secrets, settings, items)


async def digest_scheduler_loop(app_state: Any) -> None:
    """Background digest check, per user (0067/O163): every active
    user's own schedule runs under that user's context; failures are
    isolated and logged, never fatal."""
    from lumirss.user_scope import for_each_active_user

    logger = logging.getLogger("lumirss.mail_digest")

    async def tick_user(_uid: str) -> None:
        scheduler = DigestScheduler(app_state.db)
        await scheduler.maybe_send(lambda: _send_scheduled_digest(app_state))

    while True:
        await asyncio.sleep(_SCHEDULE_TICK_SECONDS)
        try:
            await for_each_active_user(app_state, tick_user)
        except Exception:  # noqa: BLE001 — scheduling must never kill the app
            logger.exception("scheduled digest cycle failed; will retry next tick")


def build_digest_scheduler_task(app_state: Any) -> asyncio.Task:
    """Lifespan wiring factory — main.py creates the task in TWO lines
    (see the phase2 recovery report for the exact diff); disabling is
    implicit: enabled=False or a missed hour makes every tick a no-op."""
    return asyncio.create_task(digest_scheduler_loop(app_state))
