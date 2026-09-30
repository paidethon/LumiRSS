"""Admin ops responsibility slice (FIX-161): deployment diagnostics and
instance-level operation policy — the P11 system panel, the public
registration policy switch, upgrade preview (N195), deploy status
(N196) and rollback readiness (N197). Routes moved verbatim from the
former ``routers/admin.py`` monolith.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from lumirss.routers.admin._common import (
    _NO_STORE,
    _accounts,
    _forbid,
    _iso,
    _require_admin,
)

router = APIRouter()


# ---- P11: admin-only system diagnostics -------------------------------------
#
# GET /admin/system — server-derived, non-secret deployment diagnostics for
# the admin console 系统 panel: build provenance (health.py pattern), runtime
# uptime/memory/CPU (proc + stdlib resource; psutil is NOT a dependency and
# none is added), store row counts (control DB + the requesting admin's OWN
# user-DB projection only — never other members' content), optional-service
# availability (reuses the operations.py probes with their bounded timeouts)
# and background scheduler task states from main.py's app.state slots (no
# last-run tracking exists anywhere — the field stays honestly null).
#
# No shell exec, no Docker socket, no env dump, no secrets: every value below
# is a number, a boolean or one of the fixed status strings the operations
# surface already return.


_SYSTEM_TASK_SLOTS: tuple[tuple[str, str], ...] = (
    # (app.state attribute name, stable task name) — mirrors main.py lifespan.
    ("search_sync_task", "search_sync"),
    ("obsidian_scan_task", "obsidian_scan"),
    ("digest_scheduler_task", "digest_scheduler"),
    ("mail_imap_task", "mail_imap"),
    ("gpt_digest_scheduler_task", "gpt_digest_scheduler"),
    ("rag_idle_task", "rag_idle"),
    ("rag_index_task", "rag_index"),
)


def _task_state(task: object) -> str:
    """Honest asyncio.Task state — never guessed, never prettified."""
    import asyncio

    if task is None:
        return "off"  # slot disabled at lifespan (e.g. interval=0)
    if not isinstance(task, asyncio.Task):
        return "unknown"
    if task.cancelled():
        return "cancelled"
    if not task.done():
        return "running"
    return "failed" if task.exception() is not None else "completed"


# N194：探针时效 — checkedAt 早于该阈值的探针在管理台标注「过期」。
# 服务端在响应序列化前即时计算（探针本身每次请求现跑，正常恒为
# fresh；UI 若持有超过 5 分钟的旧响应也能据此诚实降级展示）。
_PROBE_STALE_AFTER_S = 300.0


def _probe_freshness(
    checked_at: str | None, now_epoch: float | None = None
) -> tuple[str | None, bool]:
    """(checkedAt, stale) — server-side probe age computation.

    ``checked_at`` is the server timestamp at which the probe ran
    (operations.py already stamps ``lastCheckedAt``). ``None`` means the
    probe ran during THIS response (presence-only services, or a probe
    that does not stamp its own time) — the server clock at computation
    time is then the honest checkedAt. ``stale`` is True exactly when
    the probe is older than 5 minutes; an unparseable timestamp
    degrades the same way: we never claim staleness we cannot prove."""
    import time as _time

    if now_epoch is None:
        now_epoch = _time.time()
    if not checked_at:
        return (
            _time.strftime("%Y-%m-%dT%H:%M:%S+00:00", _time.gmtime()),
            False,
        )
    try:
        parsed = datetime.fromisoformat(str(checked_at))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        age_s = now_epoch - parsed.timestamp()
    except ValueError:
        return (
            _time.strftime("%Y-%m-%dT%H:%M:%S+00:00", _time.gmtime()),
            False,
        )
    return str(checked_at), age_s > _PROBE_STALE_AFTER_S


def _uptime_seconds() -> int | None:
    """Process uptime from /proc (starttime vs /proc/uptime); honest null
    where /proc does not exist — clock-monotonic-since-boot is NOT uptime."""
    try:
        import os
        from pathlib import Path

        stat = Path("/proc/self/stat").read_text()
        fields = stat.rsplit(")", 1)[1].split()
        start_ticks = int(fields[19])  # field 22 (starttime); fields start at 3
        clk = os.sysconf("SC_CLK_TCK")
        boot_uptime = float(Path("/proc/uptime").read_text().split()[0])
        return max(0, int(boot_uptime - start_ticks / clk))
    except Exception:  # noqa: BLE001 — non-Linux or odd /proc → honest null
        return None


def _process_metrics() -> dict[str, object]:
    """RSS (current via /proc, peak via stdlib resource) + CPU seconds."""
    rss_bytes: int | None = None
    try:
        from pathlib import Path

        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                rss_bytes = int(line.split()[1]) * 1024  # kB → bytes
                break
    except Exception:  # noqa: BLE001 — non-Linux → resource fallback below
        rss_bytes = None
    peak_bytes: int | None = None
    cpu_seconds: float | None = None
    try:
        import resource

        usage = resource.getrusage(resource.RUSAGE_SELF)
        peak_bytes = int(usage.ru_maxrss) * 1024  # Linux reports kB
        cpu_seconds = round(usage.ru_utime + usage.ru_stime, 3)
    except Exception:  # noqa: BLE001 — metrics are best-effort, never fatal
        pass
    return {"rssBytes": rss_bytes, "peakRssBytes": peak_bytes, "cpuTimeS": cpu_seconds}


async def _system_counts(request: Request) -> dict[str, int]:
    """Row counts only. Control DB: identity/invite/pool/session facts.
    User scope: the requesting admin's OWN projection counts (same tables
    the sanitized diagnostics bundle exposes) — never other members' data."""
    import time

    counts = {
        "users": 0,
        "activeUsers": 0,
        "invites": 0,
        "freshrssPoolReady": 0,
        "freshrssPoolAssigned": 0,
        "sessions": 0,
        "feeds": 0,
        "entriesIndexed": 0,
        "libraryItems": 0,
    }
    control = request.app.state.control_db
    try:
        await control.migrate()
        for key, sql in (
            ("users", "SELECT COUNT(*) AS n FROM users"),
            ("activeUsers", "SELECT COUNT(*) AS n FROM users WHERE status = 'active'"),
            ("invites", "SELECT COUNT(*) AS n FROM invites"),
            ("freshrssPoolReady", "SELECT COUNT(*) AS n FROM freshrss_pool WHERE state = 'ready'"),
            ("freshrssPoolAssigned", "SELECT COUNT(*) AS n FROM freshrss_pool WHERE state = 'assigned'"),
            ("sessions", "SELECT COUNT(*) AS n FROM auth_sessions WHERE expires_at > ?"),
        ):
            params = (int(time.time()),) if key == "sessions" else ()
            row = await control.fetch_one(sql, params)
            counts[key] = int(row["n"]) if row else 0
    except Exception:  # noqa: BLE001 — unmigrated control DB → honest zeros
        pass
    # Own-scope (RoutingDatabase under the authenticated admin's context).
    db = request.app.state.db
    try:
        await db.migrate()
        for key, table in (
            ("feeds", "search_feeds"),
            ("entriesIndexed", "search_entries"),
            ("libraryItems", "library_items"),
        ):
            row = await db.fetch_one(f"SELECT COUNT(*) AS n FROM {table}", ())
            counts[key] = int(row["n"]) if row else 0
    except Exception:  # noqa: BLE001 — unmigrated user DB → honest zeros
        pass
    return counts


@router.get("/system", response_model=None)
async def system_status(request: Request) -> dict[str, object]:
    """Admin-only deployment diagnostics (P11). See the block comment above
    for the non-secret guarantee and the deliberate scoping: cross-user /
    system-wide facts live ONLY behind this gate; the per-user
    /api/v1/operations/* endpoints stay own-scope by design."""
    import asyncio
    import platform
    import time

    from lumirss.config import LumiSettings
    from lumirss.deps import _get_operations_service, _get_webdav_settings

    if await _require_admin(request) is None:
        return _forbid()
    settings = LumiSettings()
    service = _get_operations_service(request)
    sqlite_st, freshrss_st, rsshub_st = await asyncio.gather(
        service.sqlite_status(), service.freshrss_status(), service.rsshub_status()
    )

    def _presence(status: str) -> bool:
        return status != "unconfigured"

    freshrss_configured = _presence(str(freshrss_st.get("status", "unknown")))
    rsshub_configured = _presence(str(rsshub_st.get("status", "unknown")))

    obsidian = False
    try:
        obsidian = bool(settings.LUMIRSS_OBSIDIAN_VAULT_DIR)
    except Exception:  # noqa: BLE001 — presence probing never raises
        obsidian = False
    webdav_configured = False
    try:
        webdav_settings = _get_webdav_settings(request)
        doc = await webdav_settings.load()
        webdav_configured = webdav_settings.configured(doc)
    except Exception:  # noqa: BLE001
        webdav_configured = False
    ai_key_present = False
    try:
        ai_key_present = bool(settings.AI_API_KEY.get_secret_value())
    except Exception:  # noqa: BLE001
        ai_key_present = False
    imap_present = False
    try:
        from lumirss.secrets_store import SecretsStore

        imap_present = bool(SecretsStore(settings.secrets_path).get("mail_imap"))
    except Exception:  # noqa: BLE001
        imap_present = False

    def _bool_service(name: str, configured: bool) -> dict[str, object]:
        checked_at, stale = _probe_freshness(None, time.time())
        return {
            "name": name,
            "configured": configured,
            "status": "configured" if configured else "unconfigured",
            "latencyMs": None,
            # N194：presence-only 服务没有真实探针——checkedAt 取响应
            # 构建时刻（服务端时钟），stale 恒 False。
            "checkedAt": checked_at,
            "stale": stale,
        }

    def _probed_service(
        name: str, configured: bool, probe: dict, default_status: str
    ) -> dict[str, object]:
        checked_at, stale = _probe_freshness(
            probe.get("lastCheckedAt") if isinstance(probe, dict) else None,
            time.time(),
        )
        return {
            "name": name,
            "configured": configured,
            "status": (
                str(probe.get("status", default_status))
                if isinstance(probe, dict)
                else default_status
            ),
            "latencyMs": probe.get("latencyMs") if isinstance(probe, dict) else None,
            # N194：探针完成的服务端时刻 + 5 分钟时效标志。
            "checkedAt": checked_at,
            "stale": stale,
        }

    services = [
        _probed_service("sqlite", True, sqlite_st, "unknown"),
        _probed_service("freshrss", freshrss_configured, freshrss_st, "unknown"),
        _probed_service("rsshub", rsshub_configured, rsshub_st, "unknown"),
        _bool_service("obsidian", obsidian),
        _bool_service("webdav", webdav_configured),
        _bool_service("ai", ai_key_present),
        _bool_service("imap", imap_present),
    ]

    tasks = [
        {
            "name": name,
            "enabled": getattr(request.app.state, attr, None) is not None,
            "state": _task_state(getattr(request.app.state, attr, None)),
            # No scheduler tracks last-run anywhere (checked) — honest null.
            "lastRunAt": None,
        }
        for attr, name in _SYSTEM_TASK_SLOTS
    ]

    return {
        "version": settings.LUMIRSS_VERSION,
        "commit": settings.LUMIRSS_COMMIT,
        "python": platform.python_version(),
        "apiVersion": 1,
        "uptimeS": _uptime_seconds(),
        "uptimeCheckedAt": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "process": _process_metrics(),
        "counts": await _system_counts(request),
        "services": services,
        "tasks": tasks,
    }


# ---------------------------------------------------------------------------
# P0 public-registration policy: instance-level switch owned by the
# control DB (migration 0089, InstanceSettingsStore). Defaults CLOSED on
# upgrade AND on fresh install; only this endpoint changes it, and every
# change lands in the audit log. Enforcement lives in routers/auth.py —
# this endpoint never gates anything by itself.


class RegistrationPolicyRequest(BaseModel):
    """PUT /admin/registration-policy."""

    allowPublicRegistration: bool


class RegistrationPolicyResponse(BaseModel):
    """GET / PUT /admin/registration-policy (instance-level switch)."""

    allowPublicRegistration: bool
    updatedAt: str | None = None
    updatedBy: str | None = None


def _registration_policy_response(describe: dict[str, object]) -> RegistrationPolicyResponse:
    updated_at = describe.get("updatedAt")
    return RegistrationPolicyResponse(
        allowPublicRegistration=describe["value"] == "1",
        updatedAt=_iso(int(updated_at)) if isinstance(updated_at, int) else None,
        updatedBy=str(describe["updatedBy"]) if describe.get("updatedBy") else None,
    )


@router.get("/registration-policy", response_model=RegistrationPolicyResponse)
async def get_registration_policy(request: Request) -> RegistrationPolicyResponse:
    from lumirss.instance_settings import InstanceSettingsStore

    await _require_admin(request)
    describe = await InstanceSettingsStore(request.app.state.control_db).describe(
        "allow_public_registration"
    )
    return _registration_policy_response(describe)


@router.put("/registration-policy", response_model=RegistrationPolicyResponse)
async def set_registration_policy(
    body: RegistrationPolicyRequest, request: Request
) -> RegistrationPolicyResponse:
    from lumirss.instance_settings import InstanceSettingsStore

    principal = await _require_admin(request)
    store = InstanceSettingsStore(request.app.state.control_db)
    before = await store.get_bool("allow_public_registration")
    await store.set(
        "allow_public_registration",
        "1" if body.allowPublicRegistration else "0",
        updated_by=principal["user_id"],
    )
    await _accounts(request).audit(
        actor=principal["user_id"],
        action="registration_policy_change",
        object_type="instance_setting",
        object_id="allow_public_registration",
        detail=f"{before}->{body.allowPublicRegistration}",
    )
    describe = await store.describe("allow_public_registration")
    return _registration_policy_response(describe)


@router.get("/upgrade-preview", response_model=None, response_model_exclude_none=True)
async def admin_upgrade_preview(request: Request) -> JSONResponse:
    """N195：发布清单 × 当前版本 × 迁移差异的只读推演。

    LUMIRSS_RELEASE_MANIFEST 未配置/文件不可读时如实 available:false；
    不兼容（同版本/降级/库超前于目标）→ blocked:true + 原因。绝不
    触发任何升级动作——这是预览，执行权只在 ./lumirss update。"""
    if await _require_admin(request) is None:
        return _forbid()
    from lumirss.config import LumiSettings
    from lumirss.upgrade_preview import build_upgrade_preview, preview_response

    settings = LumiSettings()
    result = build_upgrade_preview(
        manifest_path=settings.LUMIRSS_RELEASE_MANIFEST,
        current_version=settings.LUMIRSS_VERSION,
        control_db=request.app.state.control_db,
    )
    return JSONResponse(content=preview_response(**result), headers=_NO_STORE)


@router.get("/deploy-status", response_model=None, response_model_exclude_none=True)
async def admin_deploy_status(request: Request) -> JSONResponse:
    """N196：./lumirss update 写入的阶段 JSON 只读透传（admin-gated）。

    未配置/尚无记录/坏文件都是诚实 available:false + 原因；内容本身
    由脚本写入（阶段名/状态/时间戳/imageTag，绝无秘密）。本端点没有
    也永远不会有执行控件——升级只由运维侧 ./lumirss update 触发。"""
    if await _require_admin(request) is None:
        return _forbid()
    from lumirss.config import LumiSettings
    from lumirss.deploy_status import read_deploy_status

    result = read_deploy_status(LumiSettings().LUMIRSS_DEPLOY_STATUS_FILE)
    return JSONResponse(content=result, headers=_NO_STORE)


@router.get("/rollback-readiness", response_model=None, response_model_exclude_none=True)
async def admin_rollback_readiness(request: Request) -> JSONResponse:
    """N197：回滚就绪检查（admin-gated，只读要素清单）。

    - previousImage：读 ./lumirss snapshot_for_rollback 写下的回滚快照
      清单（LUMIRSS_ROLLBACK_MANIFEST_FILE）——BFF 没有 Docker 访问权，
      镜像存在性只来自脚本侧的诚实记录；
    - backup：LUMIRSS_BACKUP_DIR 里最新 *.backup + N186 只读完整性校验；
    - dbDowngrade：诚实限制说明（SQLite 迁移只向前，无法降级）；
    - canRollback = 前镜像在 AND 备份可校验 AND schema 与备份一致。

    本端点只给清单，永远不给一键回滚按钮——回滚只由运维侧
    ./lumirss rollback 触发。"""
    if await _require_admin(request) is None:
        return _forbid()
    import asyncio

    from lumirss.config import LumiSettings
    from lumirss.migrations import schema_version
    from lumirss.restore import verify_backup_findings
    from lumirss.rollback_readiness import (
        build_rollback_readiness,
        latest_backup_path,
        read_rollback_manifest,
    )

    settings = LumiSettings()
    manifest = read_rollback_manifest(settings.LUMIRSS_ROLLBACK_MANIFEST_FILE)
    latest = latest_backup_path(settings.LUMIRSS_BACKUP_DIR)
    if latest is not None:
        report = await asyncio.to_thread(
            verify_backup_findings, latest, request.app.state.control_db
        )
        backup_schema = None
        manifest_block = report.get("manifest") if isinstance(report, dict) else None
        if isinstance(manifest_block, dict):
            value = manifest_block.get("lumiDbSchemaVersion")
            backup_schema = int(value) if isinstance(value, int) else None
    else:
        report = None
        backup_schema = None
    current_schema = await asyncio.to_thread(schema_version, request.app.state.control_db)
    result = build_rollback_readiness(
        manifest=manifest,
        backup_report=report,
        backup_name=latest.name if latest is not None else None,
        current_schema_version=current_schema,
        backup_schema_version=backup_schema,
        backup_dir_configured=bool(settings.LUMIRSS_BACKUP_DIR.strip()),
    )
    return JSONResponse(content=result, headers=_NO_STORE)
