"""GPT 日报持久化（M4）——配置与调度标记的 SQL 唯一入口。

数据边界：日报是 Lumi 自有生成内容（issue/引用/配置），不是 FreshRSS
RSS 域数据的影子拷贝；引用条目只保存服务端已解析的 title/url/发布时间
等可重建元数据。订阅 token 存 SecretsStore（``gpt_digest_feed_token``），
永不进 SQLite、日志或 API 响应正文之外的地方。

``last_issue_key``（配置时区墙钟日期，如 ``2026-09-18``）是调度幂等
标记：与 mail_digest 的 last_sent_at 同一语义——重启/并发下同一日只
产生一个逻辑发布结果。
"""

import secrets as _secrets_mod
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from lumirss.secrets_store import SecretsStore
from lumirss.storage import Database
from lumirss.util import utc_now

_DEFAULT_LIMIT = 12
_MAX_LIMIT = 40
_MIN_WINDOW_HOURS = 1
_MAX_WINDOW_HOURS = 72
FEED_TOKEN_KEY = "gpt_digest_feed_token"


def gpt_digest_settings_defaults() -> dict[str, Any]:
    return {
        "enabled": False,
        "hour": 8,
        "timezone": "",
        "windowHours": 24,
        "limitCount": _DEFAULT_LIMIT,
        "lastIssueKey": None,
        "lastError": None,
    }


def normalize_timezone(value: Any, fallback: str) -> str:
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


def issue_key_for(now: datetime, timezone: str) -> str:
    """窗口结束时刻在配置时区的墙钟日期 = 期号（修订共享同一期号）。"""
    if timezone:
        return now.astimezone(ZoneInfo(timezone)).strftime("%Y-%m-%d")
    return now.astimezone().strftime("%Y-%m-%d")


class GptDigestStore:
    """Single-row GPT digest configuration + schedule marker."""

    def __init__(self, db: Database, secrets: SecretsStore) -> None:
        self._db = db
        self._secrets = secrets

    async def load(self) -> dict[str, Any]:
        await self._db.migrate()
        row = await self._db.fetch_one(
            "SELECT enabled, hour, timezone, window_hours, limit_count, last_issue_key, last_error FROM gpt_digest_settings WHERE id = 1"
        )
        if row is None:
            return gpt_digest_settings_defaults()
        return {
            "enabled": bool(row["enabled"]),
            "hour": int(row["hour"]),
            "timezone": str(row["timezone"] or ""),
            "windowHours": int(row["window_hours"]),
            "limitCount": int(row["limit_count"]),
            "lastIssueKey": row["last_issue_key"],
            "lastError": row["last_error"],
        }

    async def save(self, update: dict[str, Any]) -> dict[str, Any]:
        await self._db.migrate()
        current = await self.load()
        enabled = update.get("enabled", current["enabled"])
        hour = update.get("hour", current["hour"])
        window = update.get("windowHours", current["windowHours"])
        limit = update.get("limitCount", current["limitCount"])
        if not isinstance(hour, int) or not 0 <= hour <= 23:
            hour = current["hour"]
        if not isinstance(window, int):
            window = current["windowHours"]
        window = min(max(window, _MIN_WINDOW_HOURS), _MAX_WINDOW_HOURS)
        if not isinstance(limit, int):
            limit = current["limitCount"]
        limit = min(max(limit, 1), _MAX_LIMIT)
        timezone = normalize_timezone(update.get("timezone", current["timezone"]), current["timezone"])
        await self._db.execute(
            "UPDATE gpt_digest_settings SET enabled = ?, hour = ?, timezone = ?, window_hours = ?, limit_count = ? WHERE id = 1",
            (1 if enabled else 0, hour, timezone, window, limit),
        )
        return await self.load()

    async def mark_error(self, error: str) -> None:
        await self._db.execute(
            "UPDATE gpt_digest_settings SET last_error = ? WHERE id = 1",
            (str(error)[:500],),
        )

    async def mark_published(self, issue_key: str) -> None:
        await self._db.execute(
            "UPDATE gpt_digest_settings SET last_issue_key = ?, last_error = NULL WHERE id = 1",
            (issue_key,),
        )

    def feed_token(self) -> str | None:
        return self._secrets.get(FEED_TOKEN_KEY)

    def ensure_feed_token(self) -> str:
        token = self._secrets.get(FEED_TOKEN_KEY)
        if token:
            return token
        token = _secrets_mod.token_urlsafe(24)
        self._secrets.set(FEED_TOKEN_KEY, token)
        return token

    def rotate_feed_token(self) -> str:
        token = _secrets_mod.token_urlsafe(24)
        self._secrets.set(FEED_TOKEN_KEY, token)
        return token

    def now_utc(self) -> str:
        return utc_now()
