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
from datetime import UTC, datetime, timedelta
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

RETENTION_KEY = "storage.retention"
_BATCH = 500
_MAX_BATCHES = 40  # 单次 apply 每类上限 40×500=2 万行（有界执行）

# N188：到期提醒的提前量与推迟上界。提醒只读、绝不自动触发 apply——
# apply 保持「人工点击」唯一入口（负向测试断言无自动路径）。
NOTICE_WINDOW_DAYS = 7
POSTPONE_MAX_DAYS = 30


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


# ---------------------------------------------------------------------------
# N188：到期提醒（notice，只读）+ 推迟（postpone，≤30 天）。
#
# 语义：保留策略删除「created_at < now - days」的行；某类下一次「该删
# 有可删」的时刻 = 最老一条未到期行的 created_at + days。该时刻落在
# NOTICE_WINDOW_DAYS（7 天）内，或现在就有已到期行 → 提醒（dueSoon）。
# 提醒绝不改数据；apply 保持人工唯一入口。
# ---------------------------------------------------------------------------


def _iso(dt: datetime) -> str:
    """统一转 UTC 再格式化——调用方可能传入本地时区 aware datetime，
    绝不把 +08:00 时刻错标成 +00:00。"""
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _parse_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


async def load_postpone_until(db: Database) -> datetime | None:
    await db.migrate()
    row = await db.fetch_one(
        "SELECT retention_postpone_until FROM storage_retention_state WHERE id = 1"
    )
    if row is None:
        return None
    return _parse_dt(row["retention_postpone_until"])


async def save_postpone_until(db: Database, until: datetime | None) -> datetime | None:
    """持久化推迟时刻（None = 取消推迟；>30 天的部分被钳制到上界）。"""
    await db.migrate()
    await db.execute(
        "INSERT INTO storage_retention_state (id, retention_postpone_until) VALUES (1, ?) "
        "ON CONFLICT(id) DO UPDATE SET retention_postpone_until = excluded.retention_postpone_until",
        (_iso(until) if until is not None else None,),
    )
    return until


def _class_due(
    now: datetime, days: int | None, count_past: int, earliest_pending: str | None
) -> tuple[bool, datetime | None]:
    """单类的 (dueSoon, dueAt)：已有到期行 → 立即到期；否则看最老一条
    未到期行的到期时刻是否落在提醒窗口内。"""
    if not days or days <= 0:
        return False, None
    if count_past > 0:
        return True, now
    if earliest_pending:
        created = _parse_dt(earliest_pending)
        if created is not None:
            due_at = created + timedelta(days=days)
            if due_at <= now + timedelta(days=NOTICE_WINDOW_DAYS):
                return True, due_at
    return False, None


async def retention_notice(db: Database, now: datetime | None = None) -> dict[str, Any]:
    """N188 到期提醒（只读）：复用 F114 预览口径给出将影响计数；保护类
    如实列出。 postponedUntil 生效期内提醒被抑制（dueSoon=false，如实
    保留 dueAt 供 UI 说明）。绝不触发删除。"""
    now = now or datetime.now().astimezone()
    config = await load_retention(db)
    await db.migrate()
    preview = await retention_preview(db, now)

    ai_cutoff = _cutoff(now, config["aiVersionsDays"])
    ai_due_soon, ai_due_at = False, None
    if ai_cutoff:
        row = await db.fetch_one(
            "SELECT COUNT(*) AS n FROM ai_summary_versions WHERE created_at < ?",
            (ai_cutoff,),
        )
        past = int(row["n"]) if row is not None else 0
        row = await db.fetch_one(
            "SELECT MIN(created_at) AS earliest FROM ai_summary_versions WHERE created_at >= ?",
            (ai_cutoff,),
        )
        earliest = str(row["earliest"]) if row is not None and row["earliest"] else None
        ai_due_soon, ai_due_at = _class_due(
            now, config["aiVersionsDays"], past, earliest
        )

    log_cutoff = _cutoff(now, config["taskLogDays"])
    log_due_soon, log_due_at = False, None
    if log_cutoff:
        row = await db.fetch_one(
            "SELECT COUNT(*) AS n FROM ai_task_log WHERE created_at < ?",
            (log_cutoff,),
        )
        past = int(row["n"]) if row is not None else 0
        row = await db.fetch_one(
            "SELECT MIN(created_at) AS earliest FROM ai_task_log WHERE created_at >= ?",
            (log_cutoff,),
        )
        earliest = str(row["earliest"]) if row is not None and row["earliest"] else None
        log_due_soon, log_due_at = _class_due(
            now, config["taskLogDays"], past, earliest
        )

    due_ats = [due for due in (ai_due_at, log_due_at) if due is not None]
    due_at = min(due_ats) if due_ats else None
    due_soon = bool(config["enabled"]) and (ai_due_soon or log_due_soon)

    postpone_until = await load_postpone_until(db)
    postponed = postpone_until is not None and postpone_until > now
    if postponed and due_at is not None and due_at <= postpone_until:
        due_soon = False

    return {
        "enabled": config["enabled"],
        "dueSoon": due_soon,
        "dueAt": _iso(due_at) if due_at is not None else None,
        "noticeWindowDays": NOTICE_WINDOW_DAYS,
        "postponedUntil": _iso(postpone_until) if postponed else None,
        "affectedCounts": {
            "aiVersions": preview["aiVersions"],
            "taskLog": preview["taskLog"],
        },
        "protected": [
            "entries",
            "annotations",
            "notes",
            "cards",
            "credentials",
            "runningJobs",
        ],
        "quizNote": preview["quizNote"],
    }
