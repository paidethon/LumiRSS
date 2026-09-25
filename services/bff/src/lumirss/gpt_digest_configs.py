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
_STAGE_KEYS = ("select", "summarize", "polish")
_MAX_MODEL_STR = 200
_MAX_COLUMNS = 8
_MAX_COLUMN_COUNT = 20
_EMPTY_POLICIES = ("hide", "placeholder")
# N179：缺刊处理策略（backfill=补刊，默认——既有行为；merge_into_next=
# 错过的窗口材料并入下一期；skip=跳过并记录 skip_log）。
MISSED_ISSUE_POLICIES = ("backfill", "merge_into_next", "skip")
_DEFAULT_POLICY = "backfill"
_MAX_POLICY_NAME = 20
# N179：缺刊跳过/并入记录上限（store 层裁剪最旧）。
_MAX_SKIP_LOG = 30


def parse_missed_issue_policy(value: Any) -> str:
    """N179：策略解析（非法/缺失回退 backfill——与历史行为一致）。"""
    text = str(value or "").strip()
    return text if text in MISSED_ISSUE_POLICIES else _DEFAULT_POLICY


def parse_skip_log(value: Any) -> list[dict[str, str]]:
    """N179：skip_log_json → [{date, reason}]（损坏/缺失诚实回退空列表；
    最多保留最近 _MAX_SKIP_LOG 条）。"""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    if not isinstance(value, list):
        return []
    entries: list[dict[str, str]] = []
    for raw in value:
        if not isinstance(raw, dict):
            continue
        date = str(raw.get("date") or "")[:_MAX_POLICY_NAME]
        reason = str(raw.get("reason") or "")[:40]
        if date:
            entries.append({"date": date, "reason": reason})
    return entries[-_MAX_SKIP_LOG:]


def append_skip_log(entries: list[dict[str, str]], date: str, reason: str) -> list[dict[str, str]]:
    """N179：幂等追加一条 {date, reason}（同 date+reason 不重复），
    超出上限裁掉最旧。纯函数——返回新列表。"""
    clean_date = str(date or "")[:_MAX_POLICY_NAME]
    clean_reason = str(reason or "")[:40]
    if not clean_date:
        return list(entries)
    rest = [
        e for e in entries
        if not (e.get("date") == clean_date and e.get("reason") == clean_reason)
    ]
    rest.append({"date": clean_date, "reason": clean_reason})
    return rest[-_MAX_SKIP_LOG:]


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


def parse_columns(value: Any) -> list[dict[str, Any]]:
    """N174：栏目结构解析（list 或 JSON 串）→ 规范化栏目列表。

    每项 {name, count, emptyPolicy}：name 非空（≤60 字符）、count 收敛到
    1–20、emptyPolicy 仅 hide|placeholder（非法回退 hide）；最多 8 栏，
    超出丢弃；空 = 不启用固定栏目。"""
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            value = json.loads(text)
        except ValueError:
            return []
    if not isinstance(value, list):
        return []
    columns: list[dict[str, Any]] = []
    for raw in value[:_MAX_COLUMNS]:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        count = raw.get("count", 5)
        if isinstance(count, bool) or not isinstance(count, int):
            count = 5
        policy = raw.get("emptyPolicy")
        if policy not in _EMPTY_POLICIES:
            policy = "hide"
        columns.append(
            {
                "name": name[:60],
                "count": min(max(count, 1), _MAX_COLUMN_COUNT),
                "emptyPolicy": policy,
            }
        )
    return columns


def parse_allow_list(raw: str) -> list[str]:
    """逗号/换行/空白分隔的子串匹配规则（小写、去空）。"""
    parts = str(raw or "").replace(",", "\n").replace(";", "\n").split()
    return [part.lower() for part in (p.strip() for p in parts) if part.strip()]


def parse_stage_models(value: Any) -> dict[str, str]:
    """N172：分阶段模型解析（dict 或 JSON 串）→ {stage: model}。

    只接受 select / summarize / polish 三个阶段键；值必须是非空字符串
    （截断到 200 字符）；缺失/空 = 该阶段回退基础模型。用户配置什么
    模型串就用什么——服务端绝不发明模型名。"""
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            value = json.loads(text)
        except ValueError:
            return {}
    if not isinstance(value, dict):
        return {}
    result: dict[str, str] = {}
    for key in _STAGE_KEYS:
        raw = value.get(key)
        if isinstance(raw, str) and raw.strip():
            result[key] = raw.strip()[:_MAX_MODEL_STR]
    return result


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
    # N172：分阶段模型（空对象 = 全部用基础模型，单次调用行为不变）。
    stage_models = values.get("stageModels", fallback.get("stageModels", {}))
    if not isinstance(stage_models, str):
        stage_models = json.dumps(parse_stage_models(stage_models))
    else:
        stage_models = json.dumps(parse_stage_models(stage_models))
    # N174：固定栏目结构（'[]' = 不启用）。
    columns = values.get("columns", fallback.get("columns", []))
    if not isinstance(columns, str):
        columns = json.dumps(parse_columns(columns))
    else:
        columns = json.dumps(parse_columns(columns))
    # N175：目标阅读时长（分钟；0 = 不启用）。
    target_minutes = values.get(
        "targetReadingMinutes", fallback.get("targetReadingMinutes", 0)
    )
    if isinstance(target_minutes, bool) or not isinstance(target_minutes, int):
        target_minutes = fallback.get("targetReadingMinutes", 0)
    # N176：同事件聚合开关（默认关）。
    cluster_enabled = values.get("clusterEnabled", fallback.get("clusterEnabled", False))
    source_kind = values.get("sourceKind", fallback.get("sourceKind", "window"))
    if source_kind not in ("window", "read_later", "starred"):
        source_kind = fallback.get("sourceKind", "window")
    # N179：缺刊处理策略（非法回退 backfill）。
    missed_policy = parse_missed_issue_policy(
        values.get("missedIssuePolicy", fallback.get("missedIssuePolicy", _DEFAULT_POLICY))
    )
    return {
        "hour": hour,
        "windowHours": min(max(window, 1), 72),
        "limitCount": min(max(limit, 1), 40),
        "perSourceCap": min(max(per_source, 0), 5),
        "lookbackDays": min(max(lookback, 0), 90),
        "slots": slots,
        "days": days,
        "weekendHours": weekend_hours,
        "stageModels": stage_models,
        "columns": columns,
        "targetReadingMinutes": min(max(target_minutes, 0), 600),
        "clusterEnabled": 1 if cluster_enabled else 0,
        "sourceKind": source_kind,
        "missedIssuePolicy": missed_policy,
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
        # N172：分阶段模型（空对象 = 全部用基础模型）。
        "stageModels": parse_stage_models(row["stage_models_json"]) if "stage_models_json" in keys else {},
        # N174/N175/N176：栏目结构 / 阅读时长 / 同事件聚合。
        "columns": parse_columns(row["columns_json"]) if "columns_json" in keys else [],
        "targetReadingMinutes": int(row["target_reading_minutes"]) if "target_reading_minutes" in keys else 0,
        "clusterEnabled": bool(row["cluster_enabled"]) if "cluster_enabled" in keys else False,
        # N179：缺刊处理策略与跳过/并入记录（cap 30）。
        "missedIssuePolicy": parse_missed_issue_policy(row["missed_issue_policy"]) if "missed_issue_policy" in keys else "backfill",
        "skipLog": parse_skip_log(row["skip_log_json"]) if "skip_log_json" in keys else [],
        "lastIssueKey": row["last_issue_key"],
        "lastError": row["last_error"],
        "createdAt": str(row["created_at"] or ""),
    }


class GptDigestConfigStore:
    """CRUD + per-config schedule markers."""

    _COLUMNS = (
        "id, name, enabled, hour, timezone, window_hours, limit_count, "
        "per_source_cap, lookback_days, feed_url_allow, source_kind, slots, "
        "days_json, weekend_hours, stage_models_json, columns_json, "
        "target_reading_minutes, cluster_enabled, "
        "missed_issue_policy, skip_log_json, "
        "last_issue_key, last_error, created_at"
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
            "INSERT INTO gpt_digest_configs (name, enabled, hour, timezone, window_hours, limit_count, per_source_cap, lookback_days, feed_url_allow, source_kind, slots, days_json, weekend_hours, stage_models_json, columns_json, target_reading_minutes, cluster_enabled, missed_issue_policy, created_at) VALUES (?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                clamped["stageModels"],
                clamped["columns"],
                clamped["targetReadingMinutes"],
                clamped["clusterEnabled"],
                clamped["missedIssuePolicy"],
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
            "UPDATE gpt_digest_configs SET name = ?, enabled = ?, hour = ?, timezone = ?, window_hours = ?, limit_count = ?, per_source_cap = ?, lookback_days = ?, feed_url_allow = ?, source_kind = ?, slots = ?, days_json = ?, weekend_hours = ?, stage_models_json = ?, columns_json = ?, target_reading_minutes = ?, cluster_enabled = ?, missed_issue_policy = ? WHERE id = ?",
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
                clamped["stageModels"],
                clamped["columns"],
                clamped["targetReadingMinutes"],
                clamped["clusterEnabled"],
                clamped["missedIssuePolicy"],
                config_id,
            ),
        )
        return await self.get_config(config_id)

    async def append_config_skip_log(self, config_id: int, date: str, reason: str) -> bool:
        """N179：往配置的 skip log 幂等追加一条 {date, reason}（cap 30）。

        调度路径用：skip 策略记 policy_skip；merge_into_next 记
        merged_into_next（兼作幂等标记——同一次缺刊不重复并入）。
        配置不存在 → False。"""
        current = await self.get_config(config_id)
        if current is None:
            return False
        updated = append_skip_log(
            list(current.get("skipLog") or []), date, reason
        )
        await self._db.execute(
            "UPDATE gpt_digest_configs SET skip_log_json = ? WHERE id = ?",
            (json.dumps(updated, ensure_ascii=False), config_id),
        )
        return True

    async def skip_log_has(self, config_id: int, date: str, reason: str) -> bool:
        """N179：该 (date, reason) 是否已在记录中（幂等判定的真实依据）。"""
        current = await self.get_config(config_id)
        if current is None:
            return False
        clean_date = str(date or "")[:_MAX_POLICY_NAME]
        clean_reason = str(reason or "")[:40]
        return any(
            e.get("date") == clean_date and e.get("reason") == clean_reason
            for e in (current.get("skipLog") or [])
        )

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
