"""Storage usage reporting (F36) — read-only, honest accounting.

口径（全部显式区分，未知返回 null 而不冒充零）：
- database：lumi.sqlite 主库 + WAL/SHM 旁置文件字节数；
- libraryAssets：library_assets 表的元数据行数、字节数与去重后字节数
  （同一 sha256 的资产只计一次物理占用）；
- backups：本地备份目录（递归）文件数与字节数；
- totalKnownBytes：上述已知项之和（不含任何 null 分量）。
预算提醒：LUMIRSS_STORAGE_BUDGET_MB > 0 时按 totalKnownBytes 比较，
超过 80% 输出 warning（默认关闭，绝不自动删除任何用户内容）。
"""

import logging
from datetime import UTC
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request

from lumirss.config import LumiSettings
from lumirss.models import StorageUsage

router = APIRouter()
_logger = logging.getLogger("lumirss.storage")

_WARN_RATIO = 0.8


def _dir_usage(path: Path) -> dict[str, int]:
    total = 0
    count = 0
    if path.is_dir():
        for child in path.rglob("*"):
            try:
                if child.is_file():
                    total += child.stat().st_size
                    count += 1
            except OSError:  # noqa: PERF203 — 单文件失败不影响整体统计
                continue
    return {"count": count, "bytes": total}


def _file_bytes(path: Path) -> int:
    try:
        return path.stat().st_size if path.is_file() else 0
    except OSError:
        return 0


@router.get("/api/v1/storage/usage", response_model=StorageUsage)
async def storage_usage(request: Request) -> dict[str, Any]:
    await request.app.state.db.migrate()  # 统计前确保表已建（新库直接可查）
    settings = LumiSettings()
    db_path = Path(settings.LUMIRSS_DB_PATH).expanduser()
    database_bytes = sum(
        _file_bytes(Path(str(db_path) + suffix)) for suffix in ("", "-wal", "-shm")
    )
    assets: dict[str, Any] = {"count": None, "bytes": None, "uniqueBytes": None}
    try:
        row = await request.app.state.db.fetch_one(
            "SELECT COUNT(*) AS n, COALESCE(SUM(bytes), 0) AS total FROM library_assets"
        )
        if row is not None:
            assets["count"] = int(row["n"])
            assets["bytes"] = int(row["total"])
        unique = await request.app.state.db.fetch_one(
            "SELECT COALESCE(SUM(bytes), 0) AS total FROM library_assets a WHERE NOT EXISTS (SELECT 1 FROM library_assets b WHERE b.sha256 = a.sha256 AND (b.created_at < a.created_at OR (b.created_at = a.created_at AND b.uuid < a.uuid)))"
        )
        if unique is not None:
            assets["uniqueBytes"] = int(unique["total"])
    except Exception:  # noqa: BLE001 — 统计失败诚实返回 null，不影响其它分类
        _logger.debug("library_assets usage unavailable", exc_info=True)
    backups = _dir_usage(settings.local_backups_dir)
    total_known = database_bytes + int(assets.get("bytes") or 0) + int(backups["bytes"])
    budget_mb = settings.LUMIRSS_STORAGE_BUDGET_MB
    warning = None
    if budget_mb > 0:
        budget_bytes = budget_mb * 1024 * 1024
        ratio = total_known / budget_bytes if budget_bytes else 0
        if ratio >= 1:
            warning = f"存储用量已超过预算（{total_known} / {budget_bytes} 字节）。"
        elif ratio >= _WARN_RATIO:
            warning = f"存储用量接近预算（{round(ratio * 100)}%）。"
    return {
        "database": {"bytes": database_bytes},
        "libraryAssets": assets,
        "backupsDir": backups,
        "totalKnownBytes": total_known,
        "budgetMB": budget_mb if budget_mb > 0 else None,
        "warning": warning,
        "generatedAt": _utc_now(),
    }


def _utc_now() -> str:
    from datetime import datetime

    return datetime.now(UTC).isoformat(timespec="seconds")
