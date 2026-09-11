"""Outbound digest (phase2 G5): selected articles → text+HTML email →
the user's own SMTP relay → the single configured address.

SMTP credentials live in the secrets store (never SQLite, never logs);
sending happens only when explicitly configured and enabled (disabled by
default). Errors are typed for honest UI (unreachable / auth failed /
TLS). Tests use a local in-process SMTP sink (aiosmtpd-style) — real
third-party mail is never touched.
"""

import smtplib
import ssl
from email.message import EmailMessage
from typing import Any

from lumirss.secrets_store import SecretsStore
from lumirss.storage import Database
from lumirss.util import utc_now

_DEFAULT_LIMIT = 10
_MAX_LIMIT = 50


class SmtpNotConfigured(Exception):
    """SMTP relay or recipient address is missing."""


class SmtpSendFailed(Exception):
    """The relay refused or dropped the message."""

    def __init__(self, message: str, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


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
            "SELECT id, enabled, hour, source, limit_count, smtp_host, smtp_port, smtp_user, from_addr, to_addr, last_sent_at, last_error FROM digest_settings WHERE id = 1"
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
        if not isinstance(hour, int) or not 0 <= hour <= 23:
            hour = current["hour"]
        if source not in ("read_later", "starred"):
            source = current["source"]
        if not isinstance(limit, int) or not 1 <= limit <= _MAX_LIMIT:
            limit = min(max(limit, 1), _MAX_LIMIT) if isinstance(limit, int) else _DEFAULT_LIMIT
        await self._db.execute(
            "UPDATE digest_settings SET enabled = ?, hour = ?, source = ?, limit_count = ?, smtp_host = ?, smtp_port = ?, smtp_user = ?, from_addr = ?, to_addr = ? WHERE id = 1",
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

    Idempotent across restarts: a digest is sent at most once per hour
    boundary (last_sent_at recorded in SQLite); concurrency-safe via a
    process-local flag.
    """

    def __init__(self, db: Database) -> None:
        self._db = db
        self._busy = False

    async def maybe_send(self, send_fn) -> None:
        if self._busy:
            return
        row = await self._db.fetch_one(
            "SELECT enabled, hour, last_sent_at FROM digest_settings WHERE id = 1"
        )
        if row is None or not row["enabled"]:
            return
        now = utc_now()
        hour_now = int(now[11:13])
        if hour_now != int(row["hour"]):
            return
        if row["last_sent_at"] and str(row["last_sent_at"])[:13] == now[:13]:
            return
        self._busy = True
        try:
            await send_fn()
        finally:
            self._busy = False
