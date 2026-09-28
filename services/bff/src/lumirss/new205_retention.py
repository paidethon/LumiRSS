"""NEW-205 来源保留策略预演与确认启用 —— 保留/回收事实面 + 审计台账。

与 N038（/api/v1/sources/retention-preview|apply）的分工：N038 是
策略本体与投影裁剪的**单一真源**；本模块补齐「启用前的事实面」与
「确认语义」：

- 预演（dry-run，只读）：对某来源设 N 天保留前，如实展示——
  * 将保留：收藏（starred，无论多旧恒保留）、该来源条目上的批注、
    指向该来源条目的 library 书签；
  * 将回收：starred=0 且早于截止线的投影条目数（普通缓存）；
  * 诚实口径：估算基于 Lumi 派生投影；FreshRSS 侧真实删除仍需在
    原生界面执行（沿用 N038 的 basis/note，不另造承诺）。
- 启用（enable）：必须显式 ``confirmed=true``（缺席 → 422
  confirmation_required——「确认后才启用」由服务端强制，不信任
  客户端流程）；效果 = ``set_retention_days`` + 立即裁剪本地投影
  （starred 恒排除）+ 写一行启用台账（含预演快照）。
- 负向契约：全路径零 FreshRSS/上游调用（测试以零调用间谍断言）。
"""

import json
import uuid as _uuid
from typing import Any

from lumirss.source_retention import retention_days_valid, retention_preview
from lumirss.storage import Database
from lumirss.util import utc_now


class RetentionConfirmRequired(Exception):
    """enable 未携带 confirmed=true —— 422 confirmation_required。"""


async def retention_dry_run(db: Database, feed_url: str, *, days: int) -> dict[str, Any]:
    """预演事实面（只读）：保留多少 / 回收多少（投影口径）。"""
    if not retention_days_valid(days):
        raise ValueError("days 必须在 7..3650 之间。")
    preview = await retention_preview(db, feed_url, days=days)
    await db.migrate()
    preserved_row = await db.fetch_one(
        "SELECT"
        " (SELECT COUNT(*) FROM search_entries WHERE feed_url = ? AND starred = 1) AS starred,"
        " (SELECT COUNT(*) FROM annotations WHERE entry_ref IN"
        "   (SELECT entry_ref FROM search_entries WHERE feed_url = ?)) AS annotations,"
        " (SELECT COUNT(*) FROM library_bookmarks WHERE rss_item_ref IN"
        "   (SELECT entry_ref FROM search_entries WHERE feed_url = ?)) AS bookmarks",
        (feed_url, feed_url, feed_url),
    )
    preserved = {
        "starredEntries": int(preserved_row["starred"]) if preserved_row else 0,
        "annotations": int(preserved_row["annotations"]) if preserved_row else 0,
        "libraryBookmarks": int(preserved_row["bookmarks"]) if preserved_row else 0,
    }
    return {
        "feedUrl": feed_url,
        "retentionDays": days,
        "preserved": preserved,
        "reclaimed": {
            "prunableEntries": int(preview["prunableEntries"]),
            "cutoff": preview["cutoff"],
        },
        "totalEntries": int(preview["totalEntries"]),
        "basis": "projection",
        "note": (
            "预演基于 Lumi 派生投影：收藏（starred）恒保留，批注与 library"
            " 书签不在任何删除路径上；将回收的是普通缓存条目（starred=0 且"
            "早于截止线，投影可再生成）。FreshRSS 侧真实删除需在原生界面"
            "执行。"
        ),
    }


class RetentionEnableStore:
    """启用台账（策略本体在 source_overrides，由 N038 store 持有）。"""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def record(
        self, *, feed_url: str, days: int, dry_run: dict[str, Any]
    ) -> dict[str, Any]:
        enable_id = str(_uuid.uuid4())
        enabled_at = utc_now()
        await self._db.migrate()
        await self._db.execute(
            "INSERT INTO new205_retention_enables"
            " (id, feed_url, days, dry_run_json, enabled_at) VALUES (?, ?, ?, ?, ?)",
            (enable_id, feed_url, int(days), json.dumps(dry_run, ensure_ascii=False), enabled_at),
        )
        return {"id": enable_id, "enabledAt": enabled_at}


async def retention_enable(
    db: Database,
    feed_url: str,
    *,
    days: int,
    confirmed: bool,
    override_store,
) -> dict[str, Any]:
    """确认启用：校验确认语义 → 策略落库 → 立即裁剪投影 → 台账。

    返回 {enabled, dryRun, pruned, enableRecord}。"""
    if not confirmed:
        raise RetentionConfirmRequired("必须显式 confirmed=true 才会启用保留策略。")
    dry_run = await retention_dry_run(db, feed_url, days=days)
    # 策略本体：N038 单一真源（source_overrides.retention_days）。
    await override_store.set_retention_days(feed_url, days)
    from lumirss.source_retention import prune_projection

    pruned = await prune_projection(db, feed_url, days=days)
    store = RetentionEnableStore(db)
    record = await store.record(feed_url=feed_url, days=days, dry_run=dry_run)
    return {"enabled": True, "dryRun": dry_run, "pruned": pruned, "enableRecord": record}
