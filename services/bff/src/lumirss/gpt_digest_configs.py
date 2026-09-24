"""GPT 日报多配置的 SQL 唯一入口（F01）。

一份配置 = 一个主题日报：独立调度（hour/timezone/各自 last_issue_key
标记）、独立窗口与上限、独立来源白名单（feedUrl 子串匹配，空 =
全部订阅——不同配置的材料互不串用）。``gpt_digest_settings`` 单行表
自 0027 起保留为配置 1 的兼容投影（旧单配置端点读写它）。

删除配置级联删除其期刊：期刊是「该配置的派生生成物」，离开配置没有
独立语义（与用户笔记不同）。
"""

import json
from typing import Any

from lumirss.gpt_digest_store import normalize_timezone
from lumirss.storage import Database
from lumirss.util import utc_now

_MAX_NAME = 80
_MAX_SLOTS = 4
_MAX_DAYS = 7


def parse_days(value: Any) -> list[int]:
    """N171：发布日解析（list[int] / JSON 数组串 / 逗号串）→ 升序去重的
    0–6 星期集合（0=周一 … 6=周日）；空 = 每天发布（历史行为）。"""
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            value = json.loads(text)
        except ValueError:
            value = text.replace("[", "").replace("]", "").split(",")
    if not isinstance(value, list):
        return []
    days: set[int] = set()
    for part in value:
        try:
            day = int(part)
        except (TypeError, ValueError):
            continue
        if 0 <= day <= 6:
            days.add(day)
    return sorted(days)[:_MAX_DAYS]


def parse_slots(value: Any) -> list[int]:
    """F02：slots 解析（list[int] 或逗号字符串）→ 升序去重的 0–23 小时
    列表，最多 4 个时点；空 = 回退单 hour 字段。"""
    if isinstance(value, str):
        raw_parts = [p for p in value.replace("，", ",").split(",") if p.strip()]
    elif isinstance(value, list):
        raw_parts = value
    else:
        return []
    hours: set[int] = set()
    for part in raw_parts:
        try:
            hour = int(part)
        except (TypeError, ValueError):
            continue
        if 0 <= hour <= 23:
            hours.add(hour)
    return sorted(hours)[:_MAX_SLOTS]


def parse_allow_list(raw: str) -> list[str]:
    """逗号/换行/空白分隔的子串匹配规则（小写、去空）。"""
    parts = str(raw or "").replace(",", "\n").replace(";", "\n").split()
    return [part.lower() for part in (p.strip() for p in parts) if part.strip()]


def _clamp_config(values: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    """宽容校验：hour 非法回退现值；窗口/上限/配额收敛到合法区间。"""
    hour = values.get("hour", fallback["hour"])
    if not isinstance(hour, int) or not 0 <= hour <= 23:
        hour = fallback["hour"]
    window = values.get("windowHours", fallback["windowHours"])
    window = window if isinstance(window, int) else fallback["windowHours"]
    limit = values.get("limitCount", fallback["limitCount"])
    limit = limit if isinstance(limit, int) else fallback["limitCount"]
    per_source = values.get("perSourceCap", fallback["perSourceCap"])
    per_source = per_source if isinstance(per_source, int) else fallback["perSourceCap"]
    # F101：回看窗口（0=关，默认 7，上限 90）。
    lookback = values.get("lookbackDays", fallback.get("lookbackDays", 7))
    if not isinstance(lookback, int) or isinstance(lookback, bool):
        lookback = fallback.get("lookbackDays", 7)
    slots = values.get("slots", fallback.get("slots", ""))
    if not isinstance(slots, str):
        slots = ",".join(str(h) for h in parse_slots(slots))
    else:
        slots = ",".join(str(h) for h in parse_slots(slots))
    # N171：发布日（空 = 每天）与周末独立时点（空 = 沿用平日计划）。
    days = values.get("days", fallback.get("days", []))
    if not isinstance(days, str):
        days = json.dumps(parse_days(days))
    else:
        days = json.dumps(parse_days(days))
    weekend_hours = values.get("weekendHours", fallback.get("weekendHours", ""))
    if not isinstance(weekend_hours, str):
        weekend_hours = ",".join(str(h) for h in parse_slots(weekend_hours))
    else:
        weekend_hours = ",".join(str(h) for h in parse_slots(weekend_hours))
    source_kind = values.get("sourceKind", fallback.get("sourceKind", "window"))
    if source_kind not in ("window", "read_later", "starred"):
        source_kind = fallback.get("sourceKind", "window")
    return {
        "hour": hour,
        "windowHours": min(max(window, 1), 72),
        "limitCount": min(max(limit, 1), 40),
        "perSourceCap": min(max(per_source, 0), 5),
        "lookbackDays": min(max(lookback, 0), 90),
        "slots": slots,
        "days": days,
        "weekendHours": weekend_hours,
        "sourceKind": source_kind,
    }


def config_row_to_dict(row: Any) -> dict[str, Any]:
    slots_raw = str(row["slots"] or "")
    keys = row.keys()
    return {
        "id": int(row["id"]),
        "name": str(row["name"]),
        "enabled": bool(row["enabled"]),
        "hour": int(row["hour"]),
        "timezone": str(row["timezone"] or ""),
        "windowHours": int(row["window_hours"]),
        "limitCount": int(row["limit_count"]),
        "perSourceCap": int(row["per_source_cap"]),
        # F101：迁移前旧行无该列 → 默认 7（列有 DEFAULT，正常恒在）。
        "lookbackDays": int(row["lookback_days"]) if "lookback_days" in keys else 7,
        "feedUrlAllow": str(row["feed_url_allow"] or ""),
        "sourceKind": row["source_kind"] if row["source_kind"] in ("window", "read_later", "starred") else "window",
        "slots": parse_slots(slots_raw),
        "slotsRaw": slots_raw,
        # N171：发布日（空 = 每天）与周末独立时点（空 = 沿用平日计划）。
        "days": parse_days(row["days_json"]) if "days_json" in keys else [],
        "weekendHours": parse_slots(str(row["weekend_hours"] or "")) if "weekend_hours" in keys else [],
        "lastIssueKey": row["last_issue_key"],
        "lastError": row["last_error"],
        "createdAt": str(row["created_at"] or ""),
    }


class GptDigestConfigStore:
    """CRUD + per-config schedule markers."""

    _COLUMNS = (
        "id, name, enabled, hour, timezone, window_hours, limit_count, "
        "per_source_cap, lookback_days, feed_url_allow, source_kind, slots, "
        "days_json, weekend_hours, last_issue_key, last_error, created_at"
    )

    def __init__(self, db: Database) -> None:
        self._db = db

    async def list_configs(self) -> list[dict[str, Any]]:
        await self._db.migrate()
        rows = await self._db.fetch_all(
            f"SELECT {self._COLUMNS} FROM gpt_digest_configs ORDER BY id"
        )
        return [config_row_to_dict(row) for row in rows]

    async def get_config(self, config_id: int) -> dict[str, Any] | None:
        await self._db.migrate()
        row = await self._db.fetch_one(
            f"SELECT {self._COLUMNS} FROM gpt_digest_configs WHERE id = ?",
            (config_id,),
        )
        return config_row_to_dict(row) if row else None

    async def create_config(self, values: dict[str, Any]) -> dict[str, Any]:
        await self._db.migrate()
        name = str(values.get("name") or "").strip()[:_MAX_NAME] or "未命名日报"
        clamped = _clamp_config(values, {"hour": 8, "windowHours": 24, "limitCount": 12, "perSourceCap": 2, "lookbackDays": 7})
        await self._db.execute(
            "INSERT INTO gpt_digest_configs (name, enabled, hour, timezone, window_hours, limit_count, per_source_cap, lookback_days, feed_url_allow, source_kind, slots, days_json, weekend_hours, created_at) VALUES (?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                name,
                clamped["hour"],
                normalize_timezone(values.get("timezone"), ""),
                clamped["windowHours"],
                clamped["limitCount"],
                clamped["perSourceCap"],
                clamped["lookbackDays"],
                str(values.get("feedUrlAllow") or ""),
                clamped["sourceKind"],
                clamped["slots"],
                clamped["days"],
                clamped["weekendHours"],
                utc_now(),
            ),
        )
        row = await self._db.fetch_one(
            "SELECT id FROM gpt_digest_configs ORDER BY id DESC LIMIT 1"
        )
        assert row is not None
        config = await self.get_config(int(row["id"]))
        assert config is not None
        return config

    async def update_config(self, config_id: int, values: dict[str, Any]) -> dict[str, Any] | None:
        current = await self.get_config(config_id)
        if current is None:
            return None
        name = str(values.get("name", current["name"])).strip()[:_MAX_NAME] or current["name"]
        clamped = _clamp_config(values, current)
        await self._db.execute(
            "UPDATE gpt_digest_configs SET name = ?, enabled = ?, hour = ?, timezone = ?, window_hours = ?, limit_count = ?, per_source_cap = ?, lookback_days = ?, feed_url_allow = ?, source_kind = ?, slots = ?, days_json = ?, weekend_hours = ? WHERE id = ?",
            (
                name,
                1 if values.get("enabled", current["enabled"]) else 0,
                clamped["hour"],
                normalize_timezone(values.get("timezone", current["timezone"]), current["timezone"]),
                clamped["windowHours"],
                clamped["limitCount"],
                clamped["perSourceCap"],
                clamped["lookbackDays"],
                str(values.get("feedUrlAllow", current["feedUrlAllow"])),
                clamped["sourceKind"],
                clamped["slots"],
                clamped["days"],
                clamped["weekendHours"],
                config_id,
            ),
        )
        return await self.get_config(config_id)

    async def delete_config(self, config_id: int) -> bool:
        """删除配置并级联删除其期刊与素材池（id=1 默认配置不可删除）。"""
        if config_id <= 1:
            return False
        await self._db.migrate()
        await self._db.execute(
            "DELETE FROM digest_material_pool WHERE config_id = ?",
            (config_id,),
        )
        await self._db.execute(
            "DELETE FROM gpt_digest_issues WHERE config_id = ?",
            (config_id,),
        )
        await self._db.execute(
            "DELETE FROM gpt_digest_configs WHERE id = ?",
            (config_id,),
        )
        return True

    async def mark_published(self, config_id: int, issue_key: str) -> None:
        await self._db.migrate()
        await self._db.execute(
            "UPDATE gpt_digest_configs SET last_issue_key = ?, last_error = NULL WHERE id = ?",
            (issue_key, config_id),
        )

    async def mark_error(self, config_id: int, error: str) -> None:
        await self._db.migrate()
        await self._db.execute(
            "UPDATE gpt_digest_configs SET last_error = ? WHERE id = ?",
            (str(error)[:500], config_id),
        )
