"""NEW-374 用户资源账单 —— 每账户各数据类别的占用与计算量。

口径唯一（:func:`account_bill`），member 自查与 admin 查阅共用：

- 各类别 = 每用户库真实行数：订阅源（search_feeds）/ 已索引条目
  （search_entries）/ 资料库（library_items）/ 剪藏（library_clips）/
  附件（library_assets）；磁盘字节 = 该账户用户目录的真实文件合计
  （库文件 + 资产文件分开计）；
- 计算量 = 真实可归因的两类：AI 当日调用次数（ai_usage 日窗口键）
  与最近完成的备份任务计算秒数（backup_jobs 起止差合计）；
- **绝不出现文章内容**：所有字段都是计数/字节/秒；admin 查阅他人
  账单写一条查阅台账（admin_resource_bill_views）+ 审计——管理台
  的跨账户视图只有汇总，没有内容。

诚实边界：计算秒数只统计 Lumi 自有账本里带起止戳的任务（备份）；
FreshRSS 侧的抓取消耗不经过 Lumi，无法统计，如实标注。
"""

from datetime import datetime
from pathlib import Path
from typing import Any

from lumirss.storage import Database
from lumirss.util import utc_now

_CATEGORY_TABLES: tuple[tuple[str, str], ...] = (
    ("feeds", "search_feeds"),
    ("entriesIndexed", "search_entries"),
    ("libraryItems", "library_items"),
    ("clips", "library_clips"),
    ("assets", "library_assets"),
)


def _dir_bytes(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for candidate in path.rglob("*"):
        try:
            if candidate.is_file():
                total += candidate.stat().st_size
        except OSError:  # noqa: PERF203 — 单文件不可读不计入，不中断
            continue
    return total


async def _ai_usage_today(db: Database) -> int | None:
    try:
        from lumirss.ai_quota import window_bounds

        bounds = window_bounds(window="day")
        row = await db.fetch_one(
            "SELECT calls FROM ai_usage WHERE window_key = ?", (bounds.key,)
        )
        return int(row["calls"]) if row is not None else 0
    except Exception:  # noqa: BLE001 — 计数失败如实为「未知」
        return None


async def _backup_compute_seconds(db: Database) -> int | None:
    try:
        rows = await db.fetch_all(
            "SELECT started_at, finished_at FROM backup_jobs"
            " WHERE status = 'succeeded' AND started_at IS NOT NULL AND finished_at IS NOT NULL"
            " ORDER BY id DESC LIMIT 20",
            (),
        )
    except Exception:  # noqa: BLE001
        return None
    total = 0.0
    seen = False
    for row in rows:
        try:
            start = datetime.fromisoformat(str(row["started_at"]).replace("Z", "+00:00"))
            end = datetime.fromisoformat(str(row["finished_at"]).replace("Z", "+00:00"))
        except ValueError:
            continue
        total += max(0.0, (end - start).total_seconds())
        seen = True
    return round(total, 1) if seen else 0


async def account_bill(db: Database, users_root: Path, user_id: str) -> dict[str, Any]:
    """同口径账单（db = 该账户的 per-user 库句柄；admin 查阅与 member
    自查走同一实现，只有主语不同）。"""
    counts: dict[str, int] = {}
    for key, table in _CATEGORY_TABLES:
        try:
            row = await db.fetch_one(f"SELECT COUNT(*) AS n FROM {table}", ())
            counts[key] = int(row["n"]) if row is not None else 0
        except Exception:  # noqa: BLE001 — 未迁移/缺表 → 如实 0
            counts[key] = 0
    root = Path(users_root) / user_id
    db_bytes = (
        sum(p.stat().st_size for p in root.glob("*.sqlite*") if p.is_file())
        if root.exists()
        else 0
    )
    asset_bytes = _dir_bytes(root / "assets")
    ai_used = await _ai_usage_today(db)
    return {
        "userId": user_id,
        "counts": counts,
        "storage": {
            "databaseBytes": db_bytes,
            "assetBytes": asset_bytes,
            "totalBytes": db_bytes + asset_bytes,
        },
        "compute": {
            "aiCallsToday": ai_used,
            "recentBackupSeconds": await _backup_compute_seconds(db),
        },
        "computedAt": utc_now(),
        "contentNote": "账单只有计数与字节，绝无文章内容；FreshRSS 侧抓取消耗不经过 Lumi，无法统计。",
    }


async def open_user_db(state: Any, user_id: str) -> Database:
    """为指定账户打开其 per-user 库（admin 查阅路径）。"""
    from lumirss.user_scope import RoutingDatabase

    db = state.db
    if isinstance(db, RoutingDatabase):
        target = Database(db.user_db_path(user_id))
        await target.migrate()
        return target
    return db  # 单用户部署形态：db 即本人库


async def record_admin_view(control_db: Any, *, viewer_id: str, target_user_id: str) -> None:
    await control_db.migrate()
    await control_db.execute(
        "INSERT INTO admin_resource_bill_views (viewer_id, target_user_id, viewed_at) VALUES (?, ?, ?)",
        (viewer_id, target_user_id, utc_now()),
    )


async def recent_viewers(control_db: Any, target_user_id: str, limit: int = 5) -> list[dict[str, Any]]:
    await control_db.migrate()
    rows = await control_db.fetch_all(
        "SELECT viewer_id, viewed_at FROM admin_resource_bill_views"
        " WHERE target_user_id = ? ORDER BY id DESC LIMIT ?",
        (target_user_id, max(1, min(limit, 20))),
    )
    return [
        {"viewerId": str(row["viewer_id"]), "viewedAt": str(row["viewed_at"])} for row in rows
    ]


__all__ = [
    "account_bill",
    "open_user_db",
    "recent_viewers",
    "record_admin_view",
]
