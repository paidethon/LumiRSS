"""Operations routes (moved verbatim from main.py).

Scoping audit (P11): every route below reads ONLY the requesting user's
own database (RoutingDatabase: rsshub restart flags, webdav/backup state,
diagnostics counts, timeline task records) plus deployment-level probe
status strings that /health/ready already exposes publicly — no route
returns cross-user or member-identifying data, so all three keep their
logged-in own-scope semantics. Genuinely system-wide diagnostics (process
memory/uptime, control-DB counts, scheduler task states) live behind the
admin gate at GET /api/v1/admin/system (routers/admin.py).
"""



from fastapi import APIRouter, Request

from lumirss.backup import (
    _job_json,
)
from lumirss.deps import (
    _get_backup_jobs,
    _get_operations_service,
    _get_rsshub_control_store,
    _get_webdav_settings,
)
from lumirss.models import (
    OperationsStatus,
)

router = APIRouter()


@router.get(
    "/api/v1/operations/status",
    response_model=OperationsStatus,
    response_model_exclude_none=False,  # latencyMs/error/lastBackup may be null
)
async def operations_status(request: Request) -> dict[str, object]:
    """Redacted, real dependency status for the operations UI (no fake metrics)."""
    service = _get_operations_service(request)
    status = await service.full_status()
    rsshub_store = _get_rsshub_control_store(request)
    flags = await rsshub_store.restart_required_flags()
    status["rsshub"]["restartRequired"] = flags["count"] > 0
    status["rsshub"]["pendingConfigCount"] = flags["count"]
    webdav = _get_webdav_settings(request)
    doc = await webdav.load()
    jobs = _get_backup_jobs(request)
    last = await jobs.last_succeeded()
    status["backup"] = {
        "webdavConfigured": webdav.configured(doc),
        "lastBackup": _job_json(last) if last else None,
    }
    return status




@router.get("/api/v1/operations/diagnostics")
async def operations_diagnostics(request: Request) -> dict[str, object]:
    """F039 脱敏诊断包：结构与布尔存在性，绝不含任何秘密值/正文/token。

    - deps 复用 operations/status 的状态字符串（不探测比 status 更多）；
    - error_counts_by_type：近 24h 有界（backup_jobs + 日报/邮件任务账本）；
    - config_presence 只回布尔（freshrss / rsshub / ai_key / imap / obsidian）；
    - counts：feeds / entries_indexed / library_items。
    """
    import os
    import time
    from collections import Counter
    from datetime import UTC, datetime, timedelta

    from lumirss.config import LumiSettings
    from lumirss.task_records import TaskRecordStore

    db = request.app.state.db
    settings = LumiSettings()
    status = await _get_operations_service(request).full_status()

    deps = [
        {"name": "sqlite", "status": status.get("sqlite", {}).get("status", "unknown")},
        {"name": "freshrss", "status": status.get("freshrss", {}).get("status", "unknown")},
        {"name": "rsshub", "status": status.get("rsshub", {}).get("status", "unknown")},
    ]

    cutoff = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
    counts: Counter[str] = Counter()
    try:
        for task in await TaskRecordStore(db).recent_tasks(50):
            if task.get("error") and str(task.get("startedAt") or "") >= cutoff:
                counts[str(task.get("kind", "unknown"))] += 1
    except Exception:  # noqa: BLE001 — 诊断包不因账本缺失失败
        pass

    imap_present = False
    try:
        from lumirss.secrets_store import SecretsStore

        imap_present = bool(
            SecretsStore(settings.secrets_path).get("mail_imap")
        )
    except Exception:  # noqa: BLE001 — 秘密库不可用只影响布尔
        imap_present = False

    ai_key_present = False
    try:
        ai_key_present = bool(settings.AI_API_KEY.get_secret_value())
    except Exception:  # noqa: BLE001
        ai_key_present = False

    feeds = entries = library_items = 0
    try:
        row = await db.fetch_one("SELECT COUNT(*) AS n FROM search_feeds", ())
        feeds = int(row["n"]) if row else 0
        row = await db.fetch_one("SELECT COUNT(*) AS n FROM search_entries", ())
        entries = int(row["n"]) if row else 0
        row = await db.fetch_one("SELECT COUNT(*) AS n FROM library_items", ())
        library_items = int(row["n"]) if row else 0
    except Exception:  # noqa: BLE001 — 未迁移时诚实为 0
        pass

    try:
        import asyncio as _asyncio

        from lumirss.migrations import schema_version as _schema_version

        schema = await _asyncio.to_thread(_schema_version, db)
    except Exception:  # noqa: BLE001
        schema = 0

    _ = os
    return {
        "version": settings.LUMIRSS_VERSION,
        "schemaVersion": schema,
        "authMode": settings.LUMIRSS_AUTH_MODE,
        "uptimeS": int(time.monotonic()),
        "deps": deps,
        "errorCountsByType": dict(counts),
        "configPresence": {
            "freshrss": await _freshrss_configured(request),
            "rsshub": _rsshub_configured(),
            "aiKey": ai_key_present,
            "imap": imap_present,
            "obsidian": bool(settings.LUMIRSS_OBSIDIAN_VAULT_DIR),
        },
        "counts": {
            "feeds": feeds,
            "entriesIndexed": entries,
            "libraryItems": library_items,
        },
    }


async def _freshrss_configured(request: Request) -> bool:
    """0067：按当前用户绑定判定（env 只在 owner 迁移时授予 owner）。"""
    from lumirss.user_scope import principal_of

    principal = principal_of(request.scope)
    if principal is None:
        return False
    try:
        await request.app.state.db.migrate()
        row = await request.app.state.db.fetch_one("SELECT base_url FROM freshrss_binding WHERE id = 1")
        return bool(row and row["base_url"])
    except Exception:  # noqa: BLE001 — status probe must not raise
        return False


def _rsshub_configured() -> bool:
    from lumirss.config import RssHubSettings

    try:
        return bool(RssHubSettings().RSSHUB_BASE_URL)
    except Exception:  # noqa: BLE001
        return False


# -- F118 操作审计时间线 --------------------------------------------------------


@router.get("/api/v1/operations/timeline")
async def operations_timeline(request: Request, limit: int = 50) -> dict[str, object]:
    """F118：合并 task_records + ai_task_log + import_batches + 日报发布
    的统一时间线（时间倒序，上限 100）。

    只含 kind/status/摘要（计数与类型名）——绝不包含凭据、正文或任何
    秘密值（构造含秘密的库内 fixture 响应 grep 不到，负向测试覆盖）。
    失败与部分失败如实保留（不美化）。"""
    from lumirss.ai_task_log import AiTaskLogStore
    from lumirss.import_batch_store import ImportBatchStore
    from lumirss.task_records import TaskRecordStore

    db = request.app.state.db
    bounded = max(1, min(limit, 100))
    entries: list[dict[str, object]] = []

    for task in await TaskRecordStore(db).recent_tasks(bounded):
        summary = str(task.get("kind") or "task")
        if task.get("error"):
            summary = f"{summary}：{str(task['error'])[:80]}"
        entries.append(
            {
                "at": str(task.get("startedAt") or ""),
                "kind": str(task.get("kind") or "task"),
                "targetRef": str(task.get("ref") or "") or None,
                "status": str(task.get("status") or "unknown"),
                "summary": summary[:120],
            }
        )

    try:
        for row in await AiTaskLogStore(db).list_tasks(bounded):
            summary = f"AI {row['kind']}（{row['model'] or '未知模型'}）"
            if row["status"] == "failed" and row["errorType"]:
                summary += f"：失败（{row['errorType']}）"
            entries.append(
                {
                    "at": str(row["createdAt"]),
                    "kind": f"ai:{row['kind']}",
                    "targetRef": row["entryRef"],
                    "status": row["status"],
                    "summary": summary[:120],
                }
            )
    except Exception:  # noqa: BLE001 — 表缺失诚实降级
        pass

    try:
        for batch in await ImportBatchStore(db).list_batches(bounded):
            counts = batch.get("counts") or {}
            summary = (
                f"导入 {batch['kind']}：成功 {counts.get('created', counts.get('imported', 0))}，"
                f"跳过 {counts.get('skipped', 0)}，失败 {counts.get('failed', 0)}"
            )
            entries.append(
                {
                    "at": str(batch["createdAt"]),
                    "kind": f"import:{batch['kind']}",
                    "targetRef": str(batch["id"]),
                    "status": "failed" if counts.get("failed") else "done",
                    "summary": summary[:120],
                }
            )
    except Exception:  # noqa: BLE001
        pass

    try:
        rows = await db.fetch_all(
            "SELECT c.name AS config_name, i.issue_key, i.status, i.title, i.published_at FROM gpt_digest_configs c JOIN gpt_digest_issues i ON i.config_id = c.id ORDER BY i.id DESC LIMIT ?",
            (bounded,),
        )
        for row in rows:
            status = str(row["status"] or "unknown")
            title = " ".join(str(row["title"] or "").split())[:60]
            entries.append(
                {
                    "at": str(row["published_at"] or row["issue_key"]),
                    "kind": "digest:issue",
                    "targetRef": f"{row['config_name']}:{row['issue_key']}",
                    "status": status,
                    "summary": f"日报期号 {row['issue_key']}（{row['config_name']}）{status}：{title}"[:120],
                }
            )
    except Exception:  # noqa: BLE001
        pass

    entries.sort(key=lambda e: str(e["at"]), reverse=True)
    return {"items": entries[:bounded]}

