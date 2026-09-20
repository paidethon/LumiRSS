"""F114 派生数据保留策略 —— 配置/预览/有界应用（SQL 唯一入口）。

清理对象是「派生数据」（可再生成的机器生成物），用户内容绝不触碰：
- ai_versions：ai_summary_versions（summary/translation 等历史版本）；
- task_log：ai_task_log（诊断埋点，本就 500 条有界）；
- quiz：quiz_sessions（固定 24h 说明性口径——本期不在 apply 中删除，
  预览如实计入，删除窗口固定，避免「看起来能配但配了没用」）。

保护类（excluded，负向测试覆盖）：entries / annotations / notes /
cards / credentials / running_jobs —— 永不清理。

配置存 lumi_settings 单键 JSON（``storage.retention``），与 portable
设置严格分离（这不是便携偏好，是本机存储运维）。应用逐类 LIMIT 500/批，
边界 = now - days；预览与应用同一裁剪函数（口径一致）。
"""

import json
from datetime import datetime, timedelta
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

RETENTION_KEY = "storage.retention"
_BATCH = 500
_MAX_BATCHES = 40  # 单次 apply 每类上限 40×500=2 万行（有界执行）


def default_retention() -> dict[str, Any]:
    return {
        "enabled": False,
        "aiVersionsDays": None,  # None = 未启用该类（30–365）
        "taskLogDays": None,  # None = 未启用该类（7–180）
    }


def _clamp_days(value: Any, low: int, high: int) -> int | None:
    if value is None:
        return None
    try:
        days = int(value)
    except (TypeError, ValueError):
        return None
    if days < low or days > high:
        return None
    return days


async def load_retention(db: Database) -> dict[str, Any]:
    await db.migrate()
    row = await db.fetch_one(
        "SELECT value FROM lumi_settings WHERE key = ?", (RETENTION_KEY,)
    )
    if row is None:
        return default_retention()
    try:
        raw = json.loads(str(row["value"]))
    except ValueError:
        return default_retention()
    if not isinstance(raw, dict):
        return default_retention()
    return {
        "enabled": bool(raw.get("enabled", False)),
        "aiVersionsDays": _clamp_days(raw.get("aiVersionsDays"), 30, 365),
        "taskLogDays": _clamp_days(raw.get("taskLogDays"), 7, 180),
    }


async def save_retention(db: Database, values: dict[str, Any]) -> dict[str, Any]:
    await db.migrate()
    merged = {
        "enabled": bool(values.get("enabled", False)),
        "aiVersionsDays": _clamp_days(values.get("aiVersionsDays"), 30, 365),
        "taskLogDays": _clamp_days(values.get("taskLogDays"), 7, 180),
    }
    await db.execute(
        "INSERT INTO lumi_settings (key, value, updated_at) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (RETENTION_KEY, json.dumps(merged, ensure_ascii=False), utc_now()),
    )
    return merged


def _cutoff(now: datetime, days: int | None) -> str | None:
    if not days or days <= 0:
        return None
    return (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S+00:00")


async def retention_preview(db: Database, now: datetime | None = None) -> dict[str, Any]:
    """预览（只读）：各类「将被清理」的行数与估算字节（分开——口径不
    冒充）；保护类如实列出（负向测试断言其计数恒 0 且不进删除路径）。"""
    now = now or datetime.now().astimezone()
    config = await load_retention(db)
    await db.migrate()
    result: dict[str, Any] = {
        "enabled": config["enabled"],
        "aiVersions": {"count": 0, "bytes": 0},
        "taskLog": {"count": 0},
        "excluded": {
            "entries": 0,
            "annotations": 0,
            "notes": 0,
            "cards": 0,
            "credentials": "保护不清理",
            "runningJobs": "保护不清理",
        },
        "quizNote": "测验会话固定保留 24 小时（口径说明，不可配置）。",
    }
    ai_cutoff = _cutoff(now, config["aiVersionsDays"])
    if ai_cutoff:
        row = await db.fetch_one(
            "SELECT COUNT(*) AS n, COALESCE(SUM(LENGTH(summary)), 0) AS b FROM ai_summary_versions WHERE created_at < ?",
            (ai_cutoff,),
        )
        if row is not None:
            result["aiVersions"] = {"count": int(row["n"]), "bytes": int(row["b"])}
    log_cutoff = _cutoff(now, config["taskLogDays"])
    if log_cutoff:
        row = await db.fetch_one(
            "SELECT COUNT(*) AS n FROM ai_task_log WHERE created_at < ?",
            (log_cutoff,),
        )
        if row is not None:
            result["taskLog"] = {"count": int(row["n"])}
    return result


async def retention_apply(db: Database, now: datetime | None = None) -> dict[str, Any]:
    """有界应用（逐类 LIMIT 500/批；预览与应用同一裁剪口径）。"""
    now = now or datetime.now().astimezone()
    config = await load_retention(db)
    await db.migrate()
    if not config["enabled"]:
        return {"enabled": False, "deleted": {"aiVersions": 0, "taskLog": 0}, "note": "保留策略未启用（no-op）。"}
    deleted = {"aiVersions": 0, "taskLog": 0}

    def _tx(connection: Any) -> None:
        ai_cutoff = _cutoff(now, config["aiVersionsDays"])
        if ai_cutoff:
            for _ in range(_MAX_BATCHES):
                cursor = connection.execute(
                    "DELETE FROM ai_summary_versions WHERE seq IN (SELECT seq FROM ai_summary_versions WHERE created_at < ? LIMIT ?)",
                    (ai_cutoff, _BATCH),
                )
                removed = max(cursor.rowcount, 0)
                deleted["aiVersions"] += removed
                if removed < _BATCH:
                    break
        log_cutoff = _cutoff(now, config["taskLogDays"])
        if log_cutoff:
            for _ in range(_MAX_BATCHES):
                cursor = connection.execute(
                    "DELETE FROM ai_task_log WHERE rowid IN (SELECT rowid FROM ai_task_log WHERE created_at < ? LIMIT ?)",
                    (log_cutoff, _BATCH),
                )
                removed = max(cursor.rowcount, 0)
                deleted["taskLog"] += removed
                if removed < _BATCH:
                    break

    from lumirss.db_tx import transaction

    await transaction(db, _tx)
    return {"enabled": True, "deleted": deleted}
