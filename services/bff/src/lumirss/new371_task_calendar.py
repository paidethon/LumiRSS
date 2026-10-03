"""NEW-371 后台任务日历 —— 管理员治理本实例周期任务的最小面。

三层事实，绝不混装：

1. **计划**：每个任务档（kind）的节奏来自真实配置（env 间隔或
   digest 配置时区的发送钟点），不是拍脑袋的档期表；间隔为 0 =
   未排程（诚实呈现为「未排程」，不是「空闲」）。相位（下一次
   运行的具体时刻）只有 digest 可从配置推得；轮询间隔型任务如实
   返回 plannedNext: null——编一个「下次 03:00」是撒谎。

2. **最近结果**：既有真源是 F35 的各域账本（backup_jobs /
   gpt_digest_issues / digest_settings），按账户聚合（计数 + 状态 +
   时间，无任何内容）；`admin_task_runs` 是调度器级结果的统一补充
   落点（治理写入与测试）。

3. **暂停**：每类至多一条 active 暂停，影响说明必填——暂停而不
   说明影响等于制造静默故障。生效点分两档并如实标注 enforcedBy：
   ``loop``（本组在 main.py 自有循环里逐 tick 检查：search_sync /
   obsidian_scan）与 ``declared``（digest/RAG 等外部循环尚未消费该
   注册表——如实声明，绝不伪装成「已停止」）。绝不开放任意 shell，
   「暂停」不向任何进程发送信号。
"""

from datetime import datetime, timedelta
from typing import Any

from lumirss.db_tx import transaction
from lumirss.util import utc_now

# kind → (label, 节奏来源说明)。kind 必须与 main.py 的调度槽一一对应。
TASK_KIND_LABELS: dict[str, str] = {
    "search_sync": "搜索投影同步（逐账户）",
    "obsidian_scan": "Obsidian 仓库扫描",
    "rag_index": "RAG 增量索引",
    "digest_scheduler": "邮件摘要调度",
    "mail_imap": "IMAP 邮件轮询",
    "gpt_digest_scheduler": "GPT 日报调度",
    "rag_idle": "RAG 空闲卸载",
}

# 本组自有消费点（main.py 循环在 tick 前检查 paused_task_kinds）。
# R24：rag_index 的 tick 检查落在 rag_incremental_loop（rag.py——main.py
# 只负责一行 lifespan 挂载），语义同为 loop 实时生效。
LOOP_ENFORCED_KINDS = frozenset({"search_sync", "obsidian_scan", "rag_index"})

MAX_REASON = 200
MAX_IMPACT = 500
_MAX_RESULTS = 10

_FOREIGN_LOOP_NOTE = (
    "该任务的循环属既有调度实现，本轮未接入暂停注册表——暂停在此为"
    "治理意图记录（enforcedBy=declared），不会被伪装成已停止；生效"
    "点接入属于该循环自身模块。"
)


class TaskKindUnknown(ValueError):
    """未知任务档（422）。"""


class PauseAlreadyActive(Exception):
    """该任务档已有生效中的暂停（409）。"""


class PauseNotActive(Exception):
    """该任务档没有生效中的暂停（404）。"""


def clean_pause_fields(reason: Any, impact: Any) -> tuple[str, str]:
    if not isinstance(reason, str) or not reason.strip():
        raise TaskKindUnknown("reason 必须是非空字符串。")
    if not isinstance(impact, str) or not impact.strip():
        raise TaskKindUnknown("暂停必须说明影响（impact 非空）。")
    reason = reason.strip()
    impact = impact.strip()
    if len(reason) > MAX_REASON:
        raise TaskKindUnknown(f"reason 最长 {MAX_REASON} 字。")
    if len(impact) > MAX_IMPACT:
        raise TaskKindUnknown(f"impact 最长 {MAX_IMPACT} 字。")
    return reason, impact


def kind_exists(kind: str) -> bool:
    return kind in TASK_KIND_LABELS


async def paused_task_kinds(control_db: Any) -> set[str]:
    """main.py 循环 tick 前调用的轻量检查：当前被暂停的 kind 集合。"""
    await control_db.migrate()
    rows = await control_db.fetch_all(
        "SELECT kind FROM admin_task_pauses WHERE status = 'active'", ()
    )
    return {str(row["kind"]) for row in rows if kind_exists(str(row["kind"]))}


async def record_task_result(
    control_db: Any, *, kind: str, status: str, started_at: str,
    finished_at: str | None = None, error: str | None = None,
    ref: str | None = None,
) -> int:
    """调度器级结果统一落点（kind 必须是已知档；error 只存脱敏文案）。"""
    if not kind_exists(kind):
        raise TaskKindUnknown(f"unknown task kind: {kind}.")
    await control_db.migrate()

    def _write(conn: Any) -> int:
        cursor = conn.execute(
            "INSERT INTO admin_task_runs (kind, status, started_at, finished_at, error, ref, recorded_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (kind, status, started_at, finished_at, error, ref, utc_now()),
        )
        return int(cursor.lastrowid)

    return int(await transaction(control_db, _write))


def _interval_seconds(kind: str) -> int | None:
    from lumirss.config import LumiSettings

    settings = LumiSettings()
    if kind == "search_sync":
        return int(settings.LUMIRSS_SEARCH_SYNC_INTERVAL)
    if kind == "obsidian_scan":
        return int(settings.LUMIRSS_OBSIDIAN_SCAN_INTERVAL)
    if kind == "rag_index":
        return int(settings.LUMIRSS_RAG_INDEX_INTERVAL)
    return None


def _slot_task(app_state: Any, kind: str) -> Any:
    return getattr(app_state, _SLOT_ATTRS.get(kind, ""), None)


_SLOT_ATTRS: dict[str, str] = {
    "search_sync": "search_sync_task",
    "obsidian_scan": "obsidian_scan_task",
    "rag_index": "rag_index_task",
    "digest_scheduler": "digest_scheduler_task",
    "mail_imap": "mail_imap_task",
    "gpt_digest_scheduler": "gpt_digest_scheduler_task",
    "rag_idle": "rag_idle_task",
}


_DIGEST_NEXT_NOTE = (
    "邮件摘要按每账户自己的配置钟点发送（digest_settings）；实例日历"
    "不汇总各账户的私人钟点，下一次发送时刻请看对应账户的摘要设置。"
)


def _pause_json(row: Any) -> dict[str, Any]:
    return {
        "active": str(row["status"]) == "active",
        "reason": str(row["reason"]),
        "impact": str(row["impact"]),
        "createdAt": str(row["created_at"]),
        "createdBy": str(row["created_by"]),
        "liftedAt": row["lifted_at"],
    }


async def pause_kind(
    control_db: Any, *, kind: str, reason: str, impact: str, by: str
) -> dict[str, Any]:
    if not kind_exists(kind):
        raise TaskKindUnknown(f"unknown task kind: {kind}.")
    reason, impact = clean_pause_fields(reason, impact)
    await control_db.migrate()

    def _write(conn: Any) -> dict[str, Any]:
        active = conn.execute(
            "SELECT id FROM admin_task_pauses WHERE kind = ? AND status = 'active'",
            (kind,),
        ).fetchone()
        if active is not None:
            raise PauseAlreadyActive(kind)
        conn.execute(
            "INSERT INTO admin_task_pauses (kind, reason, impact, status, created_by, created_at)"
            " VALUES (?, ?, ?, 'active', ?, ?)",
            (kind, reason, impact, by, utc_now()),
        )
        return {"kind": kind, "paused": True, "reason": reason, "impact": impact}

    return await transaction(control_db, _write)


async def resume_kind(control_db: Any, *, kind: str, by: str) -> dict[str, Any]:
    if not kind_exists(kind):
        raise TaskKindUnknown(f"unknown task kind: {kind}.")
    await control_db.migrate()

    def _write(conn: Any) -> dict[str, Any]:
        row = conn.execute(
            "SELECT id FROM admin_task_pauses WHERE kind = ? AND status = 'active'",
            (kind,),
        ).fetchone()
        if row is None:
            raise PauseNotActive(kind)
        conn.execute(
            "UPDATE admin_task_pauses SET status = 'lifted', lifted_at = ?, lifted_by = ? WHERE id = ?",
            (utc_now(), by, int(row["id"])),
        )
        return {"kind": kind, "paused": False}

    return await transaction(control_db, _write)


async def _active_pauses(control_db: Any) -> dict[str, dict[str, Any]]:
    rows = await control_db.fetch_all(
        "SELECT kind, reason, impact, status, created_at, created_by, lifted_at"
        " FROM admin_task_pauses ORDER BY id DESC", ()
    )
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row["kind"])
        if key in result:
            continue  # 最新一行代表现状（active 优先顺序即 id DESC）
        result[key] = _pause_json(row)
    return result


async def _aggregate_user_results(db: Any, limit: int) -> list[dict[str, Any]]:
    """当前主语（admin 本人库）的 F35 账本聚合 + 日历台账。

    跨账户结果在本面只给计数汇总（运维统计不携带任何成员内容）；
    admin 想看某个账户的细节应使用该账户自己的账单/任务面。"""
    from lumirss.task_records import TaskRecordStore

    records = await TaskRecordStore(db).recent_tasks(limit)
    return records[: _MAX_RESULTS]


async def calendar_snapshot(app_state: Any, control_db: Any, db: Any) -> dict[str, Any]:
    """GET /admin/task-calendar 的口径：计划 × 槽位实况 × 暂停 × 最近结果。"""
    await control_db.migrate()
    from lumirss.runtime import SCHEDULERS

    owned = set(SCHEDULERS.owned_names())
    pauses = await _active_pauses(control_db)
    paused_now = await paused_task_kinds(control_db)

    kinds: list[dict[str, Any]] = []
    for kind, label in TASK_KIND_LABELS.items():
        interval = _interval_seconds(kind)
        slot = _slot_task(app_state, kind)
        running = slot is not None and getattr(slot, "done", None) is not None and not slot.done()
        scheduled = kind in owned or (interval is not None and interval > 0)
        pause = pauses.get(kind, {"active": False})
        entry: dict[str, Any] = {
            "kind": kind,
            "label": label,
            "intervalSeconds": interval,
            "scheduled": scheduled,
            "slotState": "running" if running else ("not_scheduled" if not scheduled else "registered"),
            "plannedNext": None,
            "pause": pause,
            "pauseEnforced": kind in paused_now,
            "enforcedBy": "loop" if kind in LOOP_ENFORCED_KINDS else "declared",
            "impact": pause.get("impact") if pause.get("active") else None,
        }
        if pause.get("active") and entry["enforcedBy"] == "declared":
            entry["pauseNote"] = _FOREIGN_LOOP_NOTE
        kinds.append(entry)

    runs = await control_db.fetch_all(
        "SELECT kind, status, started_at, finished_at, error, ref FROM admin_task_runs"
        " ORDER BY id DESC LIMIT ?",
        (_MAX_RESULTS,),
    )
    return {
        "kinds": kinds,
        "recentRuns": [
            {
                "kind": str(row["kind"]),
                "status": str(row["status"]),
                "startedAt": str(row["started_at"]),
                "finishedAt": row["finished_at"],
                "error": row["error"],
                "ref": row["ref"],
            }
            for row in runs
        ],
        "ownScopeResults": await _aggregate_user_results(db, _MAX_RESULTS),
        "notes": [
            "间隔型任务的运行相位未知（plannedNext 为 null 是诚实值）。",
            _DIGEST_NEXT_NOTE,
            "enforcedBy=declared 的暂停是治理意图记录，未接入对应循环时不生效。",
            "本面不提供任何 shell / 信号入口；暂停是注册表事实，不是进程控制。",
        ],
    }


def next_local_day_boundary(now: datetime | None = None) -> str:
    """测试与维护窗口默认值的公共锚点（本地时区明日 00:00）。"""
    base = now or datetime.now().astimezone()
    return (base + timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).isoformat(timespec="seconds")
