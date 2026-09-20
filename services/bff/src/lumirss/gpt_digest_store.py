"""GPT 日报持久化（M4）——配置与调度标记的 SQL 唯一入口。

数据边界：日报是 Lumi 自有生成内容（issue/引用/配置），不是 FreshRSS
RSS 域数据的影子拷贝；引用条目只保存服务端已解析的 title/url/发布时间
等可重建元数据。订阅 token 存 SecretsStore（``gpt_digest_feed_token``），
永不进 SQLite、日志或 API 响应正文之外的地方。

``last_issue_key``（配置时区墙钟日期，如 ``2026-09-18``）是调度幂等
标记：与 mail_digest 的 last_sent_at 同一语义——重启/并发下同一日只
产生一个逻辑发布结果。
"""

import asyncio
import secrets as _secrets_mod
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from lumirss.secrets_store import SecretsStore
from lumirss.storage import Database
from lumirss.token_hash import hash_token, is_token_hash
from lumirss.util import utc_now

_DEFAULT_LIMIT = 12
_MAX_LIMIT = 40
_MIN_WINDOW_HOURS = 1
_MAX_WINDOW_HOURS = 72
_MAX_PER_SOURCE_CAP = 5
FEED_TOKEN_KEY = "gpt_digest_feed_token"
FEED_TOKEN_ROTATED_AT_KEY = "gpt_digest_feed_rotated_at"


def gpt_digest_settings_defaults() -> dict[str, Any]:
    return {
        "enabled": False,
        "hour": 8,
        "timezone": "",
        "windowHours": 24,
        "limitCount": _DEFAULT_LIMIT,
        "perSourceCap": 2,
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
    """兼容外观（0027 起）：旧单配置接口投影到 gpt_digest_configs 的
    配置 1（「默认日报」）。订阅 token 仍由本类持有（SecretsStore）。"""

    def __init__(self, db: Database, secrets: SecretsStore) -> None:
        self._db = db
        self._secrets = secrets

    def _configs(self):
        from lumirss.gpt_digest_configs import GptDigestConfigStore

        return GptDigestConfigStore(self._db)

    async def load(self) -> dict[str, Any]:
        config = await self._configs().get_config(1)
        if config is None:  # 迁移前的极端情况：给出默认形状
            return gpt_digest_settings_defaults()
        return {
            "enabled": config["enabled"],
            "hour": config["hour"],
            "timezone": config["timezone"],
            "windowHours": config["windowHours"],
            "limitCount": config["limitCount"],
            "perSourceCap": config["perSourceCap"],
            "lastIssueKey": config["lastIssueKey"],
            "lastError": config["lastError"],
        }

    async def save(self, update: dict[str, Any]) -> dict[str, Any]:
        await self._configs().update_config(1, dict(update))
        return await self.load()

    async def mark_error(self, error: str) -> None:
        await self._configs().mark_error(1, str(error))

    async def mark_published(self, issue_key: str) -> None:
        await self._configs().mark_published(1, issue_key)

    def feed_token(self) -> str | None:
        return self._secrets.get(FEED_TOKEN_KEY)

    def ensure_feed_token(self) -> str | None:
        """§13.4：secrets 文件只存 SHA-256（单向验证）。

        返回**原始 token** 仅当本次调用刚刚创建它（响应一次性展示订阅
        地址）；已存在（哈希或旧明文）→ 原地升级为哈希并返回 None——
        「再次查看」从此不可用，新地址经轮换一次性获取。"""
        token = self._secrets.get(FEED_TOKEN_KEY)
        if token:
            if not is_token_hash(token):
                self._secrets.set(FEED_TOKEN_KEY, hash_token(token))
            return None
        token = _secrets_mod.token_urlsafe(24)
        self._secrets.set(FEED_TOKEN_KEY, hash_token(token))
        _stamp_rotated_at(self._db)
        return token

    def rotate_feed_token(self, *, dry_run: bool = False) -> str | None:
        """F103：dry_run=True 时零变更（只读现 token，供影响预览）；
        False 执行轮换并记录时刻（旧链接立即失效的语义不变）。"""
        if dry_run:
            return None
        # §13.4：落盘哈希；明文仅在轮换响应出现一次（旧链接立即失效）。
        token = _secrets_mod.token_urlsafe(24)
        self._secrets.set(FEED_TOKEN_KEY, hash_token(token))
        _stamp_rotated_at(self._db)
        return token


_background_tasks: set[asyncio.Task[None]] = set()


def _stamp_rotated_at(db: Database) -> None:
    """记录 token 写入时刻（尽力而为：失败不影响 token 本身）。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    task = loop.create_task(_write_rotated_at(db))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


async def _write_rotated_at(db: Database) -> None:
    import json as _json

    await db.migrate()
    await db.execute(
        "INSERT INTO lumi_settings (key, value, updated_at) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (FEED_TOKEN_ROTATED_AT_KEY, _json.dumps(utc_now()), utc_now()),
    )


async def feed_token_impact(secrets: SecretsStore, db: Database) -> dict[str, Any]:
    """F103 dry-run 影响报告：现 token 的写入时刻与年龄（天，按墙钟
    截断；无记录 → None——诚实报未知，不编造）。零变更。"""
    import json as _json
    from datetime import datetime as _dt

    token = secrets.get(FEED_TOKEN_KEY)
    await db.migrate()
    row = await db.fetch_one(
        "SELECT value FROM lumi_settings WHERE key = ?",
        (FEED_TOKEN_ROTATED_AT_KEY,),
    )
    rotated_at: str | None = None
    age_days: int | None = None
    if row is not None:
        try:
            rotated_at = str(_json.loads(str(row["value"])))
        except ValueError:
            rotated_at = str(row["value"]) or None
    if rotated_at:
        try:
            stamp = _dt.fromisoformat(rotated_at.replace("Z", "+00:00"))
            age_days = max(
                0,
                int(
                    (_dt.now(stamp.tzinfo) - stamp).total_seconds() // 86400
                ),
            )
        except ValueError:
            age_days = None
    return {
        "tokenExists": bool(token),
        "tokenRotatedAt": rotated_at,
        "ageDays": age_days,
        "note": "轮换后旧链接立即失效；订阅方需更新。",
    }

    def now_utc(self) -> str:
        return utc_now()
