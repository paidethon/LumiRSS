"""Backup routes (moved verbatim from main.py)."""


import asyncio
import json
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, model_validator

from lumirss.backup import (
    BackupBusy,
    BackupInvalid,
    BackupNotFound,
    _job_json,
    assess_freshrss_backup,
)
from lumirss.config import LumiSettings
from lumirss.deps import (
    _get_backup_engine,
    _get_backup_jobs,
    _get_restore_service,
    _get_webdav_settings,
)
from lumirss.models import (
    BackupCapabilities,
    BackupJob,
    RemoteBackupsResponse,
    RestorePreview,
    RestoreResult,
    WebDavSettingsView,
    WebDavTestResult,
)
from lumirss.webdav import WebDavError, WebDavNotConfigured

router = APIRouter()

_NO_STORE = {"Cache-Control": "no-store"}


async def _require_admin(request: Request) -> JSONResponse | None:
    """O167：全实例备份/恢复是运营操作——包含量身于所有用户的数据
    （每用户库、凭据状态、任务账本）。member 一律 403；basic 模式下
    只存在 owner，行为不变。服务端角色判定，绝不信任请求体。"""
    from lumirss.config import LumiSettings as _LS
    from lumirss.user_scope import principal_of

    if _LS().LUMIRSS_AUTH_MODE != "session":
        return None
    principal = principal_of(request.scope)
    if principal is None or principal.get("role") not in ("owner", "admin"):
        return JSONResponse(
            status_code=403,
            content={"error": {"type": "forbidden", "message": "Administrator role required."}},
            headers=_NO_STORE,
        )
    return None


class WebDavSettingsPut(BaseModel):
    """PUT /api/v1/backups/webdav body.

    password omitted/None = keep existing; non-empty = set; clearPassword
    is the ONLY way to clear it (empty-string password never clears)."""

    serverUrl: str | None = None
    username: str | None = None
    password: str | None = None
    remoteDir: str | None = None
    tlsVerify: bool | None = None
    clearPassword: bool = False

    @model_validator(mode="after")
    def password_semantics(self) -> "WebDavSettingsPut":
        if self.password is not None and not self.password and not self.clearPassword:
            raise ValueError("use clearPassword=true to clear (empty string does not clear)")
        if self.password is not None and self.clearPassword:
            raise ValueError("provide either password or clearPassword, not both")
        return self


def _webdav_json(doc: dict, password_configured: bool) -> dict[str, object]:
    return {
        "configured": bool(doc.get("serverUrl")) and password_configured,
        "serverUrl": doc.get("serverUrl", ""),
        "username": doc.get("username", ""),
        "remoteDir": doc.get("remoteDir", ""),
        "tlsVerify": bool(doc.get("tlsVerify", True)),
        "passwordConfigured": password_configured,
    }


@router.get("/api/v1/backups/webdav", response_model=WebDavSettingsView)
async def get_webdav_settings(request: Request) -> dict[str, object]:
    guard = await _require_admin(request)
    if guard is not None:
        return guard
    store = _get_webdav_settings(request)
    doc = await store.load()
    return _webdav_json(doc, store.password_configured())


@router.put("/api/v1/backups/webdav", response_model=WebDavSettingsView)
async def put_webdav_settings(
    body: WebDavSettingsPut, request: Request
) -> dict[str, object]:
    """Update WebDAV settings (password write-only, never read back)."""
    guard = await _require_admin(request)
    if guard is not None:
        return guard
    store = _get_webdav_settings(request)
    update: dict[str, object] = {}
    if body.serverUrl is not None:
        update["serverUrl"] = body.serverUrl
    if body.username is not None:
        update["username"] = body.username
    if body.remoteDir is not None:
        update["remoteDir"] = body.remoteDir
    if body.tlsVerify is not None:
        update["tlsVerify"] = body.tlsVerify
    doc = await store.save(update)
    if body.clearPassword:
        store.clear_password()
    elif body.password:
        store.set_password(body.password)
    return _webdav_json(doc, store.password_configured())


@router.post(
    "/api/v1/backups/webdav/test",
    response_model=WebDavTestResult,  # exclude_none omits "message" on success
)
async def test_webdav(request: Request) -> dict[str, object]:
    """Test the WebDAV connection: create + list the backup root."""
    guard = await _require_admin(request)
    if guard is not None:
        return guard
    from lumirss.webdav import backup_root_path

    store = _get_webdav_settings(request)
    doc = await store.load()
    if not doc.get("serverUrl"):
        raise WebDavNotConfigured("WebDAV is not configured.")
    client = await store.build_client(doc)
    try:
        root = backup_root_path(doc.get("remoteDir", ""))
        await client.ensure_dir(root)
        await client.list_dir(root)
        return {"status": "ok"}
    except WebDavError as exc:
        return {"status": "failed", "message": str(exc)}
    finally:
        await client.aclose()


class BackupCreate(BaseModel):
    target: Literal["local", "webdav"] = "local"


@router.get(
    "/api/v1/backups",
    response_model=list[BackupJob],
    response_model_exclude_none=False,  # queued jobs: stage/startedAt/… null
)
async def list_backups(request: Request) -> list[dict[str, object]]:
    guard = await _require_admin(request)
    if guard is not None:
        return guard
    jobs = _get_backup_jobs(request)
    return [_job_json(job) for job in await jobs.list()]


@router.get(
    "/api/v1/backups/capabilities",
    response_model=BackupCapabilities,
)
async def backup_capabilities(request: Request) -> dict[str, object]:
    """Honest full-backup preflight (shown to the user before they click).

    Reuses the exact assessment the engine re-runs at execution time, so
    the UI can never offer a full backup the engine would refuse — and the
    engine never fails with a vaguer error than the preflight detected.
    """
    guard = await _require_admin(request)
    if guard is not None:
        return guard
    settings = LumiSettings()
    lumi_available = Path(settings.LUMIRSS_DB_PATH).expanduser().is_file()
    assessment = await asyncio.to_thread(
        assess_freshrss_backup, settings.FRESHRSS_DATA_DIR
    )
    freshrss_view: dict[str, object] = {
        "available": assessment.available,
        "reasonCode": assessment.reason_code,
        "reason": assessment.safe_reason,
        "fileCount": assessment.file_count or None,
        "sqliteFileCount": assessment.sqlite_file_count or None,
        "dbType": assessment.db_type,
    }
    includes: list[str] = []
    if lumi_available:
        includes.append("lumi.sqlite")
    if assessment.available:
        includes.append("freshrss-data")
    return {
        "fullBackupReady": lumi_available and assessment.available,
        "includes": includes,
        "lumiDatabaseAvailable": lumi_available,
        "freshrssData": freshrss_view,
    }


@router.post(
    "/api/v1/backups",
    status_code=202,
    response_model=BackupJob,
    response_model_exclude_none=False,
)
async def create_backup(
    body: BackupCreate, request: Request
) -> dict[str, object]:
    """Create a full backup job (runs in the background; poll the job)."""
    guard = await _require_admin(request)
    if guard is not None:
        return guard
    engine = _get_backup_engine(request)
    job = await engine.submit_full_backup(body.target)
    return _job_json(job)


@router.get("/api/v1/backups/remote", response_model=RemoteBackupsResponse)
async def list_remote_backups(request: Request) -> dict[str, object]:
    """List backups stored on WebDAV (flat names + sizes, no secret values)."""
    guard = await _require_admin(request)
    if guard is not None:
        return guard
    from lumirss.webdav import backup_root_path

    store = _get_webdav_settings(request)
    doc = await store.load()
    if not doc.get("serverUrl"):
        raise WebDavNotConfigured("WebDAV is not configured.")
    client = await store.build_client(doc)
    try:
        entries = await client.list_dir(backup_root_path(doc.get("remoteDir", "")))
    except WebDavError as exc:
        raise exc
    finally:
        await client.aclose()
    return {
        "backups": [
            {"fileName": entry["name"], "sizeBytes": int(entry.get("size") or 0)}
            for entry in entries
            if entry["name"].endswith(".backup")
        ]
    }


@router.get(
    "/api/v1/backups/{job_id}",
    response_model=BackupJob,
    response_model_exclude_none=False,
)
async def get_backup_job(job_id: str, request: Request) -> dict[str, object]:
    guard = await _require_admin(request)
    if guard is not None:
        return guard
    jobs = _get_backup_jobs(request)
    job = await jobs.get(job_id)
    if job is None:
        raise BackupNotFound("Backup job not found.")
    return _job_json(job)


class RestorePreviewBody(BaseModel):
    source: Literal["local", "remote"]
    jobId: str | None = None
    fileName: str | None = None


class RestoreExecuteBody(BaseModel):
    restoreSessionId: str = Field(min_length=1)
    confirmation: str = Field(min_length=1)


class BackupCompareBody(BaseModel):
    """POST /api/v1/backups/compare 体：两份本地备份的任务 id。"""

    aId: str = Field(min_length=1)
    bId: str = Field(min_length=1)


async def _read_backup_manifest(job_id: str, request: Request) -> dict[str, object]:
    """读本地备份 zip 里的 manifest.json（只读）。损坏/缺失 → 该侧
    incomparable 原因（诚实降级，绝不冒充可比）。"""
    import zipfile

    jobs = _get_backup_jobs(request)
    job = await jobs.get(job_id)
    if job is None:
        raise BackupNotFound("Backup job not found.")
    if job["status"] != "succeeded":
        raise BackupNotFound("Only succeeded backups can be compared.")
    local_path = None
    summary = job.get("summary")
    if isinstance(summary, str) and summary:
        try:
            local_path = json.loads(summary).get("localPath")
        except json.JSONDecodeError:
            local_path = None
    if not local_path:
        raise BackupNotFound("This backup has no local file.")
    path = Path(local_path)
    if not path.is_file():
        raise BackupNotFound("The local backup file is missing.")
    try:
        with zipfile.ZipFile(path) as archive:
            raw = archive.read("manifest.json")
        manifest = json.loads(raw.decode("utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("manifest is not an object")
    except Exception as exc:  # noqa: BLE001 — 损坏如实报告（该侧不可比）
        return {"ok": False, "reason": f"manifest 损坏或缺失：{type(exc).__name__}"}
    return {"ok": True, "manifest": manifest}


@router.post("/api/v1/backups/compare")
async def compare_backups(body: BackupCompareBody, request: Request) -> dict[str, object]:
    """F115：两份本地备份的 manifest 差异比较（只读——只开 zip 读句柄，
    不改文件、不触碰 mtime）。相同 → identical=true；不同类别计数逐条
    delta；未知段名（旧格式）进 incomparable——绝不显示为 0。"""
    guard = await _require_admin(request)
    if guard is not None:
        return guard
    side_a = await _read_backup_manifest(body.aId, request)
    side_b = await _read_backup_manifest(body.bId, request)
    incomparable: list[str] = []
    if not side_a.get("ok"):
        incomparable.append(f"A（{body.aId[:12]}）：{side_a.get('reason')}")
    if not side_b.get("ok"):
        incomparable.append(f"B（{body.bId[:12]}）：{side_b.get('reason')}")
    if incomparable:
        return {"identical": False, "categories": [], "schemaVersions": None, "incomparable": incomparable}
    manifest_a: dict = side_a["manifest"]  # type: ignore[assignment]
    manifest_b: dict = side_b["manifest"]  # type: ignore[assignment]
    counts_a: dict[str, int] = {
        str(k)[:80]: int(v)
        for k, v in (manifest_a.get("componentCounts") or {}).items()
        if isinstance(v, (int, float))
    }
    counts_b: dict[str, int] = {
        str(k)[:80]: int(v)
        for k, v in (manifest_b.get("componentCounts") or {}).items()
        if isinstance(v, (int, float))
    }
    # 恶意/未知 manifest 键名不进比较面（转义/截断后仅作 incomparable 提示）
    unknown = sorted((set(counts_a) | set(counts_b)) - {"lumi.sqlite", "freshrss-data"})
    categories = [
        {
            "name": name,
            "aCount": counts_a.get(name, 0) if name in counts_a else None,
            "bCount": counts_b.get(name, 0) if name in counts_b else None,
            "delta": (counts_a.get(name, 0) if name in counts_a else 0)
            - (counts_b.get(name, 0) if name in counts_b else 0),
        }
        for name in sorted(set(counts_a) | set(counts_b))
        if name not in unknown
    ]
    schema_a = manifest_a.get("lumiDbSchemaVersion")
    schema_b = manifest_b.get("lumiDbSchemaVersion")
    if unknown:
        incomparable.append("未知/旧格式段名：" + "、".join(unknown[:10]))
    identical = (
        not unknown
        and counts_a == counts_b
        and schema_a == schema_b
        and manifest_a.get("backupSchemaVersion") == manifest_b.get("backupSchemaVersion")
    )
    return {
        "identical": identical,
        "categories": categories,
        "schemaVersions": {"a": schema_a, "b": schema_b},
        "incomparable": incomparable,
    }


async def _locate_backup_package(
    body: RestorePreviewBody, request: Request
) -> tuple[Path, str]:
    """Return (local zip path, display name) for the requested source."""
    settings = LumiSettings()
    if body.source == "local":
        if not body.jobId:
            raise BackupNotFound("A jobId is required for local restore.")
        jobs = _get_backup_jobs(request)
        job = await jobs.get(body.jobId)
        if job is None:
            raise BackupNotFound("Backup job not found.")
        if job["status"] != "succeeded":
            raise BackupNotFound("Only succeeded backups can be restored.")
        summary = job.get("summary")
        local_path = None
        if isinstance(summary, str) and summary:
            try:
                local_path = json.loads(summary).get("localPath")
            except json.JSONDecodeError:
                local_path = None
        if not local_path:
            raise BackupNotFound("This backup has no local file.")
        path = Path(local_path)
        if not path.is_file():
            raise BackupNotFound("The local backup file is missing.")
        return path, path.name

    # remote
    from lumirss.webdav import backup_root_path, quote_path_segment

    if not body.fileName:
        raise BackupNotFound("A fileName is required for remote restore.")
    # 恶意 WebDAV 服务器可能构造带路径分隔符的 listing 名：本地落盘名
    # 只允许纯文件名（与远端同名文件的匹配仍按原始 fileName 精确比较）。
    if body.fileName != Path(body.fileName).name or body.fileName in ("", ".", ".."):
        raise BackupInvalid("The remote backup file name is not a plain file name.")
    store = _get_webdav_settings(request)
    doc = await store.load()
    if not doc.get("serverUrl"):
        raise WebDavNotConfigured("WebDAV is not configured.")
    client = await store.build_client(doc)
    try:
        root = backup_root_path(doc.get("remoteDir", ""))
        entries = await client.list_dir(root)
        match = next((e for e in entries if e["name"] == body.fileName), None)
        if match is None:
            raise BackupNotFound("Remote backup not found.")
        # Download into a temp file for verification.
        stage = settings.restore_staging_dir / "downloads"
        stage.mkdir(parents=True, exist_ok=True)
        dest = stage / body.fileName
        # AUDIT-037: stream to disk (bounded by MAX_TOTAL_BYTES) instead of
        # holding the whole archive in memory under the smaller in-RAM cap.
        await client.download_to(f"{root}/{quote_path_segment(body.fileName)}", dest)
    finally:
        await client.aclose()
    return dest, body.fileName


@router.post(
    "/api/v1/restore/preview",
    response_model=RestorePreview,
    response_model_exclude_none=False,  # createdAt/lumiVersion may be null
)
async def restore_preview(
    body: RestorePreviewBody, request: Request
) -> dict[str, object]:
    """Validate a backup package and return a preview + restoreSessionId."""
    guard = await _require_admin(request)
    if guard is not None:
        return guard
    zip_path, name = await _locate_backup_package(body, request)
    service = _get_restore_service(request)
    preview = await service.preview(zip_path)
    preview["fileName"] = name
    return preview


@router.post(
    "/api/v1/restore",
    response_model=RestoreResult,
    # Historical wire format: freshrssStagedAt appears only when FreshRSS
    # data was staged; safetyBackupId is always present (null when absent).
    response_model_exclude_none=False,
    response_model_exclude_unset=True,
)
async def restore_execute(
    body: RestoreExecuteBody, request: Request
) -> dict[str, object]:
    """Execute a previously previewed restore (explicit confirmation).

    AD-0018-7: the destructive restore is serialized against backups via the
    engine flag plus a DB-level guard (the guard runs the interrupted sweep
    first, so rows left by a previous process never wedge new work), and is
    recorded in ``backup_jobs`` (type=restore) as a persisted audit trail.

    Subtlety: a successful lumi restore REPLACES the database file, so the
    job row recorded before the swap may vanish with the old file, and the
    restored snapshot may carry stale active rows. After execute the ledger
    is reconciled: stale rows are marked interrupted (nothing can legitimately
    be running once the exclusive restore finished) and the restore record is
    re-created when the swap erased it."""
    guard = await _require_admin(request)
    if guard is not None:
        return guard
    engine = _get_backup_engine(request)
    service = _get_restore_service(request)
    jobs = _get_backup_jobs(request)
    if engine.running or await jobs.has_running():
        raise BackupBusy("Another job is already in progress.")
    job = await jobs.create("restore", "restore")
    await jobs.start(job["id"])
    try:
        result = await engine.run_restore(service, body.restoreSessionId, body.confirmation)
    except Exception as exc:
        # run_restore / service.execute 只抛出脱敏后的安全消息（静态文本或
        # RestoreFailed 包装），截断兜底防止异常长的内容进入 job 历史。
        safe = (str(exc).strip() or "The restore failed.")[:300]
        if await jobs.get(job["id"]) is None:
            # 替换后的数据库里已经没有这一行：补一条终态记录
            replacement = await jobs.create("restore", "restore")
            await jobs.start(replacement["id"])
            await jobs.fail(replacement["id"], safe)
        else:
            await jobs.fail(job["id"], safe)
        raise
    # 成功：快照残影的 running/queued 行全部标记 interrupted（restore 互斥，
    # 此刻不可能有真正在跑的 job），然后确保审计记录存在于当前数据库。
    await jobs.mark_stale_active_interrupted(keep_id=job["id"])
    summary = {
        "lumiRestored": result.get("lumiRestored", False),
        "freshrss": result.get("freshrss", "not_included"),
        "safetyBackupId": result.get("safetyBackupId"),
        "filename": body.restoreSessionId,
    }
    if await jobs.get(job["id"]) is None:
        replacement = await jobs.create("restore", "restore")
        await jobs.start(replacement["id"])
        await jobs.succeed(replacement["id"], summary)
    else:
        await jobs.succeed(job["id"], summary)
    return result


